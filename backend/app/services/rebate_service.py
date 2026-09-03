"""
Orchestrates rebate agreement/period lifecycle: record actual spend -> recalculate expected
(dynamic, on every ingestion - confirmed product decision) -> check threshold alerts -> close
period (monthly snapshot trigger - confirmed product decision) -> record receipt -> classify
status. No calculation logic of its own - every number is a call into
app.analytics.rebate_calculations (genuinely tested - tests_pure/test_rebate_calculations.py).
DB-dependent, syntax-checked only in this sandbox, same pattern as every service this session.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.rebate_calculations import (
    EntrySource,
    RebateBand,
    RebateType,
    calculate_expected_rebate,
    calculate_progress_to_next_tier,
    calculate_rebate_leakage,
    classify_rebate_status,
    is_period_due_for_close,
    is_threshold_alert_due,
)
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import FinancialAmountStatusEvent, RebateAgreement, RebateAlert, RebatePeriodActual, Supplier
from app.schemas.rebate import RebateAgreementCreate, RebatePeriodActualCreate, RebateReceiptRecord
from app.services import audit_service


async def _write_expected_amount_event(
    db: AsyncSession, *, period_actual: RebatePeriodActual, new_amount, new_status: str,
    new_source_basis: str | None, new_calculated_at, new_approved_at=None, new_approved_by_user_id=None,
    actor_user_id: int | None, change_reference: str, change_reason_code: str,
) -> None:
    """
    P-03: writes one financial_amount_status_events row for expected_amount and updates
    period_actual's snapshot columns to match, in the same transaction as the caller - the
    deferred parent-row trigger proves this at COMMIT, so a snapshot-only change (this function
    not being called at all) fails closed rather than silently succeeding.

    Locks the parent row FOR UPDATE first - P-03's required concurrency control - so two
    concurrent writers for the SAME period_actual can never compute the same event_version.
    period_actual must already be flushed (have a real id) before this is called.
    """
    locked = (await db.execute(
        select(RebatePeriodActual).where(RebatePeriodActual.id == period_actual.id).with_for_update()
    )).scalar_one()

    current_max = (await db.execute(
        select(func.max(FinancialAmountStatusEvent.event_version))
        .where(FinancialAmountStatusEvent.rebate_period_actual_id == locked.id)
        .where(FinancialAmountStatusEvent.measure_code == "expected_amount")
    )).scalar_one_or_none()
    next_version = (current_max or 0) + 1

    event = FinancialAmountStatusEvent(
        organisation_id=locked.organisation_id, rebate_period_actual_id=locked.id,
        measure_code="expected_amount", event_version=next_version,
        old_amount=locked.expected_amount, new_amount=new_amount,
        old_status=locked.expected_amount_status, new_status=new_status,
        old_source_basis=locked.expected_amount_source_basis, new_source_basis=new_source_basis,
        old_calculated_at=locked.expected_amount_calculated_at, new_calculated_at=new_calculated_at,
        old_approved_at=locked.expected_amount_approved_at, new_approved_at=new_approved_at,
        old_approved_by_user_id=locked.expected_amount_approved_by_user_id,
        new_approved_by_user_id=new_approved_by_user_id,
        actor_user_id=actor_user_id, occurred_at=datetime.now(timezone.utc),
        change_reference=change_reference, change_reason_code=change_reason_code,
    )
    db.add(event)
    await db.flush()

    locked.expected_amount = new_amount
    locked.expected_amount_status = new_status
    locked.expected_amount_source_basis = new_source_basis
    locked.expected_amount_calculated_at = new_calculated_at
    locked.expected_amount_approved_at = new_approved_at
    locked.expected_amount_approved_by_user_id = new_approved_by_user_id
    locked.expected_amount_current_event_id = event.id


def _bands_from_agreement(agreement: RebateAgreement) -> list[RebateBand] | None:
    if not agreement.bands:
        return None
    return [RebateBand(Decimal(str(b["threshold_spend"])), Decimal(str(b["rate_pct"]))) for b in agreement.bands]


async def create_rebate_agreement(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: RebateAgreementCreate
) -> RebateAgreement:
    supplier_result = await db.execute(
        select(Supplier).where(Supplier.public_id == payload.supplier_public_id)
    )
    supplier = supplier_result.scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier not found")

    agreement = RebateAgreement(
        organisation_id=organisation_id, supplier_id=supplier.id,
        title=payload.title, rebate_type=payload.rebate_type, period_type=payload.period_type,
        flat_rate_pct=payload.flat_rate_pct,
        bands=[b.model_dump(mode="json") for b in payload.bands] if payload.bands else None,
        fixed_amount=payload.fixed_amount, currency=payload.currency,
        created_by_user_id=user_id,
    )
    db.add(agreement)
    await db.flush()
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="rebate_agreement_created",
        entity_type="rebate_agreement", entity_id=str(agreement.id),
    )
    await db.commit()
    await db.refresh(agreement)
    return agreement


def _compute_expected_amount(agreement: RebateAgreement, period_actual: RebatePeriodActual) -> Decimal | None:
    """Pure calculation only - returns None if there's nothing to calculate yet (no actual_spend
    recorded). Does not touch the database or write any event - the caller decides what status
    that maps to (typically 'unknown' for None, 'calculated' for a real result)."""
    if period_actual.actual_spend is None:
        return None
    actual_spend = Decimal(str(period_actual.actual_spend))
    rebate_type = RebateType(agreement.rebate_type)
    flat_rate = Decimal(str(agreement.flat_rate_pct)) if agreement.flat_rate_pct is not None else None
    fixed_amount = Decimal(str(agreement.fixed_amount)) if agreement.fixed_amount is not None else None
    bands = _bands_from_agreement(agreement)
    return calculate_expected_rebate(
        actual_spend, rebate_type, flat_rate_pct=flat_rate, bands=bands, fixed_amount=fixed_amount,
    )


async def recalculate_expected(
    db: AsyncSession, *, agreement: RebateAgreement, period_actual: RebatePeriodActual,
    actor_user_id: int | None, change_reference: str, change_reason_code: str = "recalculation",
) -> None:
    """
    The 'dynamic recalculation on ingestion' product decision - called every time actual_spend
    changes (manual re-entry in 4a; every new purchase_transactions row in 4b), never only once
    at period creation. P-03: writes an event unconditionally, every call - 'unknown' (no amount
    yet) if actual_spend isn't set, 'calculated' with a real amount if it is. Every row needs a
    genesis event before COMMIT regardless of whether a real amount exists yet - the deferred
    parent-row trigger requires current_event_id to be non-null unconditionally, not only when
    there's a number to show. period_actual must already be flushed (have a real id).
    """
    new_amount = _compute_expected_amount(agreement, period_actual)

    if new_amount is None:
        await _write_expected_amount_event(
            db, period_actual=period_actual, new_amount=None, new_status="unknown",
            new_source_basis=None, new_calculated_at=None,
            actor_user_id=actor_user_id, change_reference=change_reference, change_reason_code=change_reason_code,
        )
    else:
        await _write_expected_amount_event(
            db, period_actual=period_actual, new_amount=new_amount, new_status="calculated",
            new_source_basis="contract_terms_calculation", new_calculated_at=datetime.now(timezone.utc),
            actor_user_id=actor_user_id, change_reference=change_reference, change_reason_code=change_reason_code,
        )
    period_actual.status_calculated_at = datetime.now(timezone.utc)


async def record_period_actual(
    db: AsyncSession, *, organisation_id: int, user_id: int,
    agreement: RebateAgreement, payload: RebatePeriodActualCreate,
) -> RebatePeriodActual:
    """Phase 4a entry path - entry_source='manual' (ADR-012). Phase 4b's transaction-aggregation
    path calls recalculate_expected() the same way after populating actual_spend/volume from
    app.analytics.rebate_calculations.aggregate_transactions_for_period instead of a form."""
    period_actual = RebatePeriodActual(
        organisation_id=organisation_id, rebate_agreement_id=agreement.id,
        period_start=payload.period_start, period_end=payload.period_end,
        actual_spend=payload.actual_spend, actual_volume=payload.actual_volume,
        entry_source=EntrySource.MANUAL.value, entered_by_user_id=user_id,
        expected_amount_status="unknown",  # placeholder until the genesis event below sets it for real
    )
    db.add(period_actual)
    await db.flush()  # period_actual.id must be real before recalculate_expected can write its event

    await recalculate_expected(
        db, agreement=agreement, period_actual=period_actual, actor_user_id=user_id,
        change_reference=f"rebate_period_actual_created:{period_actual.id}", change_reason_code="manual_estimate",
    )

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="rebate_period_actual_recorded",
        entity_type="rebate_period_actual", entity_id=str(period_actual.id),
        context={"entry_source": EntrySource.MANUAL.value},
    )
    await db.commit()
    await db.refresh(period_actual)
    return period_actual


async def check_threshold_alert(
    db: AsyncSession, *, organisation_id: int,
    agreement: RebateAgreement, period_actual: RebatePeriodActual, today: date | None = None,
) -> RebateAlert | None:
    """Idempotent, same pattern as contract_service.run_alert_check - the unique constraint on
    (rebate_period_actual_id, alert_type) is what actually enforces one-time firing; this
    function just avoids inserting a row it already knows would violate it."""
    bands = _bands_from_agreement(agreement)
    if bands is None or period_actual.actual_spend is None:
        return None
    today = today or date.today()

    due = is_threshold_alert_due(
        Decimal(str(period_actual.actual_spend)), bands, today, period_actual.period_end
    )
    if not due:
        return None

    existing = await db.execute(
        select(RebateAlert)
        .where(RebateAlert.rebate_period_actual_id == period_actual.id)
        .where(RebateAlert.alert_type == "threshold_approaching")
    )
    if existing.scalar_one_or_none() is not None:
        return None

    alert = RebateAlert(
        organisation_id=organisation_id, rebate_period_actual_id=period_actual.id,
        alert_type="threshold_approaching", trigger_date=today,
    )
    db.add(alert)
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=None, action="rebate_threshold_alert_fired",
        entity_type="rebate_period_actual", entity_id=str(period_actual.id),
    )
    await db.commit()
    return alert


async def close_period(
    db: AsyncSession, *, organisation_id: int, user_id: int | None,
    period_actual: RebatePeriodActual, today: date | None = None,
) -> RebatePeriodActual:
    """
    The 'formal monthly period-close snapshot' product decision. Locks earned_amount at whatever
    expected_amount currently is - a scheduled monthly job (Phase 9, not built here) calls this
    for every period_actual where is_period_due_for_close() is true; user_id is None for that
    automated path, set for a manual early-close if the service layer ever exposes one (not
    built in this delivery - spec doesn't call for early close, only natural period-end close).
    """
    today = today or date.today()
    if not is_period_due_for_close(period_actual.period_end, today):
        raise ConflictError(
            f"Period ends {period_actual.period_end}, not yet due for close as of {today}"
        )
    if period_actual.earned_amount is not None:
        raise ConflictError("Period has already been closed")

    period_actual.earned_amount = period_actual.expected_amount
    period_actual.earned_at = datetime.now(timezone.utc)
    _refresh_status(period_actual, today=today, period_closed=True)

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="rebate_period_closed",
        entity_type="rebate_period_actual", entity_id=str(period_actual.id),
        context={"earned_amount": str(period_actual.earned_amount)},
    )
    await db.commit()
    await db.refresh(period_actual)
    return period_actual


async def record_receipt(
    db: AsyncSession, *, organisation_id: int, user_id: int,
    period_actual: RebatePeriodActual, payload: RebateReceiptRecord,
) -> dict:
    """spec Section 29 + analytics-methodology.md §8: received_amount is only ever set from an
    actual reference, and setting it is what makes leakage detection (or reconciliation)
    possible - see classify_rebate_status.

    P-03: the receipt itself is ALWAYS stored - a real payment was received; that's a fact
    independent of what's known about expectation. Only the leakage CALCULATION becomes
    diagnostic (null, with a reason code) when expected_amount_status is 'unknown' or
    'legacy_unverified' - never a fabricated leakage figure computed against an assumed-zero
    expectation. Return type changed from RebatePeriodActual to dict - the diagnostic leakage
    shape needs to be communicated to the caller, not silently absent from the response.
    """
    period_actual.received_amount = payload.received_amount
    period_actual.received_reference = payload.received_reference
    _refresh_status(period_actual, today=date.today(), period_closed=period_actual.earned_amount is not None)

    if period_actual.expected_amount_status in ("unknown", "legacy_unverified"):
        leakage_result = {"leakage": None, "status": "diagnostic", "reason_code": "expected_amount_status_insufficient"}
    else:
        leakage = calculate_rebate_leakage(Decimal(str(period_actual.expected_amount)), payload.received_amount)
        leakage_result = {"leakage": str(leakage), "status": "ok", "reason_code": None}

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="rebate_receipt_recorded",
        entity_type="rebate_period_actual", entity_id=str(period_actual.id),
        context={"received_amount": str(payload.received_amount), "leakage_result": leakage_result},
    )
    await db.commit()
    await db.refresh(period_actual)
    return {"period_actual": period_actual, "leakage_result": leakage_result}


def _refresh_status(period_actual: RebatePeriodActual, *, today: date, period_closed: bool) -> None:
    # P-03: classifying a workflow status against a fabricated zero expectation is the exact
    # same false-precision problem this whole design exists to prevent - skip classification
    # entirely (leave status unchanged) when the evidence status can't support it, rather than
    # silently treating "unknown" as "expected nothing."
    if period_actual.expected_amount_status in ("unknown", "legacy_unverified"):
        period_actual.status_calculated_at = datetime.now(timezone.utc)
        return
    threshold_alert_due = False  # recomputed by check_threshold_alert, not duplicated here
    period_actual.status = classify_rebate_status(
        Decimal(str(period_actual.expected_amount)),
        Decimal(str(period_actual.received_amount)) if period_actual.received_amount is not None else None,
        period_closed=period_closed, threshold_alert_due=threshold_alert_due,
    ).value
    period_actual.status_calculated_at = datetime.now(timezone.utc)


def get_derived_progress(agreement: RebateAgreement, period_actual: RebatePeriodActual) -> dict:
    bands = _bands_from_agreement(agreement)
    if bands is None or period_actual.actual_spend is None:
        return {"next_tier_threshold": None, "amount_to_next_tier": None}
    next_threshold, remaining = calculate_progress_to_next_tier(
        Decimal(str(period_actual.actual_spend)), bands
    )
    return {"next_tier_threshold": next_threshold, "amount_to_next_tier": remaining}
