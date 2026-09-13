"""
Orchestrates the price-review lifecycle end to end (spec Section 36's wizard flow): create review
-> upload files -> confirm mapping -> validate -> match -> resolve uncertain matches -> calculate
-> buyer decisions -> negotiation -> opportunities -> export. Every mutating action is audited
(spec Section 34) via services/audit_service.py.

Needs SQLAlchemy/asyncpg, neither installable in this sandbox - syntax-checked only, not run. The
functions this module calls into (app.matching.*, app.analytics.price_review_calculations,
app.ingestion.*, app.reporting.price_review_excel_export) ARE genuinely tested - see
tests_pure/ and scripts/demo_price_review.py. This module is the thin, DB-aware layer that wires
those proven building blocks into persistent state; it deliberately contains no calculation or
matching logic of its own.
"""
from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.price_review_calculations import (
    PriceReviewMatchStatus,
    calculate_actual_cost_avoidance,
    calculate_annual_impact,
    calculate_gross_margin,
    calculate_percentage_change,
    calculate_potential_cost_avoidance,
    calculate_price_change,
    classify_movement_type,
    classify_risk,
    determine_comparison_basis,
)
from app.analytics.price_review_summary import PriceReviewLineForSummary, summarize
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.db.models import Opportunity, PriceReview, PriceReviewFile, PriceReviewLine, Supplier
from app.ingestion.staging import compute_checksum
from app.matching.pack_parser import (
    UnrecognizedPackFormatError,
    parse_pack_string,
    price_per_base_unit,
)
from app.matching.review import requires_human_review
from app.matching.scorer import CandidateItem, MatchStatus, find_best_match
from app.schemas.price_review import (
    BuyerDecisionUpdate,
    ManualQuantityUpdate,
    MatchDecision,
    NegotiationOutcomeUpdate,
    NegotiationTargetUpdate,
    PriceReviewCreate,
)
from app.services import audit_service


async def create_review(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: PriceReviewCreate
) -> PriceReview:
    supplier_result = await db.execute(
        select(Supplier).where(Supplier.public_id == payload.supplier_public_id)
    )
    supplier = supplier_result.scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier not found")

    review = PriceReview(
        organisation_id=organisation_id,
        supplier_id=supplier.id,
        status="draft",
        effective_date=payload.effective_date,
        currency=payload.currency,
        price_basis=payload.price_basis,
        created_by_user_id=user_id,
    )
    db.add(review)
    await db.flush()
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="price_review_created",
        entity_type="price_review", entity_id=str(review.id),
    )
    await db.commit()
    await db.refresh(review)
    return review


async def register_uploaded_file(
    db: AsyncSession, *, organisation_id: int, user_id: int, review_id: int,
    file_type: str, original_filename: str, storage_key: str, file_bytes: bytes,
) -> PriceReviewFile:
    checksum = compute_checksum(file_bytes)

    existing = await db.execute(
        select(PriceReviewFile)
        .where(PriceReviewFile.price_review_id == review_id)
        .where(PriceReviewFile.checksum == checksum)
    )
    if existing.scalar_one_or_none() is not None:
        # Belt-and-braces: the DB unique constraint (migration 0002) is the real guarantee: see
        # docs/data-model.md / ADR reasoning. This check gives a clean error message before
        # hitting a raw constraint violation.
        raise ConflictError("This exact file has already been uploaded to this review")

    file_record = PriceReviewFile(
        organisation_id=organisation_id, price_review_id=review_id, file_type=file_type,
        original_filename=original_filename, storage_key=storage_key, checksum=checksum,
        processing_status="uploaded", uploaded_by_user_id=user_id,
    )
    db.add(file_record)
    await db.flush()
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="price_review_file_uploaded",
        entity_type="price_review_file", entity_id=str(file_record.id),
        context={"file_type": file_type, "filename": original_filename},
    )
    await db.commit()
    await db.refresh(file_record)
    return file_record


def _normalize(pack_raw: str | None, price: Decimal | None) -> tuple[Decimal | None, str | None]:
    if not pack_raw or price is None:
        return None, None
    try:
        parsed = parse_pack_string(pack_raw)
        return price_per_base_unit(price, parsed), parsed.base_unit
    except (UnrecognizedPackFormatError, ValueError):
        return None, None  # falls back to raw price comparison - flagged as pack_changed=False,
        # low-confidence movement classification; never silently treated as a like-for-like price


async def run_matching(
    db: AsyncSession, *, organisation_id: int, review_id: int,
    old_rows: list[dict], new_rows: list[dict],
) -> list[PriceReviewLine]:
    """
    Runs the proven matching pipeline (app.matching.scorer) against staged rows and persists one
    PriceReviewLine per old-list item, plus one per new-only ("new_product") item. This is the
    DB-persistence wrapper around exactly the logic exercised in tests_pure/test_matching.py and
    scripts/demo_price_review.py - no matching logic lives here.
    """
    old_candidates = [
        CandidateItem(key=str(r["supplier_sku"]), supplier_sku=r.get("supplier_sku"),
                       barcode=r.get("barcode"), description=r.get("description") or "")
        for r in old_rows
    ]
    new_candidates = [
        CandidateItem(key=str(r["supplier_sku"]), supplier_sku=r.get("supplier_sku"),
                       barcode=r.get("barcode"), description=r.get("description") or "")
        for r in new_rows
    ]
    new_by_sku = {r["supplier_sku"]: r for r in new_rows}
    matched_new_skus: set[str] = set()

    lines: list[PriceReviewLine] = []
    for old_row, old_item in zip(old_rows, old_candidates):
        result = find_best_match(old_item, new_candidates)
        old_price = Decimal(str(old_row["price"])) if old_row.get("price") else None
        old_norm, old_unit = _normalize(old_row.get("pack_size"), old_price)

        if result.status == MatchStatus.NO_CANDIDATE or result.new_key is None:
            lines.append(PriceReviewLine(
                organisation_id=organisation_id, price_review_id=review_id,
                old_supplier_sku=old_row.get("supplier_sku"), old_description=old_row.get("description"),
                old_pack_raw=old_row.get("pack_size"), old_price=old_price,
                old_normalized_price=old_norm, old_normalized_base_unit=old_unit,
                match_status=PriceReviewMatchStatus.DISCONTINUED.value, match_method="unmatched",
                movement_type="discontinued",
            ))
            continue

        matched_new_skus.add(result.new_key)
        new_row = new_by_sku[result.new_key]
        new_price = Decimal(str(new_row["price"])) if new_row.get("price") else None
        new_norm, new_unit = _normalize(new_row.get("pack_size"), new_price)
        pack_changed = (old_row.get("pack_size") or "") != (new_row.get("pack_size") or "")

        match_status = PriceReviewMatchStatus.MATCHED.value if not requires_human_review(result.status) else PriceReviewMatchStatus.REVIEW_REQUIRED.value

        lines.append(PriceReviewLine(
            organisation_id=organisation_id, price_review_id=review_id,
            old_supplier_sku=old_row.get("supplier_sku"), old_description=old_row.get("description"),
            old_pack_raw=old_row.get("pack_size"), old_price=old_price,
            old_normalized_price=old_norm, old_normalized_base_unit=old_unit,
            new_supplier_sku=new_row.get("supplier_sku"), new_description=new_row.get("description"),
            new_pack_raw=new_row.get("pack_size"), new_price=new_price,
            new_normalized_price=new_norm, new_normalized_base_unit=new_unit,
            match_status=match_status, match_method=result.method.value,
            match_confidence=Decimal(str(round(result.confidence, 4))),
            pack_changed=pack_changed,
        ))

    for sku, new_row in new_by_sku.items():
        if sku in matched_new_skus:
            continue
        new_price = Decimal(str(new_row["price"])) if new_row.get("price") else None
        new_norm, new_unit = _normalize(new_row.get("pack_size"), new_price)
        lines.append(PriceReviewLine(
            organisation_id=organisation_id, price_review_id=review_id,
            new_supplier_sku=new_row.get("supplier_sku"), new_description=new_row.get("description"),
            new_pack_raw=new_row.get("pack_size"), new_price=new_price,
            new_normalized_price=new_norm, new_normalized_base_unit=new_unit,
            match_status=PriceReviewMatchStatus.NEW_PRODUCT.value, match_method="unmatched", movement_type="new_product",
        ))

    db.add_all(lines)
    await db.flush()
    return lines


def calculate_line_movement(line: PriceReviewLine) -> None:
    """Applies the proven calculation functions (app.analytics.price_review_calculations) to a
    matched line's already-normalized prices and manually-entered quantity, mutating it in place.
    Called after a match is confirmed and/or a manual quantity is set - never on an
    unmatched/new/discontinued line, which structurally cannot have a movement type here."""
    if line.match_status not in (PriceReviewMatchStatus.MATCHED.value, PriceReviewMatchStatus.REVIEW_REQUIRED.value):
        return

    basis = determine_comparison_basis(
        line.old_normalized_price, line.new_normalized_price,
        line.old_normalized_base_unit, line.new_normalized_base_unit,
    )
    line.comparison_basis = basis

    if basis == "unit_mismatch":
        # Compliance finding 1: refuse rather than silently compare incompatible units - same
        # posture as the zero-old-price case (calculate_percentage_change returns None, never a
        # fabricated number). classify_movement_type is deliberately NOT called here: its
        # existing (tested) branch order checks pack_changed before percentage_change is None,
        # which would misclassify this as "pack_change" rather than flag it for review.
        line.movement_type = "review_required"
        line.absolute_change = None
        line.percentage_change = None
        line.risk_classification = "unclassified"
        return

    cmp_old = line.old_normalized_price if basis == "normalized" else line.old_price
    cmp_new = line.new_normalized_price if basis == "normalized" else line.new_price
    if cmp_old is None or cmp_new is None:
        return

    line.absolute_change = calculate_price_change(Decimal(str(cmp_old)), Decimal(str(cmp_new)))
    line.percentage_change = calculate_percentage_change(Decimal(str(cmp_old)), Decimal(str(cmp_new)))
    line.movement_type = classify_movement_type(
        is_matched=True, is_new=False, is_discontinued=False,
        pack_changed=line.pack_changed, percentage_change=line.percentage_change,
    )
    line.risk_classification = classify_risk(line.percentage_change)

    if line.annual_quantity is not None:
        line.annual_impact = calculate_annual_impact(line.absolute_change, Decimal(str(line.annual_quantity)))

    if line.selling_price is not None:
        _, old_margin_pct = calculate_gross_margin(Decimal(str(line.selling_price)), Decimal(str(cmp_old)))
        _, new_margin_pct = calculate_gross_margin(Decimal(str(line.selling_price)), Decimal(str(cmp_new)))
        line.old_margin_pct = old_margin_pct
        line.new_margin_pct = new_margin_pct
        line.margin_movement_pct = new_margin_pct - old_margin_pct
        if line.annual_quantity is not None:
            line.annual_margin_impact = calculate_annual_impact(
                new_margin_pct - old_margin_pct, Decimal(str(line.annual_quantity))
            )


async def resolve_match(
    db: AsyncSession, *, organisation_id: int, user_id: int, line: PriceReviewLine,
    decision: MatchDecision, candidate_line: PriceReviewLine | None = None,
) -> PriceReviewLine:
    """spec Section 10's match-review actions. candidate_line is required and pre-fetched by the
    caller (routes layer) when decision.action == 'choose_different'."""
    if decision.action == "confirm":
        line.match_status = PriceReviewMatchStatus.MATCHED.value
    elif decision.action == "choose_different":
        if candidate_line is None:
            raise ValidationFailedError("chosen_new_line_public_id did not resolve to a line in this review")
        line.new_supplier_sku = candidate_line.new_supplier_sku
        line.new_description = candidate_line.new_description
        line.new_pack_raw = candidate_line.new_pack_raw
        line.new_price = candidate_line.new_price
        line.new_normalized_price = candidate_line.new_normalized_price
        line.match_status = PriceReviewMatchStatus.MATCHED.value
        line.match_method = "manual_override"
    elif decision.action == "mark_new":
        line.match_status = PriceReviewMatchStatus.NEW_PRODUCT.value
        line.movement_type = "new_product"
    elif decision.action == "mark_discontinued":
        line.match_status = PriceReviewMatchStatus.DISCONTINUED.value
        line.movement_type = "discontinued"
    elif decision.action == "ignore":
        line.match_status = PriceReviewMatchStatus.IGNORED.value

    line.match_confirmed_by_user_id = user_id
    calculate_line_movement(line)

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="price_review_match_resolved",
        entity_type="price_review_line", entity_id=str(line.id), context={"action": decision.action},
    )
    await db.commit()
    await db.refresh(line)
    return line


async def set_manual_quantity(
    db: AsyncSession, *, organisation_id: int, user_id: int, line: PriceReviewLine,
    payload: ManualQuantityUpdate,
) -> PriceReviewLine:
    """spec Section 13/32 + ADR-008."""
    line.annual_quantity = payload.annual_quantity
    line.quantity_source = "manual"
    line.quantity_confidence = "low"  # per ADR-008 - manual entry is always Low confidence
    if payload.selling_price is not None:
        line.selling_price = payload.selling_price
    calculate_line_movement(line)

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="price_review_quantity_set",
        entity_type="price_review_line", entity_id=str(line.id),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def set_buyer_decision(
    db: AsyncSession, *, organisation_id: int, user_id: int, line: PriceReviewLine,
    payload: BuyerDecisionUpdate,
) -> PriceReviewLine:
    from datetime import datetime

    line.buyer_decision = payload.decision
    line.buyer_decision_notes = payload.notes
    line.buyer_decision_by_user_id = user_id
    line.buyer_decision_at = datetime.now(UTC)

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="price_review_buyer_decision",
        entity_type="price_review_line", entity_id=str(line.id), context={"decision": payload.decision},
    )
    await db.commit()
    await db.refresh(line)
    return line


async def set_negotiation_target(
    db: AsyncSession, *, organisation_id: int, user_id: int, line: PriceReviewLine,
    payload: NegotiationTargetUpdate,
) -> PriceReviewLine:
    """spec Section 23 - potential cost avoidance, explicitly not hard savings."""
    line.target_price = payload.target_price
    if line.new_price is not None and line.annual_quantity is not None:
        line.potential_cost_avoidance = calculate_potential_cost_avoidance(
            Decimal(str(line.new_price)), payload.target_price, Decimal(str(line.annual_quantity))
        )
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id,
        action="price_review_negotiation_target_set", entity_type="price_review_line",
        entity_id=str(line.id),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def record_negotiation_outcome(
    db: AsyncSession, *, organisation_id: int, user_id: int, line: PriceReviewLine,
    payload: NegotiationOutcomeUpdate,
) -> PriceReviewLine:
    """spec Section 24 - actual cost avoidance, kept separate from potential (Section 23) and
    from hard savings/working capital/margin protection (analytics-methodology.md Section 7)."""
    line.final_negotiated_price = payload.final_negotiated_price
    if line.new_price is not None and line.annual_quantity is not None:
        line.actual_cost_avoidance = calculate_actual_cost_avoidance(
            Decimal(str(line.new_price)), payload.final_negotiated_price, Decimal(str(line.annual_quantity))
        )
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id,
        action="price_review_negotiation_outcome_recorded", entity_type="price_review_line",
        entity_id=str(line.id),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def create_opportunity_from_line(
    db: AsyncSession, *, organisation_id: int, user_id: int, review: PriceReview, line: PriceReviewLine,
) -> Opportunity:
    """spec Section 25 - links back to price_review_id / price_review_line_id per the spec's
    explicit requirement, so an opportunity is always traceable to the analysis that produced it."""
    opportunity = Opportunity(
        organisation_id=organisation_id,
        title=f"Review price increase: {line.new_description or line.old_description}",
        opportunity_type="price_increase_challenge",
        supplier_id=review.supplier_id,
        price_review_id=review.id,
        price_review_line_id=line.id,
        requested_increase_pct=line.percentage_change,
        annual_financial_impact=line.annual_impact,
        negotiation_target_price=line.target_price,
        potential_cost_avoidance=line.potential_cost_avoidance,
        owner_user_id=user_id,
        status="identified",
        created_by_user_id=user_id,
    )
    db.add(opportunity)
    await db.flush()
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="opportunity_created",
        entity_type="opportunity", entity_id=str(opportunity.id),
        context={"price_review_line_id": line.id},
    )
    await db.commit()
    await db.refresh(opportunity)
    return opportunity


async def get_summary(db: AsyncSession, *, review_id: int):
    """Wraps app.analytics.price_review_summary.summarize (proven in tests_pure/test_calculations.py)
    around the review's persisted lines."""
    result = await db.execute(select(PriceReviewLine).where(PriceReviewLine.price_review_id == review_id))
    lines = list(result.scalars().all())

    summary_lines = [
        PriceReviewLineForSummary(
            movement_type=line.movement_type or "review_required",
            percentage_change=line.percentage_change,
            annual_impact=line.annual_impact,
            annual_quantity=line.annual_quantity,
            pack_changed=line.pack_changed,
            requires_review=(line.match_status == PriceReviewMatchStatus.REVIEW_REQUIRED.value),
        )
        for line in lines
    ]
    total_previous = sum(1 for l in lines if l.old_supplier_sku is not None)
    total_new = sum(1 for l in lines if l.new_supplier_sku is not None)
    return summarize(summary_lines, total_previous_skus=total_previous, total_new_skus=total_new)
