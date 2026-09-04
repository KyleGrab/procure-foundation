"""
Orchestrates duplicate-SKU detection (spec §107) and supplier-consolidation flagging (spec §22)
using Phase 2's matching engine (app.matching.scorer - proven, tests_pure/test_matching.py). No
new matching logic - this module's only job is which SKU sets to compare and persisting flags for
human review, never auto-merging or auto-recommending (same principle as product matching itself).

Pairwise (O(n²)) comparison - acceptable for typical supplier catalog sizes (hundreds to low
thousands of SKUs), not built for a national retailer's full catalog. If that becomes the actual
scale, this needs blocking/indexing before the O(n²) scan, not a rewrite of the matching logic.
"""
from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.domain_graph import (
    ConsolidationFlagInput,
    ConsolidationReviewAction,
    SupplierInput,
    build_supplier_consolidation_graph,
    determine_consolidation_flag_transition,
)
from app.db.models import (
    DuplicateSkuFlag,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseTransaction,
    Supplier,
    SupplierConsolidationFlag,
)
from app.matching.scorer import (
    REVIEW_RECOMMENDED_THRESHOLD,
    CandidateItem,
    MatchMethod,
    score_pair,
)
from app.services import audit_service


async def _distinct_sku_descriptions(db: AsyncSession, organisation_id: int, supplier_id: int) -> list[tuple[str | None, str]]:
    """Pulls every distinct (sku, description) pair purchased from this supplier, from whichever
    source has data (invoice lines preferred, matching the ADR-014 precedence reasoning used
    elsewhere - not a rebate calculation here, but the same "don't trust the thinner data source
    when a richer one exists" logic applies)."""
    invoice_result = await db.execute(
        select(PurchaseInvoiceLine.supplier_sku, PurchaseInvoiceLine.description).distinct()
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
        .where(PurchaseInvoice.organisation_id == organisation_id)
        .where(PurchaseInvoice.supplier_id == supplier_id)
        .where(PurchaseInvoiceLine.description.is_not(None))
    )
    rows = [(sku, desc) for sku, desc in invoice_result.all() if desc]
    if rows:
        return rows

    txn_result = await db.execute(
        select(PurchaseTransaction.supplier_sku, PurchaseTransaction.description).distinct()
        .where(PurchaseTransaction.organisation_id == organisation_id)
        .where(PurchaseTransaction.supplier_id == supplier_id)
        .where(PurchaseTransaction.description.is_not(None))
    )
    return [(sku, desc) for sku, desc in txn_result.all() if desc]


async def scan_supplier_for_duplicate_skus(
    db: AsyncSession, *, organisation_id: int, supplier_id: int,
) -> list[DuplicateSkuFlag]:
    """
    Pairwise comparison within one supplier's own SKU list. A match via exact SKU isn't a
    duplicate (same SKU = same item by definition) - only fuzzy/attribute matches above the
    review threshold, between rows with DIFFERENT SKU codes, are flagged. Skips pairs already
    flagged (by sku_a/sku_b/description pair) so re-running the scan doesn't create duplicate
    flags of its own.
    """
    items = await _distinct_sku_descriptions(db, organisation_id, supplier_id)
    if len(items) < 2:
        return []

    existing_result = await db.execute(
        select(DuplicateSkuFlag.description_a, DuplicateSkuFlag.description_b)
        .where(DuplicateSkuFlag.supplier_id == supplier_id)
    )
    already_flagged = {frozenset((a, b)) for a, b in existing_result.all()}

    candidates = [
        CandidateItem(key=str(i), supplier_sku=sku, barcode=None, description=desc)
        for i, (sku, desc) in enumerate(items)
    ]

    new_flags: list[DuplicateSkuFlag] = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            item_a, item_b = candidates[i], candidates[j]
            if item_a.supplier_sku and item_a.supplier_sku == item_b.supplier_sku:
                continue  # same SKU - not a duplicate, it's the same item
            score, method = score_pair(item_a, item_b)
            if score < REVIEW_RECOMMENDED_THRESHOLD or method == MatchMethod.SKU:
                continue
            if frozenset((item_a.description, item_b.description)) in already_flagged:
                continue

            flag = DuplicateSkuFlag(
                organisation_id=organisation_id, supplier_id=supplier_id,
                sku_a=item_a.supplier_sku, description_a=item_a.description,
                sku_b=item_b.supplier_sku, description_b=item_b.description,
                similarity_score=round(score, 4), match_method=method.value, status="flagged",
            )
            db.add(flag)
            new_flags.append(flag)

    if new_flags:
        await audit_service.record(
            db, organisation_id=organisation_id, user_id=None, action="duplicate_sku_scan_flagged",
            entity_type="supplier", entity_id=str(supplier_id), context={"new_flags": len(new_flags)},
        )
        await db.commit()
    return new_flags


async def review_duplicate_sku_flag(
    db: AsyncSession, *, organisation_id: int, user_id: int, flag: DuplicateSkuFlag, confirmed: bool,
) -> DuplicateSkuFlag:
    """Human confirmation - the never-silently-merge gate. Nothing downstream treats sku_a/sku_b
    as the same product because of this flag alone; that decision belongs to whatever workflow
    the human confirmation is meant to inform (out of scope here - this only records the review)."""
    from datetime import datetime

    flag.status = "confirmed_duplicate" if confirmed else "rejected"
    flag.reviewed_by_user_id = user_id
    flag.reviewed_at = datetime.now(UTC)
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="duplicate_sku_flag_reviewed",
        entity_type="duplicate_sku_flag", entity_id=str(flag.id), context={"confirmed": confirmed},
    )
    await db.commit()
    await db.refresh(flag)
    return flag


async def scan_for_supplier_consolidation(
    db: AsyncSession, *, organisation_id: int,
) -> list[SupplierConsolidationFlag]:
    """
    Cross-supplier equivalent of duplicate-SKU detection (spec §22). Deliberately produces only
    flags, never a ranked "consolidate these" recommendation - service risk, geographic coverage,
    and supply resilience (spec's own explicit list) are exactly the things this function has no
    visibility into and must not pretend to weigh.
    """
    suppliers_result = await db.execute(
        select(Supplier.id, Supplier.legal_name).where(Supplier.organisation_id == organisation_id)
    )
    suppliers = suppliers_result.all()
    if len(suppliers) < 2:
        return []

    existing_result = await db.execute(
        select(SupplierConsolidationFlag.description_a, SupplierConsolidationFlag.description_b)
        .where(SupplierConsolidationFlag.organisation_id == organisation_id)
    )
    already_flagged = {frozenset((a, b)) for a, b in existing_result.all()}

    items_by_supplier = {
        sid: await _distinct_sku_descriptions(db, organisation_id, sid) for sid, _ in suppliers
    }

    new_flags: list[SupplierConsolidationFlag] = []
    for i in range(len(suppliers)):
        for j in range(i + 1, len(suppliers)):
            supplier_a_id, _ = suppliers[i]
            supplier_b_id, _ = suppliers[j]
            for sku_a, desc_a in items_by_supplier[supplier_a_id]:
                for sku_b, desc_b in items_by_supplier[supplier_b_id]:
                    item_a = CandidateItem(key="a", supplier_sku=sku_a, barcode=None, description=desc_a)
                    item_b = CandidateItem(key="b", supplier_sku=sku_b, barcode=None, description=desc_b)
                    score, method = score_pair(item_a, item_b)
                    if score < REVIEW_RECOMMENDED_THRESHOLD:
                        continue
                    if frozenset((desc_a, desc_b)) in already_flagged:
                        continue
                    flag = SupplierConsolidationFlag(
                        organisation_id=organisation_id, supplier_a_id=supplier_a_id, supplier_b_id=supplier_b_id,
                        description_a=desc_a, description_b=desc_b, similarity_score=round(score, 4),
                        match_method=method.value, status="flagged",
                    )
                    db.add(flag)
                    new_flags.append(flag)

    if new_flags:
        await audit_service.record(
            db, organisation_id=organisation_id, user_id=None, action="supplier_consolidation_scan_flagged",
            entity_type="organisation", entity_id=str(organisation_id), context={"new_flags": len(new_flags)},
        )
        await db.commit()
    return new_flags


async def build_consolidation_graph_payload(db: AsyncSession, *, organisation_id: int) -> dict:
    """
    DB orchestration only - fetches Supplier/SupplierConsolidationFlag rows for the org and maps
    them into the pure engine's Input dataclasses, then hands off entirely to
    build_supplier_consolidation_graph() (app/analytics/domain_graph.py, §2.1: zero DB/framework
    imports in that module). Suppliers and flags are fetched from the SAME RLS-scoped org, so
    every flag's supplier_a_id/supplier_b_id is guaranteed present in the supplier list by FK
    integrity - UnknownSupplierError should never actually fire here; it exists as a real
    guardrail for a caller bug (§5.2), not dead code for a case that "should never happen" being
    silently trusted.
    """
    suppliers_result = await db.execute(
        select(Supplier).where(Supplier.organisation_id == organisation_id).where(Supplier.deleted_at.is_(None))
    )
    supplier_inputs = [
        SupplierInput(id=s.id, public_id=str(s.public_id), name=s.legal_name)
        for s in suppliers_result.scalars().all()
    ]

    flags_result = await db.execute(
        select(SupplierConsolidationFlag).where(SupplierConsolidationFlag.organisation_id == organisation_id)
    )
    flags = list(flags_result.scalars().all())
    flag_inputs = [
        ConsolidationFlagInput(
            supplier_a_id=f.supplier_a_id, supplier_b_id=f.supplier_b_id,
            description_a=f.description_a, description_b=f.description_b,
            similarity_score=Decimal(str(f.similarity_score)),
            combined_spend=Decimal(str(f.combined_spend)) if f.combined_spend is not None else None,
            status=f.status, match_method=f.match_method,
        )
        for f in flags
    ]

    graph = build_supplier_consolidation_graph(supplier_inputs, flag_inputs)

    return {
        "nodes": [
            {"id": n.id, "label": n.label, "node_type": n.node_type, "source": n.source, "metadata": n.metadata}
            for n in graph.nodes
        ],
        # similarity_score/combined_spend come directly off GraphEdge (domain_graph.py) - pulling
        # them a second time from flag_inputs[i] here would be exactly the duplicate-source risk
        # §2.7 exists to avoid. flag_public_id is deliberately NOT added to the pure GraphEdge/
        # ConsolidationFlagInput dataclasses (unlike similarity_score/combined_spend, which are
        # genuine domain data) - a DB public_id is purely a persistence detail with no reason to
        # exist inside a pure topology engine; sourced here from `flags` (the raw ORM rows,
        # same iteration order as flag_inputs/graph.edges - one flag per edge, no filtering).
        "edges": [
            {
                "source_id": e.source_id, "target_id": e.target_id, "weight": str(e.weight),
                "status": e.status, "source": e.source,
                "similarity_score": str(e.similarity_score),
                "combined_spend": str(e.combined_spend) if e.combined_spend is not None else None,
                "match_method": e.match_method,
                "description_a": flag_inputs[i].description_a, "description_b": flag_inputs[i].description_b,
                "flag_public_id": str(flags[i].public_id),
            }
            for i, e in enumerate(graph.edges)
        ],
    }


async def review_consolidation_flag(
    db: AsyncSession, *, organisation_id: int, user_id: int,
    flag: SupplierConsolidationFlag, action: ConsolidationReviewAction, notes: str | None,
) -> SupplierConsolidationFlag:
    """Validates the transition via the pure state machine (app.analytics.domain_graph -
    determine_consolidation_flag_transition, tests_pure/test_domain_graph.py) before writing
    anything - InvalidConsolidationTransitionError propagates to the route as a 409, same
    pattern as opportunity_service.advance_waterfall_stage."""
    from datetime import datetime

    new_status = determine_consolidation_flag_transition(flag.status, action)
    flag.status = new_status
    flag.review_notes = notes
    flag.reviewed_by_user_id = user_id
    flag.reviewed_at = datetime.now(UTC)

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="consolidation_flag_reviewed",
        entity_type="supplier_consolidation_flag", entity_id=str(flag.id),
        context={"new_status": new_status, "review_action": action.value},
    )
    await db.commit()
    await db.refresh(flag)
    return flag
