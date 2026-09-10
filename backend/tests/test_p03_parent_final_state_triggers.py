"""
P03-CORE-R1: dedicated tests for the three deferred parent-final-state constraint triggers fixed
in migration 0024 - check_rpa_expected_amount_matches_event, check_opp_annual_financial_impact_
matches_event, check_opp_realised_savings_matches_event. Each is a CONSTRAINT TRIGGER, DEFERRABLE
INITIALLY DEFERRED, FOR EACH ROW - checked only at COMMIT, against the parent row's final state.

Deliberately independent of p03_seed and the existing P-03 raw-SQL test file's helpers
(_insert_event, _insert_period_actual, _insert_opportunity): those still carry open, separate
schema-parity defects (a RebateAgreement built without a supplier, raw INSERTs into
financial_amount_status_events that omit public_id) unrelated to this migration. This file builds
every prerequisite row itself, directly, with explicit public_id values, so it is unaffected by
either of those open issues and isolates proof of the migration 0024 fix on its own.

Uses plain psycopg async connections (db_conn, from conftest.py) rather than the ORM for the same
reason test_financial_amount_events_raw_sql.py does: these are raw-SQL proofs that the DATABASE
itself enforces the invariant, not a Python code path - and pytest.raises(...) around
`await db_conn.commit()` is how a DEFERRED constraint trigger's failure is actually observed
(it does not raise from the triggering INSERT/UPDATE statement itself, only at commit).
"""
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def rpa_prereqs(db_conn):
    """Independent of p03_seed: organisation + user + supplier + a genuinely supplier-backed
    buy_side RebateAgreement, built directly here so this file does not depend on p03_seed's
    still-open RebateAgreement defect. A fresh UUID-suffixed email keeps this fixture safely
    repeatable within one pytest session (function-scoped, invoked fresh per test)."""
    cur = await db_conn.execute(
        "INSERT INTO organisations (public_id, name, default_currency, country) "
        "VALUES (gen_random_uuid(), 'P03-CORE-R1 Org', 'ZAR', 'ZA') RETURNING id"
    )
    org_id = (await cur.fetchone())[0]

    cur = await db_conn.execute(
        "INSERT INTO users (public_id, first_name, last_name, email, password_hash, verified) "
        "VALUES (gen_random_uuid(), 'Trig', 'Test', %s, 'not-a-real-hash-test-only', true) RETURNING id",
        (f"p03-core-r1-{uuid.uuid4()}@procureiq.local",),
    )
    user_id = (await cur.fetchone())[0]

    cur = await db_conn.execute(
        "INSERT INTO suppliers (public_id, organisation_id, legal_name, currency) "
        "VALUES (gen_random_uuid(), %s, 'P03-CORE-R1 Supplier', 'ZAR') RETURNING id",
        (org_id,),
    )
    supplier_id = (await cur.fetchone())[0]

    cur = await db_conn.execute(
        "INSERT INTO rebate_agreements (public_id, organisation_id, supplier_id, direction, title, "
        "rebate_type, period_type, flat_rate_pct, currency, created_by_user_id, status) "
        "VALUES (gen_random_uuid(), %s, %s, 'buy_side', 'P03-CORE-R1 Agreement', 'fixed_percentage', "
        "'quarterly', 0.02, 'ZAR', %s, 'active') RETURNING id",
        (org_id, supplier_id, user_id),
    )
    agreement_id = (await cur.fetchone())[0]

    return {"org_id": org_id, "user_id": user_id, "supplier_id": supplier_id, "agreement_id": agreement_id}


@pytest_asyncio.fixture
async def opp_prereqs(db_conn):
    """Independent of p03_seed: organisation + user only, enough to insert an Opportunity."""
    cur = await db_conn.execute(
        "INSERT INTO organisations (public_id, name, default_currency, country) "
        "VALUES (gen_random_uuid(), 'P03-CORE-R1 Opp Org', 'ZAR', 'ZA') RETURNING id"
    )
    org_id = (await cur.fetchone())[0]

    cur = await db_conn.execute(
        "INSERT INTO users (public_id, first_name, last_name, email, password_hash, verified) "
        "VALUES (gen_random_uuid(), 'Trig', 'Opp', %s, 'not-a-real-hash-test-only', true) RETURNING id",
        (f"p03-core-r1-opp-{uuid.uuid4()}@procureiq.local",),
    )
    user_id = (await cur.fetchone())[0]

    return {"org_id": org_id, "user_id": user_id}


async def _insert_period_actual(
    db_conn, *, org_id, agreement_id, user_id, period_start="2026-01-01", period_end="2026-03-31",
) -> int:
    # uq_rebate_period is UNIQUE on (rebate_agreement_id, period_start, period_end) - callers that
    # need two period_actuals under the same agreement must pass distinct periods.
    cur = await db_conn.execute(
        "INSERT INTO rebate_period_actuals (public_id, organisation_id, rebate_agreement_id, "
        "period_start, period_end, entry_source, entered_by_user_id, expected_amount_status) "
        "VALUES (gen_random_uuid(), %s, %s, %s, %s, 'manual', %s, 'unknown') "
        "RETURNING id",
        (org_id, agreement_id, period_start, period_end, user_id),
    )
    return (await cur.fetchone())[0]


async def _insert_rpa_event(db_conn, *, org_id, period_actual_id, event_version=1, new_status="unknown") -> int:
    cur = await db_conn.execute(
        "INSERT INTO financial_amount_status_events (public_id, organisation_id, "
        "rebate_period_actual_id, measure_code, event_version, new_status, occurred_at, "
        "change_reference, change_reason_code) "
        "VALUES (gen_random_uuid(), %s, %s, 'expected_amount', %s, %s, now(), "
        "'p03_core_r1_test', 'initial_backfill') RETURNING id",
        (org_id, period_actual_id, event_version, new_status),
    )
    return (await cur.fetchone())[0]


async def _insert_opportunity(db_conn, *, org_id, user_id) -> int:
    cur = await db_conn.execute(
        "INSERT INTO opportunities (public_id, organisation_id, title, opportunity_type, status, "
        "created_by_user_id, annual_financial_impact_status, realised_savings_status) "
        "VALUES (gen_random_uuid(), %s, 'P03-CORE-R1 Opportunity', 'price_increase_challenge', "
        "'identified', %s, 'unknown', 'unknown') RETURNING id",
        (org_id, user_id),
    )
    return (await cur.fetchone())[0]


async def _insert_opp_event(db_conn, *, org_id, opportunity_id, measure_code, event_version=1) -> int:
    cur = await db_conn.execute(
        "INSERT INTO financial_amount_status_events (public_id, organisation_id, opportunity_id, "
        "measure_code, event_version, new_status, occurred_at, change_reference, change_reason_code) "
        "VALUES (gen_random_uuid(), %s, %s, %s, %s, 'unknown', now(), "
        "'p03_core_r1_test', 'initial_backfill') RETURNING id",
        (org_id, opportunity_id, measure_code, event_version),
    )
    return (await cur.fetchone())[0]


# ------------------------------------------------------------------
# RebatePeriodActual / expected_amount
# ------------------------------------------------------------------

@pytest.mark.integration
async def test_rpa_valid_insert_event_pointer_sequence_commits(db_conn, rpa_prereqs):
    period_actual_id = await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"],
    )
    event_id = await _insert_rpa_event(db_conn, org_id=rpa_prereqs["org_id"], period_actual_id=period_actual_id)
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_current_event_id = %s WHERE id = %s",
        (event_id, period_actual_id),
    )
    await db_conn.commit()


@pytest.mark.integration
async def test_rpa_no_event_no_pointer_fails_at_commit(db_conn, rpa_prereqs):
    await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"],
    )
    with pytest.raises(Exception, match="expected_amount_current_event_id must not be NULL at commit"):
        await db_conn.commit()


@pytest.mark.integration
async def test_rpa_event_created_but_pointer_never_updated_fails_at_commit(db_conn, rpa_prereqs):
    period_actual_id = await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"],
    )
    await _insert_rpa_event(db_conn, org_id=rpa_prereqs["org_id"], period_actual_id=period_actual_id)
    with pytest.raises(Exception, match="expected_amount_current_event_id must not be NULL at commit"):
        await db_conn.commit()


@pytest.mark.integration
async def test_rpa_pointer_references_a_different_parents_event_fails_at_commit(db_conn, rpa_prereqs):
    period_actual_a = await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"], period_start="2026-01-01", period_end="2026-03-31",
    )
    period_actual_b = await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"], period_start="2026-04-01", period_end="2026-06-30",
    )
    event_for_a = await _insert_rpa_event(db_conn, org_id=rpa_prereqs["org_id"], period_actual_id=period_actual_a)
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_current_event_id = %s WHERE id = %s",
        (event_for_a, period_actual_a),
    )
    # B's pointer wrongly references A's event
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_current_event_id = %s WHERE id = %s",
        (event_for_a, period_actual_b),
    )
    with pytest.raises(Exception, match="current_event_id does not reference a matching event"):
        await db_conn.commit()


@pytest.mark.integration
async def test_rpa_snapshot_mismatch_with_current_event_fails_at_commit(db_conn, rpa_prereqs):
    period_actual_id = await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"],
    )
    event_id = await _insert_rpa_event(
        db_conn, org_id=rpa_prereqs["org_id"], period_actual_id=period_actual_id, new_status="unknown",
    )
    # 'legacy_unverified' + a non-null amount is internally valid on its own
    # (ck_rpa_expected_amount_state_combination), but mismatches the referenced event's own
    # new_status='unknown'/new_amount=NULL - isolating the deferred trigger's snapshot check.
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_current_event_id = %s, "
        "expected_amount_status = 'legacy_unverified', expected_amount = 100 WHERE id = %s",
        (event_id, period_actual_id),
    )
    with pytest.raises(Exception, match="snapshot does not match its current event"):
        await db_conn.commit()


@pytest.mark.integration
async def test_rpa_pointer_not_latest_event_fails_at_commit(db_conn, rpa_prereqs):
    period_actual_id = await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"],
    )
    event_v1 = await _insert_rpa_event(
        db_conn, org_id=rpa_prereqs["org_id"], period_actual_id=period_actual_id, event_version=1,
    )
    await _insert_rpa_event(
        db_conn, org_id=rpa_prereqs["org_id"], period_actual_id=period_actual_id, event_version=2,
    )
    # points at v1 even though v2 (a later event) now exists
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_current_event_id = %s WHERE id = %s",
        (event_v1, period_actual_id),
    )
    with pytest.raises(Exception, match="current_event_id is not the latest event"):
        await db_conn.commit()


# ------------------------------------------------------------------
# Opportunity / annual_financial_impact + realised_savings
# ------------------------------------------------------------------

@pytest.mark.integration
async def test_opportunity_valid_both_genesis_events_and_pointers_commits(db_conn, opp_prereqs):
    opportunity_id = await _insert_opportunity(db_conn, org_id=opp_prereqs["org_id"], user_id=opp_prereqs["user_id"])
    afi_event = await _insert_opp_event(
        db_conn, org_id=opp_prereqs["org_id"], opportunity_id=opportunity_id, measure_code="annual_financial_impact",
    )
    rs_event = await _insert_opp_event(
        db_conn, org_id=opp_prereqs["org_id"], opportunity_id=opportunity_id, measure_code="realised_savings",
    )
    await db_conn.execute(
        "UPDATE opportunities SET annual_financial_impact_current_event_id = %s, "
        "realised_savings_current_event_id = %s WHERE id = %s",
        (afi_event, rs_event, opportunity_id),
    )
    await db_conn.commit()


@pytest.mark.integration
async def test_opportunity_annual_pointer_left_null_fails_at_commit(db_conn, opp_prereqs):
    opportunity_id = await _insert_opportunity(db_conn, org_id=opp_prereqs["org_id"], user_id=opp_prereqs["user_id"])
    rs_event = await _insert_opp_event(
        db_conn, org_id=opp_prereqs["org_id"], opportunity_id=opportunity_id, measure_code="realised_savings",
    )
    await db_conn.execute(
        "UPDATE opportunities SET realised_savings_current_event_id = %s WHERE id = %s",
        (rs_event, opportunity_id),
    )
    with pytest.raises(Exception, match="annual_financial_impact_current_event_id must not be NULL at commit"):
        await db_conn.commit()


@pytest.mark.integration
async def test_opportunity_realised_pointer_left_null_fails_at_commit(db_conn, opp_prereqs):
    opportunity_id = await _insert_opportunity(db_conn, org_id=opp_prereqs["org_id"], user_id=opp_prereqs["user_id"])
    afi_event = await _insert_opp_event(
        db_conn, org_id=opp_prereqs["org_id"], opportunity_id=opportunity_id, measure_code="annual_financial_impact",
    )
    await db_conn.execute(
        "UPDATE opportunities SET annual_financial_impact_current_event_id = %s WHERE id = %s",
        (afi_event, opportunity_id),
    )
    with pytest.raises(Exception, match="realised_savings_current_event_id must not be NULL at commit"):
        await db_conn.commit()


@pytest.mark.integration
async def test_opportunity_annual_pointer_references_wrong_measure_event_fails_at_commit(db_conn, opp_prereqs):
    opportunity_id = await _insert_opportunity(db_conn, org_id=opp_prereqs["org_id"], user_id=opp_prereqs["user_id"])
    # a genuine realised_savings event, wrongly pointed to by annual_financial_impact's pointer
    rs_event = await _insert_opp_event(
        db_conn, org_id=opp_prereqs["org_id"], opportunity_id=opportunity_id, measure_code="realised_savings",
    )
    await db_conn.execute(
        "UPDATE opportunities SET annual_financial_impact_current_event_id = %s, "
        "realised_savings_current_event_id = %s WHERE id = %s",
        (rs_event, rs_event, opportunity_id),
    )
    with pytest.raises(Exception, match="annual_financial_impact_current_event_id mismatch"):
        await db_conn.commit()


# ------------------------------------------------------------------
# Edge case: row deleted within the same transaction before commit
# ------------------------------------------------------------------

@pytest.mark.integration
async def test_rpa_deleted_before_commit_does_not_raise(db_conn, rpa_prereqs):
    """A deferred commit-time invariant on a row that no longer exists has nothing to validate -
    deleting the row later in the same transaction must not turn into a spurious failure."""
    period_actual_id = await _insert_period_actual(
        db_conn, org_id=rpa_prereqs["org_id"], agreement_id=rpa_prereqs["agreement_id"],
        user_id=rpa_prereqs["user_id"],
    )
    # Deliberately leaves the pointer NULL - would fail at commit if the row still existed.
    await db_conn.execute("DELETE FROM rebate_period_actuals WHERE id = %s", (period_actual_id,))
    await db_conn.commit()


@pytest.mark.integration
async def test_opportunity_deleted_before_commit_does_not_raise(db_conn, opp_prereqs):
    opportunity_id = await _insert_opportunity(db_conn, org_id=opp_prereqs["org_id"], user_id=opp_prereqs["user_id"])
    await db_conn.execute("DELETE FROM opportunities WHERE id = %s", (opportunity_id,))
    await db_conn.commit()
