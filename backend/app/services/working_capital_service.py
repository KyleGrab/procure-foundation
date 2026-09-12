"""
DB orchestration for working_capital_snapshots/aging_ledger_snapshots ingestion. No financial
formula of its own - app.analytics.management_accounting's calculate_working_capital_metrics and
classify_aging_buckets (both real, tested, tests_pure/test_management_accounting.py) do every
number. This module's own logic is period-locking, plus (WC-DERIVED-METRIC-DIAGNOSTICS-R1)
deciding what a genuinely calculated days-metric result is safe to persist given
WorkingCapitalSnapshot.dso/dio/dpo/ccc's real Numeric(9, 1) storage boundary - a persistence
concern, not a financial one, which is why it lives here rather than in the pure §2.1 engine.

Period-locking, not a DB constraint (same reasoning as InventorySnapshot's grain check, Phase
5b): an app-level check that raises a specific, catchable ConflictError rather than either a
silently-overwritten prior snapshot or a silently-created ambiguous second snapshot for the same
date. A caller that actually means to correct a bad prior submission passes is_correction=True,
which sets corrects_id on the new row - same append-only correction pattern as
PurchaseInvoice/InventorySnapshot.

variance_vs_prior is deliberately NOT computed here - app.services.canvas_service.build_management_lens
already fetches the two most recent active snapshots and calls calculate_variance_vs_prior at read
time. Duplicating that here would reintroduce exactly the two-sources-of-truth risk ADR-014's
rebate_aggregation_service.py refactor was written to eliminate.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.management_accounting import calculate_working_capital_metrics, classify_aging_buckets
from app.core.exceptions import ConflictError, ValidationFailedError
from app.db.models import AgingLedgerSnapshot, WorkingCapitalSnapshot
from app.services import audit_service

_VALID_LEDGER_TYPES = ("debtors", "creditors")

# WC-DERIVED-METRIC-DIAGNOSTICS-R1: WorkingCapitalSnapshot.dso/dio/dpo/ccc are Numeric(9, 1) -
# precision 9, scale 1, so at most 9-1=8 integer digits fit, and the largest magnitude that
# column can actually hold is 99999999.9. This is the schema's own storage boundary, not an
# invented "no DSO over N days" business threshold (see WORKING-CAPITAL-PRECISION-R1's
# investigation for the real case this closes: a genuinely non-zero but near-zero annualized
# revenue/COGS denominator against a normal six-figure balance produces an arithmetically exact
# but unstorable ~365,000,000-day result).
_DAYS_METRIC_STORAGE_MAX_ABS = Decimal("99999999.9")


def _apply_days_metric_storage_boundary(metrics: dict) -> tuple[dict, list[str]]:
    """metrics is calculate_working_capital_metrics' own, unmodified return dict - this function
    only decides what is safe to persist; it never changes the arithmetic itself, never caps or
    rounds a value into range, and never converts an unknown/unrepresentable result to zero.

    Returns (safe_metrics, diagnostics): safe_metrics has the same keys as metrics with any
    out-of-range dso/dio/dpo/ccc replaced by None, and diagnostics is the list of stable,
    lower_snake_case codes to persist in WorkingCapitalSnapshot.derived_metric_diagnostics.

    An ordinary zero/missing-denominator None (calculate_working_capital_metrics' own existing,
    unchanged §3.2 behavior) is not itself a new diagnostic condition this function introduces -
    diagnostics only records the specific out-of-range cases this phase adds handling for.
    """
    diagnostics: list[str] = []

    def _out_of_range(value: Decimal | None) -> bool:
        return value is not None and abs(value) > _DAYS_METRIC_STORAGE_MAX_ABS

    dso_oor = _out_of_range(metrics["dso"])
    dio_oor = _out_of_range(metrics["dio"])
    dpo_oor = _out_of_range(metrics["dpo"])

    if dso_oor:
        diagnostics.append("dso_out_of_range")
    if dio_oor:
        diagnostics.append("dio_out_of_range")
    if dpo_oor:
        diagnostics.append("dpo_out_of_range")

    safe_dso = None if dso_oor else metrics["dso"]
    safe_dio = None if dio_oor else metrics["dio"]
    safe_dpo = None if dpo_oor else metrics["dpo"]

    if safe_dso is not None and safe_dio is not None and safe_dpo is not None:
        # All three components calculate_working_capital_metrics needs were present and
        # representable, so it already computed a real ccc from them (metrics["ccc"] cannot be
        # None here). That combination can, in principle, itself exceed the storage boundary even
        # though each component individually fits - guard it the same way, so no metric ever
        # surfaces a raw database overflow.
        safe_ccc = metrics["ccc"]
        if _out_of_range(safe_ccc):
            diagnostics.append("ccc_out_of_range")
            safe_ccc = None
    else:
        safe_ccc = None
        if dso_oor:
            diagnostics.append("ccc_unavailable_dso_out_of_range")
        if dio_oor:
            diagnostics.append("ccc_unavailable_dio_out_of_range")
        if dpo_oor:
            diagnostics.append("ccc_unavailable_dpo_out_of_range")
        # else: metrics["ccc"] was already None because one of dio/dso/dpo was None from a
        # zero/missing denominator - existing, unchanged behavior, not a new diagnostic condition.

    return {**metrics, "dso": safe_dso, "dio": safe_dio, "dpo": safe_dpo, "ccc": safe_ccc}, diagnostics


async def ingest_working_capital_snapshot(
    db: AsyncSession, *, organisation_id: int, user_id: int, as_of_date: date,
    accounts_receivable: Decimal, accounts_payable: Decimal, inventory_value: Decimal,
    cash_balance: Decimal | None, annualized_revenue: Decimal, annualized_cogs: Decimal,
    is_correction: bool = False,
) -> WorkingCapitalSnapshot:
    existing_result = await db.execute(
        select(WorkingCapitalSnapshot)
        .where(WorkingCapitalSnapshot.organisation_id == organisation_id)
        .where(WorkingCapitalSnapshot.as_of_date == as_of_date)
        .where(WorkingCapitalSnapshot.corrects_id.is_(None))
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None and not is_correction:
        raise ConflictError(
            f"An active working capital snapshot already exists for {as_of_date} - "
            f"pass is_correction=True to supersede it, not silently duplicate or overwrite it"
        )

    metrics = calculate_working_capital_metrics(
        ar=accounts_receivable, ap=accounts_payable, inventory=inventory_value,
        annual_revenue=annualized_revenue, annual_cogs=annualized_cogs, cash=cash_balance,
    )
    safe_metrics, diagnostics = _apply_days_metric_storage_boundary(metrics)

    snapshot = WorkingCapitalSnapshot(
        organisation_id=organisation_id, as_of_date=as_of_date,
        accounts_receivable=accounts_receivable, accounts_payable=accounts_payable,
        inventory_value=inventory_value, cash_balance=cash_balance,
        annualized_revenue=annualized_revenue, annualized_cogs=annualized_cogs,
        dso=safe_metrics["dso"], dio=safe_metrics["dio"], dpo=safe_metrics["dpo"], ccc=safe_metrics["ccc"],
        working_capital_ratio=metrics["working_capital_ratio"],
        derived_metric_diagnostics=diagnostics,
        corrects_id=existing.id if (existing is not None and is_correction) else None,
        uploaded_by_user_id=user_id,
    )
    db.add(snapshot)
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id,
        action="working_capital_snapshot_corrected" if is_correction else "working_capital_snapshot_ingested",
        entity_type="working_capital_snapshot", entity_id=None,
        context={"as_of_date": as_of_date.isoformat(), "is_correction": is_correction},
    )
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def ingest_aging_snapshot(
    db: AsyncSession, *, organisation_id: int, user_id: int, as_of_date: date, ledger_type: str,
    invoices: list[dict], is_correction: bool = False,
) -> AgingLedgerSnapshot:
    if ledger_type not in _VALID_LEDGER_TYPES:
        raise ValidationFailedError(f"Unrecognized ledger_type: {ledger_type!r} - expected 'debtors' or 'creditors'")

    existing_result = await db.execute(
        select(AgingLedgerSnapshot)
        .where(AgingLedgerSnapshot.organisation_id == organisation_id)
        .where(AgingLedgerSnapshot.as_of_date == as_of_date)
        .where(AgingLedgerSnapshot.ledger_type == ledger_type)
        .where(AgingLedgerSnapshot.corrects_id.is_(None))
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None and not is_correction:
        raise ConflictError(
            f"An active {ledger_type} aging snapshot already exists for {as_of_date} - "
            f"pass is_correction=True to supersede it"
        )

    buckets = classify_aging_buckets(invoices)

    snapshot = AgingLedgerSnapshot(
        organisation_id=organisation_id, as_of_date=as_of_date, ledger_type=ledger_type,
        current_balance=buckets["current"], days_30=buckets["days_30"], days_60=buckets["days_60"],
        days_90=buckets["days_90"], days_120_plus=buckets["days_120_plus"],
        corrects_id=existing.id if (existing is not None and is_correction) else None,
        uploaded_by_user_id=user_id,
    )
    db.add(snapshot)
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id,
        action="aging_snapshot_corrected" if is_correction else "aging_snapshot_ingested",
        entity_type="aging_ledger_snapshot", entity_id=None,
        context={"as_of_date": as_of_date.isoformat(), "ledger_type": ledger_type, "is_correction": is_correction},
    )
    await db.commit()
    await db.refresh(snapshot)
    return snapshot
