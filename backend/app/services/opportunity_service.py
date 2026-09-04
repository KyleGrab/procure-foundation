"""
Opportunity register lifecycle (spec Section 35's waterfall). No calculation logic beyond
timestamping - the actual savings-type-specific math lives in app.analytics.savings_register and
is computed before an Opportunity is created (by whichever caller has the right inputs for that
type - price_review_service, rebate_service, or a future caller), not here.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import FinancialAmountEvidence, FinancialAmountStatusEvent, Opportunity, Supplier
from app.schemas.opportunity import OpportunityCreate
from app.services import audit_service

_WATERFALL_ORDER = ("identified", "validated", "approved", "implementation", "realised")


async def _write_opportunity_measure_event(
    db: AsyncSession, *, opportunity: Opportunity, measure_code: str, new_amount, new_status: str,
    new_source_basis: str | None, new_calculated_at=None, new_approved_at=None, new_approved_by_user_id=None,
    new_effective_period_start=None, new_effective_period_end=None,
    actor_user_id: int | None, change_reference: str, change_reason_code: str,
) -> FinancialAmountStatusEvent:
    """
    P-03: shared by both Opportunity measures (annual_financial_impact, realised_savings) - same
    locking/versioning mechanics as rebate_service._write_expected_amount_event, parameterized by
    measure since both share the opportunities table. Field names on the ORM object are looked
    up dynamically (getattr/setattr with the measure_code prefix) rather than duplicated per
    measure - the two measures' column sets differ (annual_financial_impact has no approval or
    end-period field), so callers pass None for whichever fields don't apply to their measure,
    and this function only writes the columns that actually exist for it.
    """
    locked = (await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity.id).with_for_update()
    )).scalar_one()

    if measure_code not in ("annual_financial_impact", "realised_savings"):
        raise ValueError(f"_write_opportunity_measure_event does not support measure_code={measure_code!r}")

    current_max = (await db.execute(
        select(func.max(FinancialAmountStatusEvent.event_version))
        .where(FinancialAmountStatusEvent.opportunity_id == locked.id)
        .where(FinancialAmountStatusEvent.measure_code == measure_code)
    )).scalar_one_or_none()
    next_version = (current_max or 0) + 1

    prefix = f"{measure_code}_"
    old_amount = getattr(locked, measure_code)
    old_status = getattr(locked, f"{prefix}status")
    old_source_basis = getattr(locked, f"{prefix}source_basis")
    old_calculated_at = getattr(locked, f"{prefix}calculated_at")
    if measure_code == "annual_financial_impact":
        old_approved_at = None
        old_approved_by_user_id = None
        old_period_start = locked.annual_financial_impact_effective_from
        old_period_end = None
    else:
        old_approved_at = locked.realised_savings_approved_at
        old_approved_by_user_id = locked.realised_savings_approved_by_user_id
        old_period_start = locked.realised_savings_effective_period_start
        old_period_end = locked.realised_savings_effective_period_end

    event = FinancialAmountStatusEvent(
        organisation_id=locked.organisation_id, opportunity_id=locked.id,
        measure_code=measure_code, event_version=next_version,
        old_amount=old_amount, new_amount=new_amount,
        old_status=old_status, new_status=new_status,
        old_source_basis=old_source_basis, new_source_basis=new_source_basis,
        old_calculated_at=old_calculated_at, new_calculated_at=new_calculated_at,
        old_approved_at=old_approved_at, new_approved_at=new_approved_at,
        old_approved_by_user_id=old_approved_by_user_id, new_approved_by_user_id=new_approved_by_user_id,
        old_effective_period_start=old_period_start, new_effective_period_start=new_effective_period_start,
        old_effective_period_end=old_period_end, new_effective_period_end=new_effective_period_end,
        actor_user_id=actor_user_id, occurred_at=datetime.now(UTC),
        change_reference=change_reference, change_reason_code=change_reason_code,
    )
    db.add(event)
    await db.flush()

    setattr(locked, measure_code, new_amount)
    setattr(locked, f"{prefix}status", new_status)
    setattr(locked, f"{prefix}source_basis", new_source_basis)
    setattr(locked, f"{prefix}calculated_at", new_calculated_at)
    if measure_code == "annual_financial_impact":
        locked.annual_financial_impact_effective_from = new_effective_period_start
        locked.annual_financial_impact_current_event_id = event.id
    else:
        locked.realised_savings_approved_at = new_approved_at
        locked.realised_savings_approved_by_user_id = new_approved_by_user_id
        locked.realised_savings_effective_period_start = new_effective_period_start
        locked.realised_savings_effective_period_end = new_effective_period_end
        locked.realised_savings_current_event_id = event.id

    return event


async def create_opportunity(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: OpportunityCreate,
) -> Opportunity:
    supplier_id = None
    if payload.supplier_public_id:
        result = await db.execute(select(Supplier.id).where(Supplier.public_id == payload.supplier_public_id))
        supplier_id = result.scalar_one_or_none()
        if supplier_id is None:
            raise NotFoundError("Supplier not found")

    # P-03: annual_financial_impact given without an effective period can't be marked
    # 'estimated' (the combination constraint requires both) - rather than silently downgrade
    # to 'unknown' and discard the caller's number, or invent a period they didn't state,
    # require both together explicitly. Neither given at all is fine - genuinely 'unknown'.
    if payload.annual_financial_impact is not None and payload.annual_financial_impact_effective_from is None:
        raise ConflictError(
            "annual_financial_impact requires annual_financial_impact_effective_from to be "
            "given alongside it - an estimate with no stated period can't be recorded as one"
        )

    opportunity = Opportunity(
        organisation_id=organisation_id, title=payload.title, opportunity_type=payload.opportunity_type,
        supplier_id=supplier_id, description=payload.description,
        savings_type=payload.savings_type,
        baseline_value=payload.baseline_value, baseline_methodology=payload.baseline_methodology,
        confidence=payload.confidence, status="identified", created_by_user_id=user_id,
        algorithm_version="v1", calculation_timestamp=datetime.now(UTC),
        annual_financial_impact_status="unknown",  # placeholder until the genesis event below sets it for real
        realised_savings_status="unknown",
    )
    db.add(opportunity)
    await db.flush()  # opportunity.id must be real before the genesis events below can reference it

    if payload.annual_financial_impact is not None:
        await _write_opportunity_measure_event(
            db, opportunity=opportunity, measure_code="annual_financial_impact",
            new_amount=payload.annual_financial_impact, new_status="estimated",
            new_source_basis="manual_estimate",
            new_effective_period_start=payload.annual_financial_impact_effective_from,
            actor_user_id=user_id, change_reference=f"opportunity_created:{opportunity.id}",
            change_reason_code="manual_estimate",
        )
    else:
        await _write_opportunity_measure_event(
            db, opportunity=opportunity, measure_code="annual_financial_impact",
            new_amount=None, new_status="unknown", new_source_basis=None,
            actor_user_id=user_id, change_reference=f"opportunity_created:{opportunity.id}",
            change_reason_code="manual_estimate",
        )
    # realised_savings genesis - always 'unknown' at creation, an opportunity can't have a
    # realised figure before it's even been through the waterfall.
    await _write_opportunity_measure_event(
        db, opportunity=opportunity, measure_code="realised_savings",
        new_amount=None, new_status="unknown", new_source_basis=None,
        actor_user_id=user_id, change_reference=f"opportunity_created:{opportunity.id}",
        change_reason_code="manual_estimate",
    )

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="opportunity_created",
        entity_type="opportunity", entity_id=None, context={"title": payload.title},
    )
    await db.commit()
    await db.refresh(opportunity)
    return opportunity


async def advance_waterfall_stage(
    db: AsyncSession, *, organisation_id: int, user_id: int, opportunity: Opportunity, target_status: str,
) -> Opportunity:
    """
    Enforces the waterfall order (spec Section 35: identified -> validated -> approved ->
    implementation -> realised) - an opportunity cannot skip a stage or move backwards through
    this function (rejected/expired are separate terminal states, reachable from any stage, not
    part of the ordered sequence this function enforces).
    """
    if target_status in ("rejected", "expired"):
        opportunity.status = target_status
    else:
        if target_status not in _WATERFALL_ORDER:
            raise ConflictError(f"Unknown waterfall stage: {target_status!r}")
        current_index = _WATERFALL_ORDER.index(opportunity.status) if opportunity.status in _WATERFALL_ORDER else -1
        target_index = _WATERFALL_ORDER.index(target_status)
        if target_index != current_index + 1:
            raise ConflictError(
                f"Cannot move from {opportunity.status!r} to {target_status!r} - "
                f"the waterfall advances one stage at a time"
            )
        opportunity.status = target_status
        if target_status == "approved":
            opportunity.approved_by_user_id = user_id
            opportunity.approved_at = datetime.now(UTC)

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="opportunity_stage_advanced",
        entity_type="opportunity", entity_id=str(opportunity.id), context={"new_status": target_status},
    )
    await db.commit()
    await db.refresh(opportunity)
    return opportunity


async def record_realised_savings(
    db: AsyncSession, *, organisation_id: int, user_id: int, opportunity: Opportunity,
    realised_savings: Decimal, effective_period_start: date, effective_period_end: date,
    documented_baseline_reference: str, actual_cost_source_reference: str,
    variance_calculation_reference: str, change_reference: str,
) -> Opportunity:
    """
    P-03: realised_savings can only ever reach 'confirmed' via 'reconciled_actuals', which
    requires at least three specific linked evidence rows (documented_baseline,
    actual_cost_source, variance_calculation_reference) - enforced at the database by the
    deferred confirmation-sufficiency trigger, not merely by this function's own discipline.
    All three reference strings are required parameters here precisely because the trigger will
    reject the commit if any is missing - failing early with a clear Python-level error is
    friendlier than a raw PL/pgSQL exception, but the trigger is what actually guarantees this,
    not this check.
    """
    if opportunity.status != "implementation":
        raise ConflictError(
            f"Cannot record realised savings from status {opportunity.status!r} - "
            f"an opportunity must be in 'implementation' first"
        )
    if effective_period_start > effective_period_end:
        raise ConflictError("effective_period_start must not be after effective_period_end")

    event = await _write_opportunity_measure_event(
        db, opportunity=opportunity, measure_code="realised_savings",
        new_amount=realised_savings, new_status="confirmed", new_source_basis="reconciled_actuals",
        new_approved_at=datetime.now(UTC), new_approved_by_user_id=user_id,
        new_effective_period_start=effective_period_start, new_effective_period_end=effective_period_end,
        actor_user_id=user_id, change_reference=change_reference, change_reason_code="evidence_received",
    )

    now = datetime.now(UTC)
    for evidence_type, external_reference in (
        ("documented_baseline", documented_baseline_reference),
        ("actual_cost_source", actual_cost_source_reference),
        ("variance_calculation_reference", variance_calculation_reference),
    ):
        db.add(FinancialAmountEvidence(
            organisation_id=organisation_id, event_id=event.id, evidence_type=evidence_type,
            external_reference=external_reference, recorded_at=now,
        ))

    opportunity.status = "realised"
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="opportunity_realised",
        entity_type="opportunity", entity_id=str(opportunity.id),
        context={"realised_savings": str(realised_savings)},
    )
    await db.commit()
    await db.refresh(opportunity)
    return opportunity


async def list_opportunities(
    db: AsyncSession, *, organisation_id: int, savings_type: str | None = None, status: str | None = None,
) -> list[Opportunity]:
    query = select(Opportunity)
    if savings_type:
        query = query.where(Opportunity.savings_type == savings_type)
    if status:
        query = query.where(Opportunity.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())
