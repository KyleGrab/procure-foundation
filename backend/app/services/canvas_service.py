"""
DB orchestration for the three canvas lenses (Procurement, Warehouse & Inventory, Management
Accounting). Fetches real data, maps to app.analytics.canvas_lens's Input dataclasses, hands off
entirely to the pure builders (§2.1). No relationship/status logic here - only queries and mapping.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.canvas_lens import (
    CanvasGraph,
    ContractRenewalInput,
    InventorySummaryInput,
    LocationInput,
    ManagementSummaryInput,
    SupplierSpendInput,
    build_inventory_lens_graph,
    build_management_lens_graph,
    build_procurement_lens_graph,
)
from app.analytics.inventory_calculations import calculate_days_since_last_movement, classify_expiry_risk
from app.analytics.management_accounting import calculate_variance_vs_prior
from app.analytics.rebate_calculations import calculate_aggregate_rebate_leakage
from app.db.models import (
    Contract,
    CostToServeLedger,
    InventorySnapshot,
    Location,
    RebateAgreement,
    RebatePeriodActual,
    Supplier,
    WorkingCapitalSnapshot,
)
from app.services import spend_analytics_service


async def build_procurement_lens(db: AsyncSession, *, organisation_id: int) -> CanvasGraph:
    suppliers_result = await db.execute(
        select(Supplier).where(Supplier.organisation_id == organisation_id).where(Supplier.deleted_at.is_(None))
    )
    suppliers = list(suppliers_result.scalars().all())
    if not suppliers:
        return CanvasGraph(nodes=[], edges=[])

    spend_items = await spend_analytics_service.get_spend_by_supplier(db, organisation_id=organisation_id)
    spend_by_supplier_id = {item.key: item.amount for item in spend_items}

    supplier_inputs = [
        SupplierSpendInput(
            id=s.id, public_id=str(s.public_id), name=s.legal_name, category=s.category,
            total_spend=spend_by_supplier_id.get(str(s.id), Decimal("0")),
        )
        for s in suppliers
    ]

    periods_result = await db.execute(
        select(RebatePeriodActual.expected_amount, RebatePeriodActual.received_amount)
        .join(RebateAgreement, RebateAgreement.id == RebatePeriodActual.rebate_agreement_id)
        .where(RebateAgreement.organisation_id == organisation_id)
        # P-03: was `expected_amount.is_not(None)` - correct in spirit (excluding unknown rows)
        # but the real signal is now the evidence status, not raw nullability. legacy_unverified
        # rows also have a non-null amount but must still be excluded from this authoritative
        # aggregate - only estimated/calculated/confirmed represent real evidence.
        .where(RebatePeriodActual.expected_amount_status.in_(("estimated", "calculated", "confirmed")))
    )
    period_pairs = [
        (Decimal(str(expected)), Decimal(str(received)) if received is not None else None)
        for expected, received in periods_result.all()
    ]
    aggregate_leakage = calculate_aggregate_rebate_leakage(period_pairs)

    contracts_result = await db.execute(
        select(Contract)
        .where(Contract.organisation_id == organisation_id)
        .where(Contract.status.in_(("expiring_soon", "notice_period_open")))
    )
    contract_renewals = [
        ContractRenewalInput(
            contract_public_id=str(c.public_id), supplier_id=c.supplier_id, title=c.title,
            expiry_date=c.expiry_date, status=c.status,
        )
        for c in contracts_result.scalars().all()
    ]

    return build_procurement_lens_graph(
        supplier_inputs, aggregate_leakage=aggregate_leakage, contract_renewals=contract_renewals,
    )


async def build_inventory_lens(
    db: AsyncSession, *, organisation_id: int, as_of: date | None = None, stale_threshold_days: int = 60,
) -> CanvasGraph:
    """
    as_of defaults to today, resolved here in the service layer (not inside the pure engine -
    same §7.3 determinism boundary as every other pure function this session). Fetches full
    snapshot history per grain key rather than a windowed "latest per group" SQL query - simpler
    for this v1, acceptable at realistic data volumes; a real performance concern later is a
    query optimization, not a logic rewrite (same documented tradeoff as
    duplicate_detection_service's O(n^2) scan).
    """
    resolved_as_of = as_of or date.today()

    locations_result = await db.execute(
        select(Location).where(Location.organisation_id == organisation_id)
    )
    locations = list(locations_result.scalars().all())
    if not locations:
        return CanvasGraph(nodes=[], edges=[])

    snapshots_result = await db.execute(
        select(
            InventorySnapshot.location_id, InventorySnapshot.description, InventorySnapshot.supplier_sku,
            InventorySnapshot.snapshot_date, InventorySnapshot.quantity_on_hand, InventorySnapshot.expiry_date,
        )
        .where(InventorySnapshot.organisation_id == organisation_id)
        .where(InventorySnapshot.corrects_id.is_(None))
    )
    rows = snapshots_result.all()

    grouped: dict[tuple[int, str, str | None], list[tuple[date, Decimal, date | None]]] = {}
    for location_id, description, supplier_sku, snapshot_date, quantity, expiry_date in rows:
        key = (location_id, description, supplier_sku)
        grouped.setdefault(key, []).append((snapshot_date, Decimal(str(quantity)), expiry_date))

    summaries: list[InventorySummaryInput] = []
    for (location_id, description, _supplier_sku), history in grouped.items():
        history.sort(key=lambda t: t[0])
        last_movement_days = calculate_days_since_last_movement(
            [(d, q) for d, q, _e in history], as_of=resolved_as_of
        )
        latest_expiry_date = history[-1][2]
        expiry_status = classify_expiry_risk(latest_expiry_date, as_of=resolved_as_of).value
        summaries.append(InventorySummaryInput(
            location_id=location_id, description=description,
            expiry_status=expiry_status, last_movement_days=last_movement_days,
        ))

    location_inputs = [LocationInput(id=loc.id, public_id=str(loc.public_id), name=loc.name) for loc in locations]

    return build_inventory_lens_graph(location_inputs, summaries, stale_threshold_days=stale_threshold_days)


async def build_management_lens(db: AsyncSession, *, organisation_id: int) -> CanvasGraph:
    """
    Latest WorkingCapitalSnapshot (+ the one before it, for variance_vs_prior) and an aggregate
    over CostToServeLedger. If no WorkingCapitalSnapshot exists yet for this org, returns an
    empty graph - the org simply hasn't ingested any working-capital data, not an error.
    """
    snapshots_result = await db.execute(
        select(WorkingCapitalSnapshot)
        .where(WorkingCapitalSnapshot.organisation_id == organisation_id)
        .where(WorkingCapitalSnapshot.corrects_id.is_(None))
        .order_by(WorkingCapitalSnapshot.as_of_date.desc())
        .limit(2)
    )
    snapshots = list(snapshots_result.scalars().all())
    if not snapshots:
        return CanvasGraph(nodes=[], edges=[])

    current = snapshots[0]
    prior = snapshots[1] if len(snapshots) > 1 else None

    def _decimal_or_none(value) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    dso, dio, dpo, ccc = (
        _decimal_or_none(current.dso), _decimal_or_none(current.dio),
        _decimal_or_none(current.dpo), _decimal_or_none(current.ccc),
    )
    prior_dso = _decimal_or_none(prior.dso) if prior else None
    prior_dio = _decimal_or_none(prior.dio) if prior else None
    prior_dpo = _decimal_or_none(prior.dpo) if prior else None

    ledger_result = await db.execute(
        select(
            func.coalesce(func.sum(CostToServeLedger.net_revenue), 0),
            func.coalesce(func.sum(CostToServeLedger.cogs), 0),
            func.coalesce(func.sum(CostToServeLedger.allocated_warehouse_cost), 0),
            func.coalesce(func.sum(CostToServeLedger.direct_logistics_cost), 0),
            func.coalesce(func.sum(CostToServeLedger.net_margin), 0),
        )
        .where(CostToServeLedger.organisation_id == organisation_id)
        .where(CostToServeLedger.corrects_id.is_(None))
    )
    gross_revenue, cogs, warehouse_abc_cost, logistics_cost, net_margin = (
        Decimal(str(v)) for v in ledger_result.one()
    )

    summary = ManagementSummaryInput(
        gross_revenue=gross_revenue, cogs=cogs, warehouse_abc_cost=warehouse_abc_cost,
        logistics_cost=logistics_cost, net_margin=net_margin,
        dso=dso, dio=dio, dpo=dpo, ccc=ccc,
        dso_variance=calculate_variance_vs_prior(dso, prior_dso),
        dio_variance=calculate_variance_vs_prior(dio, prior_dio),
        dpo_variance=calculate_variance_vs_prior(dpo, prior_dpo),
    )
    return build_management_lens_graph(summary)
