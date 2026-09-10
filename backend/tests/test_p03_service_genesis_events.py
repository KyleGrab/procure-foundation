"""
P03-CORE-R1: proves the real production event-writer paths - rebate_service.record_period_actual/
recalculate_expected and opportunity_service.create_opportunity/record_realised_savings - satisfy
ck_famev_genesis_old_fields_null (migration 0021: a genesis, version-1 event must have every
old_* field NULL) while still correctly chaining old_*/new_* across later, non-genesis events.

Deliberately independent of p03_seed - builds its own organisation/user/supplier/agreement rows
directly via the ORM, so this file is unaffected by p03_seed's still-open, separate schema-parity
defects. Exercises the actual public service functions (never touches
FinancialAmountStatusEvent/the writer helpers directly) so this is proof of the real code path,
not a reimplementation of it. Asserts against the stored event rows themselves, not merely that
the service call returned - the persisted event history is the control being verified.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select


async def _make_rebate_prereqs(db_session):
    from app.db.models import Organisation, RebateAgreement, Supplier, User

    org = Organisation(name="P03-CORE-R1 Service Org", default_currency="ZAR", country="ZA")
    db_session.add(org)
    await db_session.flush()

    user = User(
        first_name="Trig", last_name="Service", email=f"p03-core-r1-svc-{uuid.uuid4()}@procureiq.local",
        password_hash="not-a-real-hash-test-only", verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    supplier = Supplier(organisation_id=org.id, legal_name="P03-CORE-R1 Service Supplier", currency="ZAR")
    db_session.add(supplier)
    await db_session.flush()

    agreement = RebateAgreement(
        organisation_id=org.id, supplier_id=supplier.id, direction="buy_side",
        title="P03-CORE-R1 Service Agreement", rebate_type="fixed_percentage", period_type="quarterly",
        flat_rate_pct=Decimal("0.02"), currency="ZAR", created_by_user_id=user.id,
    )
    db_session.add(agreement)
    await db_session.flush()

    return org, user, agreement


async def _make_opp_prereqs(db_session):
    from app.db.models import Organisation, User

    org = Organisation(name="P03-CORE-R1 Opp Service Org", default_currency="ZAR", country="ZA")
    db_session.add(org)
    await db_session.flush()

    user = User(
        first_name="Trig", last_name="OppService", email=f"p03-core-r1-opp-svc-{uuid.uuid4()}@procureiq.local",
        password_hash="not-a-real-hash-test-only", verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    return org, user


# ------------------------------------------------------------------
# A + B: rebate_service - genesis, then a real version-2 recalculation
# ------------------------------------------------------------------

@pytest.mark.integration
async def test_rebate_period_actual_genesis_event_has_all_old_fields_null(db_session):
    from app.db.models import FinancialAmountStatusEvent
    from app.schemas.rebate import RebatePeriodActualCreate
    from app.services.rebate_service import record_period_actual

    org, user, agreement = await _make_rebate_prereqs(db_session)

    payload = RebatePeriodActualCreate(
        period_start=date(2026, 1, 1), period_end=date(2026, 3, 31), actual_spend=Decimal("0"),
    )
    period_actual = await record_period_actual(
        db_session, organisation_id=org.id, user_id=user.id, agreement=agreement, payload=payload,
    )
    assert period_actual.expected_amount_current_event_id is not None

    genesis_event = (await db_session.execute(
        select(FinancialAmountStatusEvent)
        .where(FinancialAmountStatusEvent.rebate_period_actual_id == period_actual.id)
        .where(FinancialAmountStatusEvent.measure_code == "expected_amount")
        .where(FinancialAmountStatusEvent.event_version == 1)
    )).scalar_one()

    assert genesis_event.old_amount is None
    assert genesis_event.old_status is None
    assert genesis_event.old_source_basis is None
    assert genesis_event.old_calculated_at is None
    assert genesis_event.old_approved_at is None
    assert genesis_event.old_approved_by_user_id is None

    assert genesis_event.new_status == period_actual.expected_amount_status
    assert genesis_event.new_amount == period_actual.expected_amount
    assert genesis_event.new_source_basis == period_actual.expected_amount_source_basis
    assert period_actual.expected_amount_current_event_id == genesis_event.id


@pytest.mark.integration
async def test_rebate_period_actual_version_2_old_fields_match_version_1_new_fields(db_session):
    from app.db.models import FinancialAmountStatusEvent
    from app.schemas.rebate import RebatePeriodActualCreate
    from app.services.rebate_service import record_period_actual, recalculate_expected

    org, user, agreement = await _make_rebate_prereqs(db_session)

    payload = RebatePeriodActualCreate(
        period_start=date(2026, 1, 1), period_end=date(2026, 3, 31), actual_spend=Decimal("0"),
    )
    period_actual = await record_period_actual(
        db_session, organisation_id=org.id, user_id=user.id, agreement=agreement, payload=payload,
    )

    genesis_event = (await db_session.execute(
        select(FinancialAmountStatusEvent)
        .where(FinancialAmountStatusEvent.rebate_period_actual_id == period_actual.id)
        .where(FinancialAmountStatusEvent.measure_code == "expected_amount")
        .where(FinancialAmountStatusEvent.event_version == 1)
    )).scalar_one()

    # A real recalculation, through the actual production path - not a hand-written event.
    period_actual.actual_spend = Decimal("50000")
    await recalculate_expected(
        db_session, agreement=agreement, period_actual=period_actual, actor_user_id=user.id,
        change_reference=f"test_recalc:{period_actual.id}", change_reason_code="recalculation",
    )
    await db_session.commit()
    await db_session.refresh(period_actual)

    version_2 = (await db_session.execute(
        select(FinancialAmountStatusEvent)
        .where(FinancialAmountStatusEvent.rebate_period_actual_id == period_actual.id)
        .where(FinancialAmountStatusEvent.measure_code == "expected_amount")
        .where(FinancialAmountStatusEvent.event_version == 2)
    )).scalar_one()

    # The fix must not erase real history: version 2's old_* is version 1's new_*, not NULL.
    assert version_2.old_amount == genesis_event.new_amount
    assert version_2.old_status == genesis_event.new_status
    assert version_2.old_source_basis == genesis_event.new_source_basis
    assert version_2.old_calculated_at == genesis_event.new_calculated_at
    assert version_2.new_amount != genesis_event.new_amount  # a real, different recalculation
    assert period_actual.expected_amount_current_event_id == version_2.id


# ------------------------------------------------------------------
# C + D: opportunity_service - both genesis events, then a real version-2 path
# ------------------------------------------------------------------

@pytest.mark.integration
async def test_opportunity_genesis_events_have_all_old_fields_null(db_session):
    from app.db.models import FinancialAmountStatusEvent
    from app.schemas.opportunity import OpportunityCreate
    from app.services.opportunity_service import create_opportunity

    org, user = await _make_opp_prereqs(db_session)

    payload = OpportunityCreate(
        title="P03-CORE-R1 Service Opportunity", opportunity_type="price_increase_challenge",
        annual_financial_impact=Decimal("12000"), annual_financial_impact_effective_from=date(2026, 1, 1),
    )
    opportunity = await create_opportunity(db_session, organisation_id=org.id, user_id=user.id, payload=payload)

    assert opportunity.annual_financial_impact_current_event_id is not None
    assert opportunity.realised_savings_current_event_id is not None

    afi_genesis = (await db_session.execute(
        select(FinancialAmountStatusEvent)
        .where(FinancialAmountStatusEvent.opportunity_id == opportunity.id)
        .where(FinancialAmountStatusEvent.measure_code == "annual_financial_impact")
        .where(FinancialAmountStatusEvent.event_version == 1)
    )).scalar_one()
    rs_genesis = (await db_session.execute(
        select(FinancialAmountStatusEvent)
        .where(FinancialAmountStatusEvent.opportunity_id == opportunity.id)
        .where(FinancialAmountStatusEvent.measure_code == "realised_savings")
        .where(FinancialAmountStatusEvent.event_version == 1)
    )).scalar_one()

    for ev in (afi_genesis, rs_genesis):
        assert ev.old_amount is None
        assert ev.old_status is None
        assert ev.old_source_basis is None
        assert ev.old_calculated_at is None
        assert ev.old_approved_at is None
        assert ev.old_approved_by_user_id is None
        assert ev.old_effective_period_start is None
        assert ev.old_effective_period_end is None

    assert afi_genesis.new_amount == opportunity.annual_financial_impact
    assert afi_genesis.new_status == opportunity.annual_financial_impact_status
    assert opportunity.annual_financial_impact_current_event_id == afi_genesis.id
    assert rs_genesis.new_status == opportunity.realised_savings_status
    assert opportunity.realised_savings_current_event_id == rs_genesis.id


@pytest.mark.integration
async def test_opportunity_realised_savings_version_2_old_fields_match_version_1_new_fields(db_session):
    from app.db.models import FinancialAmountStatusEvent
    from app.schemas.opportunity import OpportunityCreate
    from app.services.opportunity_service import advance_waterfall_stage, create_opportunity, record_realised_savings

    org, user = await _make_opp_prereqs(db_session)

    payload = OpportunityCreate(title="P03-CORE-R1 Waterfall Opportunity", opportunity_type="price_increase_challenge")
    opportunity = await create_opportunity(db_session, organisation_id=org.id, user_id=user.id, payload=payload)

    rs_genesis = (await db_session.execute(
        select(FinancialAmountStatusEvent)
        .where(FinancialAmountStatusEvent.opportunity_id == opportunity.id)
        .where(FinancialAmountStatusEvent.measure_code == "realised_savings")
        .where(FinancialAmountStatusEvent.event_version == 1)
    )).scalar_one()

    for target in ("validated", "approved", "implementation"):
        opportunity = await advance_waterfall_stage(
            db_session, organisation_id=org.id, user_id=user.id, opportunity=opportunity, target_status=target,
        )

    opportunity = await record_realised_savings(
        db_session, organisation_id=org.id, user_id=user.id, opportunity=opportunity,
        realised_savings=Decimal("5000"),
        effective_period_start=date(2026, 1, 1), effective_period_end=date(2026, 3, 31),
        documented_baseline_reference="BASELINE-CORE-R1", actual_cost_source_reference="COST-CORE-R1",
        variance_calculation_reference="VAR-CORE-R1", change_reference=f"test_realised:{opportunity.id}",
    )

    version_2 = (await db_session.execute(
        select(FinancialAmountStatusEvent)
        .where(FinancialAmountStatusEvent.opportunity_id == opportunity.id)
        .where(FinancialAmountStatusEvent.measure_code == "realised_savings")
        .where(FinancialAmountStatusEvent.event_version == 2)
    )).scalar_one()

    assert version_2.old_amount == rs_genesis.new_amount
    assert version_2.old_status == rs_genesis.new_status
    assert version_2.old_source_basis == rs_genesis.new_source_basis
    assert version_2.old_calculated_at == rs_genesis.new_calculated_at
    assert version_2.old_approved_at == rs_genesis.new_approved_at
    assert version_2.old_approved_by_user_id == rs_genesis.new_approved_by_user_id
    assert version_2.old_effective_period_start == rs_genesis.new_effective_period_start
    assert version_2.old_effective_period_end == rs_genesis.new_effective_period_end
    assert version_2.new_status == "confirmed"
    assert opportunity.realised_savings_current_event_id == version_2.id
