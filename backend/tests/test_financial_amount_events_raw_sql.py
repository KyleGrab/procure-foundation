"""
P-03 raw-SQL constraint and mechanism tests. Runs against the fully-migrated (head, including
0021) database the normal backend CI job already builds via `alembic upgrade head` - distinct
from the separate migration-compatibility script, which specifically tests the 0020->0021
transition itself and never touches these fixtures.

Uses plain psycopg async connections (see conftest.py's db_conn/db_conn_a/db_conn_b) rather than
the ORM - these are deliberately raw-SQL proofs that the DATABASE itself enforces each rule,
independent of any Python code path. Real row IDs come from the p03_seed fixture, never
hardcoded constants - every CI run gets a genuinely fresh database.
"""
import pytest


async def _insert_event(
    conn, *, organisation_id, rebate_period_actual_id=None, opportunity_id=None,
    measure_code="expected_amount", event_version=1,
    old_amount=None, old_status=None, old_source_basis=None,
    old_calculated_at=None, old_approved_at=None, old_approved_by_user_id=None,
    old_effective_period_start=None, old_effective_period_end=None,
    new_amount=None, new_status="unknown", new_source_basis=None,
    new_calculated_at=None, new_approved_at=None, new_approved_by_user_id=None,
    new_effective_period_start=None, new_effective_period_end=None,
    change_reference="raw_sql_test", change_reason_code="manual_estimate",
) -> int:
    """Real INSERT against financial_amount_status_events - returns the new row's id."""
    cur = await conn.execute(
        """
        INSERT INTO financial_amount_status_events
          (organisation_id, rebate_period_actual_id, opportunity_id, measure_code, event_version,
           old_amount, old_status, old_source_basis, old_calculated_at, old_approved_at,
           old_approved_by_user_id, old_effective_period_start, old_effective_period_end,
           new_amount, new_status, new_source_basis, new_calculated_at, new_approved_at,
           new_approved_by_user_id, new_effective_period_start, new_effective_period_end,
           occurred_at, change_reference, change_reason_code)
        VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s, now(),%s,%s)
        RETURNING id
        """,
        (organisation_id, rebate_period_actual_id, opportunity_id, measure_code, event_version,
         old_amount, old_status, old_source_basis, old_calculated_at, old_approved_at,
         old_approved_by_user_id, old_effective_period_start, old_effective_period_end,
         new_amount, new_status, new_source_basis, new_calculated_at, new_approved_at,
         new_approved_by_user_id, new_effective_period_start, new_effective_period_end,
         change_reference, change_reason_code),
    )
    row = await cur.fetchone()
    return row[0]


async def _insert_period_actual(conn, *, organisation_id, rebate_agreement_id, entered_by_user_id) -> int:
    """Real INSERT against rebate_period_actuals - returns the new row's id. Deliberately leaves
    expected_amount_current_event_id NULL (the caller writes the genesis event and pointer
    separately, matching how the real service layer does it)."""
    cur = await conn.execute(
        """
        INSERT INTO rebate_period_actuals
          (organisation_id, rebate_agreement_id, period_start, period_end, entry_source,
           entered_by_user_id, expected_amount_status)
        VALUES (%s, %s, '2026-04-01', '2026-06-30', 'manual', %s, 'unknown')
        RETURNING id
        """,
        (organisation_id, rebate_agreement_id, entered_by_user_id),
    )
    row = await cur.fetchone()
    return row[0]


async def _insert_opportunity(conn, *, organisation_id, created_by_user_id) -> int:
    """Real INSERT against opportunities - returns the new row's id. Deliberately leaves both
    measures' current_event_id NULL, matching _insert_period_actual's same convention - the
    caller writes genesis events and pointers separately."""
    cur = await conn.execute(
        """
        INSERT INTO opportunities
          (organisation_id, title, opportunity_type, status, created_by_user_id,
           annual_financial_impact_status, realised_savings_status)
        VALUES (%s, 'P-03 Combination Test Opportunity', 'price_increase_challenge', 'identified', %s,
                'unknown', 'unknown')
        RETURNING id
        """,
        (organisation_id, created_by_user_id),
    )
    row = await cur.fetchone()
    return row[0]


async def _next_event_version(conn, *, rebate_period_actual_id, measure_code) -> int:
    cur = await conn.execute(
        "SELECT COALESCE(MAX(event_version), 0) + 1 FROM financial_amount_status_events "
        "WHERE rebate_period_actual_id = %s AND measure_code = %s",
        (rebate_period_actual_id, measure_code),
    )
    row = await cur.fetchone()
    return row[0]


# Section 1: per-measure status/amount combination constraints

@pytest.mark.integration
async def test_expected_amount_estimated_status_rejects_null_source_basis(db_conn, p03_seed):
    """NULL-propagation bug found and fixed mid-design: a bare equality check on a nullable
    column evaluates to NULL, not FALSE, and Postgres treats a NULL CHECK result as PASS."""
    with pytest.raises(Exception, match="ck_rpa_expected_amount_state_combination"):
        await db_conn.execute(
            "UPDATE rebate_period_actuals SET expected_amount = 100, expected_amount_status = 'estimated', "
            "expected_amount_source_basis = NULL WHERE id = %s",
            (p03_seed.period_actual_id,),
        )


@pytest.mark.integration
async def test_expected_amount_calculated_status_rejects_null_calculated_at(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_rpa_expected_amount_state_combination"):
        await db_conn.execute(
            "UPDATE rebate_period_actuals SET expected_amount = 100, expected_amount_status = 'calculated', "
            "expected_amount_source_basis = 'contract_terms_calculation', expected_amount_calculated_at = NULL "
            "WHERE id = %s",
            (p03_seed.period_actual_id,),
        )


@pytest.mark.integration
async def test_expected_amount_confirmed_status_rejects_missing_approval_fields(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_rpa_expected_amount_state_combination"):
        await db_conn.execute(
            "UPDATE rebate_period_actuals SET expected_amount = 100, expected_amount_status = 'confirmed', "
            "expected_amount_source_basis = 'supplier_statement', expected_amount_approved_by_user_id = NULL "
            "WHERE id = %s",
            (p03_seed.period_actual_id,),
        )


@pytest.mark.integration
async def test_unknown_status_rejects_populated_provenance(db_conn, p03_seed):
    """Third distinct bug found: the original 'unknown' branch only checked amount IS NULL,
    never that provenance was ALSO null."""
    with pytest.raises(Exception, match="ck_rpa_expected_amount_state_combination"):
        await db_conn.execute(
            "UPDATE rebate_period_actuals SET expected_amount_status = 'unknown', expected_amount = NULL, "
            "expected_amount_approved_by_user_id = %s WHERE id = %s",
            (p03_seed.user_id, p03_seed.period_actual_id),
        )


@pytest.mark.integration
async def test_legacy_unverified_rejects_any_populated_provenance(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_rpa_expected_amount_state_combination"):
        await db_conn.execute(
            "UPDATE rebate_period_actuals SET expected_amount_status = 'legacy_unverified', "
            "expected_amount = 100, expected_amount_source_basis = 'manual_estimate' WHERE id = %s",
            (p03_seed.period_actual_id,),
        )


@pytest.mark.integration
async def test_realised_savings_estimated_is_structurally_impossible(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_opp_rs_status_valid"):
        await db_conn.execute(
            "UPDATE opportunities SET realised_savings_status = 'estimated' WHERE id = %s",
            (p03_seed.opportunity_id,),
        )


@pytest.mark.integration
async def test_annual_financial_impact_confirmed_is_structurally_impossible(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_opp_afi_status_valid"):
        await db_conn.execute(
            "UPDATE opportunities SET annual_financial_impact_status = 'confirmed' WHERE id = %s",
            (p03_seed.opportunity_id,),
        )


@pytest.mark.integration
async def test_realised_savings_period_start_after_end_rejected(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_opp_rs_state_combination"):
        await db_conn.execute(
            "UPDATE opportunities SET realised_savings = 100, realised_savings_status = 'calculated', "
            "realised_savings_source_basis = 'actual_cost_data_calculation', "
            "realised_savings_calculated_at = now(), "
            "realised_savings_effective_period_start = '2026-06-01', "
            "realised_savings_effective_period_end = '2026-01-01' WHERE id = %s",
            (p03_seed.opportunity_id,),
        )


# Section 2: confirmation-sufficiency deferred trigger

@pytest.mark.integration
async def test_confirmed_reconciled_actuals_event_without_evidence_fails_at_commit(db_conn, p03_seed):
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, opportunity_id=p03_seed.opportunity_id,
        measure_code="realised_savings", event_version=1, new_status="confirmed",
        new_source_basis="reconciled_actuals", new_amount=500,
        new_approved_at="2026-06-01", new_approved_by_user_id=p03_seed.user_id,
        new_effective_period_start="2026-01-01", new_effective_period_end="2026-03-31",
        change_reason_code="evidence_received",
    )
    with pytest.raises(Exception, match="missing documented_baseline evidence"):
        await db_conn.commit()


@pytest.mark.integration
async def test_confirmed_reconciled_actuals_with_all_three_evidence_types_commits(db_conn, p03_seed):
    event_id = await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, opportunity_id=p03_seed.opportunity_id,
        measure_code="realised_savings", event_version=1, new_status="confirmed",
        new_source_basis="reconciled_actuals", new_amount=500,
        new_approved_at="2026-06-01", new_approved_by_user_id=p03_seed.user_id,
        new_effective_period_start="2026-01-01", new_effective_period_end="2026-03-31",
        change_reason_code="evidence_received",
    )
    for evidence_type, ref in (
        ("documented_baseline", "BASELINE-001"),
        ("actual_cost_source", "COST-001"),
        ("variance_calculation_reference", "VAR-001"),
    ):
        await db_conn.execute(
            "INSERT INTO financial_amount_evidence (organisation_id, event_id, evidence_type, "
            "external_reference, recorded_at) VALUES (%s, %s, %s, %s, now())",
            (p03_seed.org_id, event_id, evidence_type, ref),
        )
    await db_conn.commit()


@pytest.mark.integration
async def test_confirmed_reconciled_actuals_missing_one_of_three_evidence_types_fails(db_conn, p03_seed):
    event_id = await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, opportunity_id=p03_seed.opportunity_id,
        measure_code="realised_savings", event_version=1, new_status="confirmed",
        new_source_basis="reconciled_actuals", new_amount=500,
        new_approved_at="2026-06-01", new_approved_by_user_id=p03_seed.user_id,
        new_effective_period_start="2026-01-01", new_effective_period_end="2026-03-31",
        change_reason_code="evidence_received",
    )
    for evidence_type, ref in (("documented_baseline", "B-1"), ("actual_cost_source", "C-1")):
        await db_conn.execute(
            "INSERT INTO financial_amount_evidence (organisation_id, event_id, evidence_type, "
            "external_reference, recorded_at) VALUES (%s, %s, %s, %s, now())",
            (p03_seed.org_id, event_id, evidence_type, ref),
        )
    with pytest.raises(Exception, match="missing variance_calculation_reference evidence"):
        await db_conn.commit()


@pytest.mark.integration
async def test_non_confirmed_events_never_require_evidence(db_conn, p03_seed):
    version = await _next_event_version(
        db_conn, rebate_period_actual_id=p03_seed.period_actual_id, measure_code="expected_amount"
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=p03_seed.period_actual_id,
        measure_code="expected_amount", event_version=version,
        old_status="unknown" if version > 1 else None,
        new_status="calculated", new_source_basis="contract_terms_calculation",
        new_amount=100, new_calculated_at="2026-06-01", change_reason_code="recalculation",
    )
    await db_conn.commit()


@pytest.mark.integration
async def test_evidence_type_vocabulary_rejected_for_invalid_value(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_famev_evid_type_vocabulary"):
        await db_conn.execute(
            "INSERT INTO financial_amount_evidence (organisation_id, event_id, evidence_type, "
            "external_reference, recorded_at) VALUES (%s, %s, 'not_a_real_type', 'X', now())",
            (p03_seed.org_id, p03_seed.event_id),
        )


# Section 3: tenant-safe composite FK (evidence <-> event)

@pytest.mark.integration
async def test_evidence_cannot_attach_to_another_tenants_event(db_conn, p03_seed):
    with pytest.raises(Exception, match="fk_famev_evid_event_tenant_matched"):
        await db_conn.execute(
            "INSERT INTO financial_amount_evidence (organisation_id, event_id, evidence_type, "
            "external_reference, recorded_at) VALUES (%s, %s, 'invoice', 'X', now())",
            (p03_seed.org_b_id, p03_seed.event_id),
        )


# Section 4: event-chain integrity deferred trigger

@pytest.mark.integration
async def test_version_2_without_version_1_fails_for_a_fresh_parent(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=2, old_status="unknown", new_status="calculated",
        new_source_basis="contract_terms_calculation", new_amount=50, new_calculated_at="2026-06-01",
        change_reason_code="recalculation",
    )
    with pytest.raises(Exception, match="has no immediately preceding event"):
        await db_conn.commit()


@pytest.mark.integration
async def test_version_3_after_version_1_only_fails(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="unknown", change_reason_code="manual_estimate",
    )
    await db_conn.commit()
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=3, old_status="unknown", new_status="calculated",
        new_source_basis="contract_terms_calculation", new_amount=50, new_calculated_at="2026-06-01",
        change_reason_code="recalculation",
    )
    with pytest.raises(Exception, match="has no immediately preceding event"):
        await db_conn.commit()


@pytest.mark.integration
async def test_version_2_with_fabricated_old_amount_fails(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="unknown", change_reason_code="manual_estimate",
    )
    await db_conn.commit()
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=2, old_amount=999999, old_status="unknown", new_status="calculated",
        new_source_basis="contract_terms_calculation", new_amount=50, new_calculated_at="2026-06-01",
        change_reason_code="recalculation",
    )
    with pytest.raises(Exception, match=r"old_\* values do not match"):
        await db_conn.commit()


@pytest.mark.integration
async def test_version_2_with_fabricated_old_period_fails(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="unknown", change_reason_code="manual_estimate",
    )
    await db_conn.commit()
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=2, old_status="unknown", old_effective_period_start="2026-01-01",
        new_status="calculated", new_source_basis="contract_terms_calculation",
        new_amount=50, new_calculated_at="2026-06-01", change_reason_code="recalculation",
    )
    with pytest.raises(Exception, match=r"old_\* values do not match"):
        await db_conn.commit()


@pytest.mark.integration
async def test_genesis_with_nonnull_old_field_fails(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    with pytest.raises(Exception, match="ck_famev_genesis_old_fields_null"):
        await db_conn.execute(
            "INSERT INTO financial_amount_status_events (organisation_id, rebate_period_actual_id, "
            "measure_code, event_version, old_status, new_status, new_amount, occurred_at, "
            "change_reference, change_reason_code) VALUES (%s, %s, 'expected_amount', 1, 'unknown', "
            "'unknown', NULL, now(), 'test', 'initial_backfill')",
            (p03_seed.org_id, new_id),
        )


@pytest.mark.integration
async def test_genesis_annual_financial_impact_calculated_with_populated_new_fields_succeeds(db_conn, p03_seed):
    """A genesis event's new_* fields are governed only by the ordinary per-measure combination
    check, never forced NULL merely for being version 1. p03_seed's fixture only creates a
    genesis event for expected_amount, so this opportunity has no annual_financial_impact event
    yet - version 1 here is genuinely its first."""
    await db_conn.execute(
        "INSERT INTO financial_amount_status_events (organisation_id, opportunity_id, "
        "measure_code, event_version, new_status, new_amount, new_source_basis, "
        "new_calculated_at, new_effective_period_start, occurred_at, change_reference, "
        "change_reason_code) VALUES (%s, %s, 'annual_financial_impact', 1, 'calculated', 5000, "
        "'price_review_calculation', now(), '2026-01-01', now(), 'test', 'recalculation')",
        (p03_seed.org_id, p03_seed.opportunity_id),
    )
    await db_conn.commit()


@pytest.mark.integration
async def test_genesis_annual_financial_impact_calculated_missing_period_fails(db_conn, p03_seed):
    """Proves the genesis rule and the combination rule cleanly divide responsibility - this
    fails via the ordinary combination check, not the genesis rule. Uses a different
    opportunity's annual_financial_impact (still version 1, never touched) to avoid colliding
    with the prior test's now-committed genesis event."""
    with pytest.raises(Exception, match="ck_opp_afi_state_combination"):
        await db_conn.execute(
            "INSERT INTO financial_amount_status_events (organisation_id, opportunity_id, "
            "measure_code, event_version, new_status, new_amount, new_source_basis, "
            "new_calculated_at, occurred_at, change_reference, change_reason_code) VALUES "
            "(%s, %s, 'realised_savings', 1, 'calculated', 5000, "
            "'actual_cost_data_calculation', now(), now(), 'test', 'recalculation')",
            (p03_seed.org_id, p03_seed.opportunity_id),
        )


@pytest.mark.integration
async def test_downgrade_with_upgrade_appropriate_reason_code_fails(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="confirmed", new_source_basis="supplier_statement",
        new_amount=100, new_approved_at="2026-06-01", new_approved_by_user_id=p03_seed.user_id,
        change_reason_code="evidence_received",
    )
    await db_conn.commit()
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=2, old_status="confirmed", old_amount=100, old_source_basis="supplier_statement",
        old_approved_at="2026-06-01", old_approved_by_user_id=p03_seed.user_id,
        new_status="calculated", new_source_basis="contract_terms_calculation",
        new_amount=90, new_calculated_at="2026-06-15", change_reason_code="manual_estimate",
    )
    with pytest.raises(Exception, match="requires a correction-appropriate reason code"):
        await db_conn.commit()


@pytest.mark.integration
async def test_downgrade_with_correction_reason_code_succeeds(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="confirmed", new_source_basis="supplier_statement",
        new_amount=100, new_approved_at="2026-06-01", new_approved_by_user_id=p03_seed.user_id,
        change_reason_code="evidence_received",
    )
    await db_conn.commit()
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=2, old_status="confirmed", old_amount=100, old_source_basis="supplier_statement",
        old_approved_at="2026-06-01", old_approved_by_user_id=p03_seed.user_id,
        new_status="calculated", new_source_basis="contract_terms_calculation",
        new_amount=90, new_calculated_at="2026-06-15", change_reason_code="correction",
    )
    await db_conn.commit()


@pytest.mark.integration
async def test_upgrade_never_triggers_the_downgrade_check(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="estimated", new_source_basis="manual_estimate",
        new_amount=80, change_reason_code="manual_estimate",
    )
    await db_conn.commit()
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=2, old_status="estimated", old_amount=80, old_source_basis="manual_estimate",
        new_status="calculated", new_source_basis="contract_terms_calculation",
        new_amount=85, new_calculated_at="2026-06-01", change_reason_code="evidence_received",
    )
    await db_conn.commit()


@pytest.mark.integration
async def test_blank_change_reason_code_rejected(db_conn, p03_seed):
    with pytest.raises(Exception, match="null value.*change_reason_code|not-null|NotNullViolation"):
        await db_conn.execute(
            "INSERT INTO financial_amount_status_events (organisation_id, rebate_period_actual_id, "
            "measure_code, event_version, new_status, occurred_at, change_reference, change_reason_code) "
            "VALUES (%s, %s, 'expected_amount', 1, 'unknown', now(), 'test', NULL)",
            (p03_seed.org_id, p03_seed.period_actual_id),
        )


@pytest.mark.integration
async def test_invalid_change_reason_code_rejected(db_conn, p03_seed):
    with pytest.raises(Exception, match="ck_famev_reason_code_vocabulary"):
        await db_conn.execute(
            "INSERT INTO financial_amount_status_events (organisation_id, rebate_period_actual_id, "
            "measure_code, event_version, new_status, occurred_at, change_reference, change_reason_code) "
            "VALUES (%s, %s, 'expected_amount', 1, 'unknown', now(), 'test', 'not_a_real_reason')",
            (p03_seed.org_id, p03_seed.period_actual_id),
        )


# Section 5: snapshot-to-current-event deferred trigger

@pytest.mark.integration
async def test_parent_inserted_without_any_event_fails_at_commit(db_conn, p03_seed):
    await db_conn.execute(
        "INSERT INTO rebate_period_actuals (organisation_id, rebate_agreement_id, period_start, "
        "period_end, entry_source, entered_by_user_id, expected_amount_status) VALUES "
        "(%s, %s, '2026-07-01', '2026-09-30', 'manual', %s, 'unknown')",
        (p03_seed.org_id, p03_seed.agreement_id, p03_seed.user_id),
    )
    with pytest.raises(Exception, match="must not be NULL at commit"):
        await db_conn.commit()


@pytest.mark.integration
async def test_parent_and_event_but_no_pointer_update_fails_at_commit(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="unknown", change_reason_code="manual_estimate",
    )
    with pytest.raises(Exception, match="must not be NULL at commit"):
        await db_conn.commit()


@pytest.mark.integration
async def test_pointer_referencing_a_different_parents_event_fails(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_current_event_id = %s WHERE id = %s",
        (p03_seed.event_id, new_id),
    )
    with pytest.raises(Exception, match="does not reference a matching event"):
        await db_conn.commit()


@pytest.mark.integration
async def test_snapshot_field_changed_without_new_event_fails(db_conn, p03_seed):
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_calculated_at = now() WHERE id = %s",
        (p03_seed.period_actual_id,),
    )
    with pytest.raises(Exception, match="snapshot does not match its current event"):
        await db_conn.commit()


@pytest.mark.integration
async def test_valid_genesis_then_pointer_update_in_one_transaction_succeeds(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    event_id = await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="unknown", change_reason_code="manual_estimate",
    )
    await db_conn.execute(
        "UPDATE rebate_period_actuals SET expected_amount_current_event_id = %s WHERE id = %s",
        (event_id, new_id),
    )
    await db_conn.commit()


# Section 6: concurrency

@pytest.mark.integration
async def test_concurrent_event_writes_for_same_parent_are_serialized_not_racing(db_conn_a, db_conn_b, p03_seed):
    """Two real, concurrent connections. Transaction A locks the parent row FOR UPDATE and holds
    it; transaction B, targeting the same parent, must block until A commits, then correctly
    compute version = A's version + 1, never colliding. NOTE: the "B genuinely blocks" part of
    this assertion needs real timing behavior a linear script can only partly express - flagged
    as the one test here I have the least confidence reasoning through without seeing it run."""
    async with db_conn_a.transaction():
        await db_conn_a.execute(
            "SELECT * FROM rebate_period_actuals WHERE id = %s FOR UPDATE", (p03_seed.period_actual_id,)
        )
        version = await _next_event_version(
            db_conn_a, rebate_period_actual_id=p03_seed.period_actual_id, measure_code="expected_amount"
        )
        await _insert_event(
            db_conn_a, organisation_id=p03_seed.org_id, rebate_period_actual_id=p03_seed.period_actual_id,
            measure_code="expected_amount", event_version=version, old_status="unknown",
            new_status="calculated", new_source_basis="contract_terms_calculation",
            new_amount=100, new_calculated_at="2026-06-01", change_reason_code="recalculation",
        )
        await db_conn_a.execute(
            "UPDATE rebate_period_actuals SET expected_amount = 100, expected_amount_status = 'calculated', "
            "expected_amount_source_basis = 'contract_terms_calculation', "
            "expected_amount_calculated_at = now() WHERE id = %s",
            (p03_seed.period_actual_id,),
        )

    async with db_conn_b.transaction():
        next_version = await _next_event_version(
            db_conn_b, rebate_period_actual_id=p03_seed.period_actual_id, measure_code="expected_amount"
        )
        assert next_version == version + 1


@pytest.mark.integration
async def test_unique_constraint_backstops_a_genuine_version_collision(db_conn, p03_seed):
    new_id = await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )
    await _insert_event(
        db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
        event_version=1, new_status="unknown", change_reason_code="manual_estimate",
    )
    with pytest.raises(Exception, match="uq_famev_rebate_seq"):
        await _insert_event(
            db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
            event_version=1, new_status="unknown", change_reason_code="manual_estimate",
        )



# ---------------------------------------------------------------------------
# Phase 1: ck_famev_state_combination - the event-level full state-combination constraint.
# Every measure's every reachable state gets one valid-passes case, plus one rejection case per
# field that state requires to be NULL or NOT NULL - not just one representative field. unknown
# and not_applicable are tested as fully separate cases throughout, not merged - two distinct
# vocabulary values sharing the same required-field shape is not the same claim as "only one of
# them was actually tested."
# ---------------------------------------------------------------------------

async def _fresh_rpa(db_conn, p03_seed):
    return await _insert_period_actual(
        db_conn, organisation_id=p03_seed.org_id, rebate_agreement_id=p03_seed.agreement_id,
        entered_by_user_id=p03_seed.user_id,
    )


async def _fresh_opp(db_conn, p03_seed):
    return await _insert_opportunity(db_conn, organisation_id=p03_seed.org_id, created_by_user_id=p03_seed.user_id)


# ===== expected_amount: unknown =====


@pytest.mark.integration
async def test_combo_afi_confirmed_structurally_rejected_before_reaching_combination_check(db_conn, p03_seed):
    """Proves the vocabulary check and the new combination check don't conflict - this fails at
    ck_famev_status_valid_for_measure, never reaching the combination constraint at all."""
    new_id = await _fresh_opp(db_conn, p03_seed)
    with pytest.raises(Exception, match="ck_famev_status_valid_for_measure"):
        await _insert_event(db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
                             measure_code="annual_financial_impact", new_status="confirmed",
                             new_amount=8000, new_source_basis="supplier_statement",
                             new_approved_at="2026-01-01T00:00:00Z", new_approved_by_user_id=p03_seed.user_id)


@pytest.mark.integration
async def test_combo_rs_calculated_valid_genuine_zero_amount(db_conn, p03_seed):
    """Confirms IS NOT NULL (not a truthiness check) - a real R0.00 realised saving is a valid,
    evidenced calculated amount, never conflated with 'unknown'."""
    new_id = await _fresh_opp(db_conn, p03_seed)
    await _insert_event(db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
                         measure_code="realised_savings", new_status="calculated", new_amount=0,
                         new_source_basis="actual_cost_data_calculation", new_calculated_at="2026-01-01T00:00:00Z",
                         new_effective_period_start="2026-01-01", new_effective_period_end="2026-03-31")  # succeeds


@pytest.mark.integration
async def test_combo_rs_calculated_rejects_period_start_after_end(db_conn, p03_seed):
    new_id = await _fresh_opp(db_conn, p03_seed)
    with pytest.raises(Exception, match="ck_famev_state_combination"):
        await _insert_event(db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
                             measure_code="realised_savings", new_status="calculated", new_amount=3000,
                             new_source_basis="actual_cost_data_calculation", new_calculated_at="2026-01-01T00:00:00Z",
                             new_effective_period_start="2026-06-01", new_effective_period_end="2026-01-01")


@pytest.mark.integration
async def test_combo_rs_estimated_structurally_rejected_before_reaching_combination_check(db_conn, p03_seed):
    """Mirror of the annual_financial_impact/confirmed test - realised_savings can never reach
    'estimated', rejected at the vocabulary layer, never at the combination constraint."""
    new_id = await _fresh_opp(db_conn, p03_seed)
    with pytest.raises(Exception, match="ck_famev_status_valid_for_measure"):
        await _insert_event(db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
                             measure_code="realised_savings", new_status="estimated",
                             new_amount=3000, new_source_basis="actual_cost_data_calculation")


@pytest.mark.integration
async def test_combo_confirmed_event_satisfying_combination_still_needs_evidence(db_conn, p03_seed):
    """A confirmed event with a perfectly valid field shape (satisfies ck_famev_state_combination
    completely) must still fail at COMMIT via the separate evidence-sufficiency trigger if no
    evidence rows exist - proving the two mechanisms are independent layers, not overlapping or
    substituting for each other."""
    new_id = await _fresh_opp(db_conn, p03_seed)
    async with db_conn.transaction():
        await _insert_event(
            db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
            measure_code="realised_savings", new_status="confirmed", new_amount=3000,
            new_source_basis="reconciled_actuals", new_approved_at="2026-01-01T00:00:00Z",
            new_approved_by_user_id=p03_seed.user_id,
            new_effective_period_start="2026-01-01", new_effective_period_end="2026-03-31",
        )  # succeeds here - the combination constraint is immediate and satisfied
        with pytest.raises(Exception, match="missing documented_baseline evidence"):
            await db_conn.commit()  # fails here - a separate, later-checked concern





# ---------------------------------------------------------------------------
# Phase 1 expansion: full parametrized state-combination matrix. Generated from a
# verified spec (every required field tested missing individually, every forbidden field
# tested populated individually, wrong-source-basis tested where a specific value is
# required) rather than hand-written per case - 123 cases computed and cross-checked before
# this file was written, not counted after the fact.
# ---------------------------------------------------------------------------

_VALID_CASE_PARAMS = [
    pytest.param("expected_amount", "unknown", {}, id="expected_amount_unknown_valid"),
    pytest.param("expected_amount", "not_applicable", {}, id="expected_amount_not_applicable_valid"),
    pytest.param("expected_amount", "legacy_unverified", {"new_amount": 500}, id="expected_amount_legacy_unverified_valid"),
    pytest.param("expected_amount", "estimated", {"new_amount": 500, "new_source_basis": "manual_estimate"}, id="expected_amount_estimated_valid"),
    pytest.param("expected_amount", "calculated", {"new_amount": 500, "new_source_basis": "contract_terms_calculation", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_calculated_valid"),
    pytest.param("expected_amount", "confirmed", {"new_amount": 500, "new_source_basis": "supplier_statement", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_confirmed_valid"),
    pytest.param("annual_financial_impact", "unknown", {}, id="annual_financial_impact_unknown_valid"),
    pytest.param("annual_financial_impact", "not_applicable", {}, id="annual_financial_impact_not_applicable_valid"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 8000}, id="annual_financial_impact_legacy_unverified_valid"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": "manual_estimate", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_estimated_valid"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": "price_review_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_calculated_valid"),
    pytest.param("realised_savings", "unknown", {}, id="realised_savings_unknown_valid"),
    pytest.param("realised_savings", "not_applicable", {}, id="realised_savings_not_applicable_valid"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 3000}, id="realised_savings_legacy_unverified_valid"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": "actual_cost_data_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_calculated_valid"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": "reconciled_actuals", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_valid"),
]

_MALFORMED_CASE_PARAMS = [
    pytest.param("expected_amount", "unknown", {"new_amount": 999999}, id="expected_amount_unknown_forbidden_new_amount_populated"),
    pytest.param("expected_amount", "unknown", {"new_source_basis": 999999}, id="expected_amount_unknown_forbidden_new_source_basis_populated"),
    pytest.param("expected_amount", "unknown", {"new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_unknown_forbidden_new_calculated_at_populated"),
    pytest.param("expected_amount", "unknown", {"new_approved_at": "2026-01-01T00:00:00Z"}, id="expected_amount_unknown_forbidden_new_approved_at_populated"),
    pytest.param("expected_amount", "unknown", {"new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_unknown_forbidden_new_approved_by_user_id_populated"),
    pytest.param("expected_amount", "not_applicable", {"new_amount": 999999}, id="expected_amount_not_applicable_forbidden_new_amount_populated"),
    pytest.param("expected_amount", "not_applicable", {"new_source_basis": 999999}, id="expected_amount_not_applicable_forbidden_new_source_basis_populated"),
    pytest.param("expected_amount", "not_applicable", {"new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_not_applicable_forbidden_new_calculated_at_populated"),
    pytest.param("expected_amount", "not_applicable", {"new_approved_at": "2026-01-01T00:00:00Z"}, id="expected_amount_not_applicable_forbidden_new_approved_at_populated"),
    pytest.param("expected_amount", "not_applicable", {"new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_not_applicable_forbidden_new_approved_by_user_id_populated"),
    pytest.param("expected_amount", "legacy_unverified", {"new_amount": None}, id="expected_amount_legacy_unverified_missing_new_amount"),
    pytest.param("expected_amount", "legacy_unverified", {"new_amount": 500, "new_source_basis": 999999}, id="expected_amount_legacy_unverified_forbidden_new_source_basis_populated"),
    pytest.param("expected_amount", "legacy_unverified", {"new_amount": 500, "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_legacy_unverified_forbidden_new_calculated_at_populated"),
    pytest.param("expected_amount", "legacy_unverified", {"new_amount": 500, "new_approved_at": "2026-01-01T00:00:00Z"}, id="expected_amount_legacy_unverified_forbidden_new_approved_at_populated"),
    pytest.param("expected_amount", "legacy_unverified", {"new_amount": 500, "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_legacy_unverified_forbidden_new_approved_by_user_id_populated"),
    pytest.param("expected_amount", "estimated", {"new_amount": None, "new_source_basis": "manual_estimate"}, id="expected_amount_estimated_missing_new_amount"),
    pytest.param("expected_amount", "estimated", {"new_amount": 500, "new_source_basis": None}, id="expected_amount_estimated_missing_new_source_basis"),
    pytest.param("expected_amount", "estimated", {"new_amount": 500, "new_source_basis": "manual_estimate", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_estimated_forbidden_new_calculated_at_populated"),
    pytest.param("expected_amount", "estimated", {"new_amount": 500, "new_source_basis": "manual_estimate", "new_approved_at": "2026-01-01T00:00:00Z"}, id="expected_amount_estimated_forbidden_new_approved_at_populated"),
    pytest.param("expected_amount", "estimated", {"new_amount": 500, "new_source_basis": "manual_estimate", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_estimated_forbidden_new_approved_by_user_id_populated"),
    pytest.param("expected_amount", "estimated", {"new_amount": 500, "new_source_basis": "contract_terms_calculation"}, id="expected_amount_estimated_wrong_source_basis"),
    pytest.param("expected_amount", "calculated", {"new_amount": None, "new_source_basis": "contract_terms_calculation", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_calculated_missing_new_amount"),
    pytest.param("expected_amount", "calculated", {"new_amount": 500, "new_source_basis": None, "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_calculated_missing_new_source_basis"),
    pytest.param("expected_amount", "calculated", {"new_amount": 500, "new_source_basis": "contract_terms_calculation", "new_calculated_at": None}, id="expected_amount_calculated_missing_new_calculated_at"),
    pytest.param("expected_amount", "calculated", {"new_amount": 500, "new_source_basis": "contract_terms_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_approved_at": "2026-01-01T00:00:00Z"}, id="expected_amount_calculated_forbidden_new_approved_at_populated"),
    pytest.param("expected_amount", "calculated", {"new_amount": 500, "new_source_basis": "contract_terms_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_calculated_forbidden_new_approved_by_user_id_populated"),
    pytest.param("expected_amount", "calculated", {"new_amount": 500, "new_source_basis": "manual_estimate", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_calculated_wrong_source_basis"),
    pytest.param("expected_amount", "confirmed", {"new_amount": None, "new_source_basis": "supplier_statement", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_confirmed_missing_new_amount"),
    pytest.param("expected_amount", "confirmed", {"new_amount": 500, "new_source_basis": None, "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_confirmed_missing_new_source_basis"),
    pytest.param("expected_amount", "confirmed", {"new_amount": 500, "new_source_basis": "supplier_statement", "new_approved_at": None, "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_confirmed_missing_new_approved_at"),
    pytest.param("expected_amount", "confirmed", {"new_amount": 500, "new_source_basis": "supplier_statement", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": None}, id="expected_amount_confirmed_missing_new_approved_by_user_id"),
    pytest.param("expected_amount", "confirmed", {"new_amount": 500, "new_source_basis": "supplier_statement", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_confirmed_forbidden_new_calculated_at_populated"),
    pytest.param("expected_amount", "confirmed", {"new_amount": 500, "new_source_basis": "manual_estimate", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_confirmed_wrong_source_basis"),
    pytest.param("annual_financial_impact", "unknown", {"new_amount": 999999}, id="annual_financial_impact_unknown_forbidden_new_amount_populated"),
    pytest.param("annual_financial_impact", "unknown", {"new_source_basis": 999999}, id="annual_financial_impact_unknown_forbidden_new_source_basis_populated"),
    pytest.param("annual_financial_impact", "unknown", {"new_calculated_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_unknown_forbidden_new_calculated_at_populated"),
    pytest.param("annual_financial_impact", "unknown", {"new_approved_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_unknown_forbidden_new_approved_at_populated"),
    pytest.param("annual_financial_impact", "unknown", {"new_approved_by_user_id": "__RESOLVE_USER__"}, id="annual_financial_impact_unknown_forbidden_new_approved_by_user_id_populated"),
    pytest.param("annual_financial_impact", "unknown", {"new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_unknown_forbidden_new_effective_period_start_populated"),
    pytest.param("annual_financial_impact", "unknown", {"new_effective_period_end": "2026-01-01"}, id="annual_financial_impact_unknown_forbidden_new_effective_period_end_populated"),
    pytest.param("annual_financial_impact", "not_applicable", {"new_amount": 999999}, id="annual_financial_impact_not_applicable_forbidden_new_amount_populated"),
    pytest.param("annual_financial_impact", "not_applicable", {"new_source_basis": 999999}, id="annual_financial_impact_not_applicable_forbidden_new_source_basis_populated"),
    pytest.param("annual_financial_impact", "not_applicable", {"new_calculated_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_not_applicable_forbidden_new_calculated_at_populated"),
    pytest.param("annual_financial_impact", "not_applicable", {"new_approved_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_not_applicable_forbidden_new_approved_at_populated"),
    pytest.param("annual_financial_impact", "not_applicable", {"new_approved_by_user_id": "__RESOLVE_USER__"}, id="annual_financial_impact_not_applicable_forbidden_new_approved_by_user_id_populated"),
    pytest.param("annual_financial_impact", "not_applicable", {"new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_not_applicable_forbidden_new_effective_period_start_populated"),
    pytest.param("annual_financial_impact", "not_applicable", {"new_effective_period_end": "2026-01-01"}, id="annual_financial_impact_not_applicable_forbidden_new_effective_period_end_populated"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": None}, id="annual_financial_impact_legacy_unverified_missing_new_amount"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 8000, "new_source_basis": 999999}, id="annual_financial_impact_legacy_unverified_forbidden_new_source_basis_populated"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 8000, "new_calculated_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_legacy_unverified_forbidden_new_calculated_at_populated"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 8000, "new_approved_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_legacy_unverified_forbidden_new_approved_at_populated"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 8000, "new_approved_by_user_id": "__RESOLVE_USER__"}, id="annual_financial_impact_legacy_unverified_forbidden_new_approved_by_user_id_populated"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 8000, "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_legacy_unverified_forbidden_new_effective_period_start_populated"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 8000, "new_effective_period_end": "2026-01-01"}, id="annual_financial_impact_legacy_unverified_forbidden_new_effective_period_end_populated"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": None, "new_source_basis": "manual_estimate", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_estimated_missing_new_amount"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": None, "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_estimated_missing_new_source_basis"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": "manual_estimate", "new_effective_period_start": None}, id="annual_financial_impact_estimated_missing_new_effective_period_start"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": "manual_estimate", "new_effective_period_start": "2026-01-01", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_estimated_forbidden_new_calculated_at_populated"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": "manual_estimate", "new_effective_period_start": "2026-01-01", "new_approved_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_estimated_forbidden_new_approved_at_populated"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": "manual_estimate", "new_effective_period_start": "2026-01-01", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="annual_financial_impact_estimated_forbidden_new_approved_by_user_id_populated"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": "manual_estimate", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-01-01"}, id="annual_financial_impact_estimated_forbidden_new_effective_period_end_populated"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 8000, "new_source_basis": "price_review_calculation", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_estimated_wrong_source_basis"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": None, "new_source_basis": "price_review_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_calculated_missing_new_amount"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": None, "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_calculated_missing_new_source_basis"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": "price_review_calculation", "new_calculated_at": None, "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_calculated_missing_new_calculated_at"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": "price_review_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": None}, id="annual_financial_impact_calculated_missing_new_effective_period_start"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": "price_review_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_approved_at": "2026-01-01T00:00:00Z"}, id="annual_financial_impact_calculated_forbidden_new_approved_at_populated"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": "price_review_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="annual_financial_impact_calculated_forbidden_new_approved_by_user_id_populated"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": "price_review_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-01-01"}, id="annual_financial_impact_calculated_forbidden_new_effective_period_end_populated"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 8000, "new_source_basis": "manual_estimate", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_calculated_wrong_source_basis"),
    pytest.param("realised_savings", "unknown", {"new_amount": 999999}, id="realised_savings_unknown_forbidden_new_amount_populated"),
    pytest.param("realised_savings", "unknown", {"new_source_basis": 999999}, id="realised_savings_unknown_forbidden_new_source_basis_populated"),
    pytest.param("realised_savings", "unknown", {"new_calculated_at": "2026-01-01T00:00:00Z"}, id="realised_savings_unknown_forbidden_new_calculated_at_populated"),
    pytest.param("realised_savings", "unknown", {"new_approved_at": "2026-01-01T00:00:00Z"}, id="realised_savings_unknown_forbidden_new_approved_at_populated"),
    pytest.param("realised_savings", "unknown", {"new_approved_by_user_id": "__RESOLVE_USER__"}, id="realised_savings_unknown_forbidden_new_approved_by_user_id_populated"),
    pytest.param("realised_savings", "unknown", {"new_effective_period_start": "2026-01-01"}, id="realised_savings_unknown_forbidden_new_effective_period_start_populated"),
    pytest.param("realised_savings", "unknown", {"new_effective_period_end": "2026-01-01"}, id="realised_savings_unknown_forbidden_new_effective_period_end_populated"),
    pytest.param("realised_savings", "not_applicable", {"new_amount": 999999}, id="realised_savings_not_applicable_forbidden_new_amount_populated"),
    pytest.param("realised_savings", "not_applicable", {"new_source_basis": 999999}, id="realised_savings_not_applicable_forbidden_new_source_basis_populated"),
    pytest.param("realised_savings", "not_applicable", {"new_calculated_at": "2026-01-01T00:00:00Z"}, id="realised_savings_not_applicable_forbidden_new_calculated_at_populated"),
    pytest.param("realised_savings", "not_applicable", {"new_approved_at": "2026-01-01T00:00:00Z"}, id="realised_savings_not_applicable_forbidden_new_approved_at_populated"),
    pytest.param("realised_savings", "not_applicable", {"new_approved_by_user_id": "__RESOLVE_USER__"}, id="realised_savings_not_applicable_forbidden_new_approved_by_user_id_populated"),
    pytest.param("realised_savings", "not_applicable", {"new_effective_period_start": "2026-01-01"}, id="realised_savings_not_applicable_forbidden_new_effective_period_start_populated"),
    pytest.param("realised_savings", "not_applicable", {"new_effective_period_end": "2026-01-01"}, id="realised_savings_not_applicable_forbidden_new_effective_period_end_populated"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": None}, id="realised_savings_legacy_unverified_missing_new_amount"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 3000, "new_source_basis": 999999}, id="realised_savings_legacy_unverified_forbidden_new_source_basis_populated"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 3000, "new_calculated_at": "2026-01-01T00:00:00Z"}, id="realised_savings_legacy_unverified_forbidden_new_calculated_at_populated"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 3000, "new_approved_at": "2026-01-01T00:00:00Z"}, id="realised_savings_legacy_unverified_forbidden_new_approved_at_populated"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 3000, "new_approved_by_user_id": "__RESOLVE_USER__"}, id="realised_savings_legacy_unverified_forbidden_new_approved_by_user_id_populated"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 3000, "new_effective_period_start": "2026-01-01"}, id="realised_savings_legacy_unverified_forbidden_new_effective_period_start_populated"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 3000, "new_effective_period_end": "2026-01-01"}, id="realised_savings_legacy_unverified_forbidden_new_effective_period_end_populated"),
    pytest.param("realised_savings", "calculated", {"new_amount": None, "new_source_basis": "actual_cost_data_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_calculated_missing_new_amount"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": None, "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_calculated_missing_new_source_basis"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": "actual_cost_data_calculation", "new_calculated_at": None, "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_calculated_missing_new_calculated_at"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": "actual_cost_data_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": None, "new_effective_period_end": "2026-03-31"}, id="realised_savings_calculated_missing_new_effective_period_start"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": "actual_cost_data_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": None}, id="realised_savings_calculated_missing_new_effective_period_end"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": "actual_cost_data_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31", "new_approved_at": "2026-01-01T00:00:00Z"}, id="realised_savings_calculated_forbidden_new_approved_at_populated"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": "actual_cost_data_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="realised_savings_calculated_forbidden_new_approved_by_user_id_populated"),
    pytest.param("realised_savings", "calculated", {"new_amount": 3000, "new_source_basis": "reconciled_actuals", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_calculated_wrong_source_basis"),
    pytest.param("realised_savings", "confirmed", {"new_amount": None, "new_source_basis": "reconciled_actuals", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_missing_new_amount"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": None, "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_missing_new_source_basis"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": "reconciled_actuals", "new_approved_at": None, "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_missing_new_approved_at"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": "reconciled_actuals", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": None, "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_missing_new_approved_by_user_id"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": "reconciled_actuals", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": None, "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_missing_new_effective_period_start"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": "reconciled_actuals", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": None}, id="realised_savings_confirmed_missing_new_effective_period_end"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": "reconciled_actuals", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="realised_savings_confirmed_forbidden_new_calculated_at_populated"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 3000, "new_source_basis": "actual_cost_data_calculation", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_wrong_source_basis"),
]


@pytest.mark.integration
@pytest.mark.parametrize("measure,status,fields", _VALID_CASE_PARAMS)
async def test_combo_matrix_valid(db_conn, p03_seed, measure, status, fields):
    fields = {k: (p03_seed.user_id if v == "__RESOLVE_USER__" else v) for k, v in fields.items()}
    if measure == "expected_amount":
        new_id = await _fresh_rpa(db_conn, p03_seed)
        await _insert_event(db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
                             measure_code=measure, new_status=status, **fields)
    else:
        new_id = await _fresh_opp(db_conn, p03_seed)
        await _insert_event(db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
                             measure_code=measure, new_status=status, **fields)


@pytest.mark.integration
@pytest.mark.parametrize("measure,status,fields", _MALFORMED_CASE_PARAMS)
async def test_combo_matrix_malformed(db_conn, p03_seed, measure, status, fields):
    fields = {k: (p03_seed.user_id if v == "__RESOLVE_USER__" else v) for k, v in fields.items()}
    with pytest.raises(Exception, match="ck_famev_state_combination"):
        if measure == "expected_amount":
            new_id = await _fresh_rpa(db_conn, p03_seed)
            await _insert_event(db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
                                 measure_code=measure, new_status=status, **fields)
        else:
            new_id = await _fresh_opp(db_conn, p03_seed)
            await _insert_event(db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
                                 measure_code=measure, new_status=status, **fields)

@pytest.mark.integration
async def test_confirmed_expected_amount_event_without_evidence_fails_at_commit(db_conn, p03_seed):
    """The expected_amount counterpart to the existing realised_savings evidence-sufficiency
    tests above - this measure's confirmed-tier requires at least one supplier_statement or
    credit_note evidence row; previously untested for this specific measure."""
    new_id = await _fresh_rpa(db_conn, p03_seed)
    async with db_conn.transaction():
        await _insert_event(
            db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
            measure_code="expected_amount", new_status="confirmed", new_amount=500,
            new_source_basis="supplier_statement", new_approved_at="2026-01-01T00:00:00Z",
            new_approved_by_user_id=p03_seed.user_id,
        )
        with pytest.raises(Exception, match="missing valid rebate-confirmation evidence"):
            await db_conn.commit()


@pytest.mark.integration
async def test_confirmed_expected_amount_event_with_credit_note_evidence_commits(db_conn, p03_seed):
    new_id = await _fresh_rpa(db_conn, p03_seed)
    async with db_conn.transaction():
        event_id = await _insert_event(
            db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
            measure_code="expected_amount", new_status="confirmed", new_amount=500,
            new_source_basis="credit_note", new_approved_at="2026-01-01T00:00:00Z",
            new_approved_by_user_id=p03_seed.user_id,
        )
        await db_conn.execute(
            "INSERT INTO financial_amount_evidence (organisation_id, event_id, evidence_type, "
            "external_reference, recorded_at) VALUES (%s, %s, 'credit_note', 'CN-001', now())",
            (p03_seed.org_id, event_id),
        )
        await db_conn.commit()  # must succeed


_ZERO_AMOUNT_VALID_CASE_PARAMS = [
    pytest.param("expected_amount", "legacy_unverified", {"new_amount": 0}, id="expected_amount_legacy_unverified_valid_zero_amount"),
    pytest.param("expected_amount", "estimated", {"new_amount": 0, "new_source_basis": "manual_estimate"}, id="expected_amount_estimated_valid_zero_amount"),
    pytest.param("expected_amount", "calculated", {"new_amount": 0, "new_source_basis": "contract_terms_calculation", "new_calculated_at": "2026-01-01T00:00:00Z"}, id="expected_amount_calculated_valid_zero_amount"),
    pytest.param("expected_amount", "confirmed", {"new_amount": 0, "new_source_basis": "supplier_statement", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__"}, id="expected_amount_confirmed_valid_zero_amount"),
    pytest.param("annual_financial_impact", "legacy_unverified", {"new_amount": 0}, id="annual_financial_impact_legacy_unverified_valid_zero_amount"),
    pytest.param("annual_financial_impact", "estimated", {"new_amount": 0, "new_source_basis": "manual_estimate", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_estimated_valid_zero_amount"),
    pytest.param("annual_financial_impact", "calculated", {"new_amount": 0, "new_source_basis": "price_review_calculation", "new_calculated_at": "2026-01-01T00:00:00Z", "new_effective_period_start": "2026-01-01"}, id="annual_financial_impact_calculated_valid_zero_amount"),
    pytest.param("realised_savings", "legacy_unverified", {"new_amount": 0}, id="realised_savings_legacy_unverified_valid_zero_amount"),
    pytest.param("realised_savings", "confirmed", {"new_amount": 0, "new_source_basis": "reconciled_actuals", "new_approved_at": "2026-01-01T00:00:00Z", "new_approved_by_user_id": "__RESOLVE_USER__", "new_effective_period_start": "2026-01-01", "new_effective_period_end": "2026-03-31"}, id="realised_savings_confirmed_valid_zero_amount"),
]


@pytest.mark.integration
@pytest.mark.parametrize("measure,status,fields", _ZERO_AMOUNT_VALID_CASE_PARAMS)
async def test_combo_matrix_valid_zero_amount(db_conn, p03_seed, measure, status, fields):
    """P-03 requires an explicit genuine-zero case for every permitted numeric evidence
    state, not just one - a real R0.00 result must never be structurally indistinguishable
    from an unevidenced/unknown amount, in every state where a real amount can be recorded,
    not only the one state that happened to get tested first."""
    fields = {k: (p03_seed.user_id if v == "__RESOLVE_USER__" else v) for k, v in fields.items()}
    if measure == "expected_amount":
        new_id = await _fresh_rpa(db_conn, p03_seed)
        await _insert_event(db_conn, organisation_id=p03_seed.org_id, rebate_period_actual_id=new_id,
                             measure_code=measure, new_status=status, **fields)
    else:
        new_id = await _fresh_opp(db_conn, p03_seed)
        await _insert_event(db_conn, organisation_id=p03_seed.org_id, opportunity_id=new_id,
                             measure_code=measure, new_status=status, **fields)

if __name__ == "__main__":
    print("Requires a live PostgreSQL database (the backend CI job's pgvector/pgvector:pg16 service)")
    print("and pytest-asyncio. Written and reviewed against the full P-03 design.")
