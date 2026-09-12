"""
Tests for app.services.working_capital_service - period-locking (ConflictError on re-ingest
without is_correction, corrects_id on is_correction=True) and organisation-scoping of the
period-lock query. Same live-Postgres requirement as every other file in backend/tests/ -
written, not executed (no live Postgres, no pytest install, both constraints unchanged all
sprint).

Calls the service directly via the db_session fixture rather than through an HTTP route, since no
ingestion API route exists yet for these two tables (this phase is the service/pipeline layer
only - a route is a separate, later piece of work).
"""
from decimal import Decimal
from datetime import date

import pytest

from app.core.exceptions import ConflictError, ValidationFailedError
from app.core.security import decode_access_token
from app.services.working_capital_service import ingest_aging_snapshot, ingest_working_capital_snapshot


async def _register_org(client, email: str, org_name: str) -> tuple[str, int, int]:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    token = resp.json()["access_token"]
    # /auth/register's response only returns organisation_public_id (a UUID) - the service
    # functions below need the real internal integer ids, which the token itself already carries
    # as active_org_id/user_id. Decoding it here is more direct than a separate DB lookup.
    claims = decode_access_token(token)
    return token, claims.active_org_id, claims.user_id


class TestWorkingCapitalPeriodLocking:
    async def test_fresh_period_ingests_successfully_with_real_gourmet_figures(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "wc-fresh@example.com", "WC Fresh Org")
        snapshot = await ingest_working_capital_snapshot(
            db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("31596977.24"), accounts_payable=Decimal("23532821.46"),
            inventory_value=Decimal("21895070.82"), cash_balance=Decimal("-19518395.79"),
            annualized_revenue=Decimal("355848477.03"), annualized_cogs=Decimal("290075966.07"),
        )
        assert snapshot.corrects_id is None
        assert snapshot.dso is not None  # confirms calculate_working_capital_metrics actually ran
        # WC-DERIVED-METRIC-DIAGNOSTICS-R1: a normal, representable snapshot persists an empty
        # list - "evaluated, nothing to report" - never NULL (that means "never evaluated").
        assert snapshot.derived_metric_diagnostics == []

    async def test_reingesting_same_period_without_correction_flag_raises_conflict(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "wc-conflict@example.com", "WC Conflict Org")
        kwargs = dict(
            organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("100000"), accounts_payable=Decimal("50000"),
            inventory_value=Decimal("30000"), cash_balance=Decimal("10000"),
            annualized_revenue=Decimal("1000000"), annualized_cogs=Decimal("700000"),
        )
        await ingest_working_capital_snapshot(db_session, **kwargs)
        with pytest.raises(ConflictError):
            await ingest_working_capital_snapshot(db_session, **kwargs)

    async def test_correction_flag_creates_new_row_referencing_the_prior_one(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "wc-correction@example.com", "WC Correction Org")
        kwargs = dict(
            organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("100000"), accounts_payable=Decimal("50000"),
            inventory_value=Decimal("30000"), cash_balance=Decimal("10000"),
            annualized_revenue=Decimal("1000000"), annualized_cogs=Decimal("700000"),
        )
        original = await ingest_working_capital_snapshot(db_session, **kwargs)
        corrected_kwargs = {**kwargs, "accounts_receivable": Decimal("105000")}
        corrected = await ingest_working_capital_snapshot(db_session, is_correction=True, **corrected_kwargs)
        assert corrected.corrects_id == original.id
        assert corrected.id != original.id


class TestAgingPeriodLocking:
    async def test_fresh_debtors_and_creditors_for_same_date_do_not_conflict(self, client, db_session):
        # debtors and creditors are independent ledger_types - ingesting both for the same date
        # must never conflict with each other, only within the same ledger_type.
        _, org_id, user_id = await _register_org(client, "aging-both@example.com", "Aging Both Org")
        invoices = [{"amount": Decimal("1000"), "days_overdue": 10}]
        debtors = await ingest_aging_snapshot(
            db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            ledger_type="debtors", invoices=invoices,
        )
        creditors = await ingest_aging_snapshot(
            db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            ledger_type="creditors", invoices=invoices,
        )
        assert debtors.id != creditors.id
        assert debtors.corrects_id is None and creditors.corrects_id is None

    async def test_reingesting_same_ledger_type_and_date_without_correction_raises(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "aging-conflict@example.com", "Aging Conflict Org")
        kwargs = dict(
            organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            ledger_type="debtors", invoices=[{"amount": Decimal("1000"), "days_overdue": 10}],
        )
        await ingest_aging_snapshot(db_session, **kwargs)
        with pytest.raises(ConflictError):
            await ingest_aging_snapshot(db_session, **kwargs)

    async def test_unrecognized_ledger_type_raises_validation_error(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "aging-badtype@example.com", "Aging Bad Type Org")
        with pytest.raises(ValidationFailedError):
            await ingest_aging_snapshot(
                db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
                ledger_type="not_a_real_ledger_type", invoices=[],
            )

    async def test_buckets_computed_via_the_real_pure_function_not_reimplemented(self, client, db_session):
        # Locks in that this service calls classify_aging_buckets rather than a second,
        # independently-written bucket calculation - the exact real worked totals from that
        # function's own test suite, re-verified here at the service boundary.
        _, org_id, user_id = await _register_org(client, "aging-buckets@example.com", "Aging Buckets Org")
        snapshot = await ingest_aging_snapshot(
            db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            ledger_type="debtors",
            invoices=[
                {"amount": Decimal("200000"), "days_overdue": 10}, {"amount": Decimal("150000"), "days_overdue": 35},
                {"amount": Decimal("100000"), "days_overdue": 65}, {"amount": Decimal("50000"), "days_overdue": 95},
                {"amount": Decimal("25000"), "days_overdue": 130},
            ],
        )
        assert snapshot.current_balance == Decimal("200000.0000")
        assert snapshot.days_30 == Decimal("150000.0000")
        assert snapshot.days_120_plus == Decimal("25000.0000")


class TestPeriodLockIsOrganisationScoped:
    """
    Named precisely, not as 'RLS isolation': db_session connects via the admin/table-owner URL
    (get_settings().database_url), which bypasses Postgres RLS entirely regardless of FORCE ROW
    LEVEL SECURITY - that's the whole point of ADR-011's procureiq_app role existing as a
    separate, non-owner connection. This class tests that the service's own WHERE
    organisation_id == ... clause correctly scopes the period-lock query per organisation - a
    real, valuable property, but an application-layer one, not proof that Postgres RLS itself
    would block a cross-tenant read if that WHERE clause were ever accidentally omitted.
    """

    async def test_working_capital_period_lock_is_scoped_to_its_own_organisation(self, client, db_session):
        _, org_a, user_a = await _register_org(client, "wc-scope-a@example.com", "WC Scope Org A")
        _, org_b, user_b = await _register_org(client, "wc-scope-b@example.com", "WC Scope Org B")
        await ingest_working_capital_snapshot(
            db_session, organisation_id=org_a, user_id=user_a, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("100000"), accounts_payable=Decimal("50000"),
            inventory_value=Decimal("30000"), cash_balance=Decimal("10000"),
            annualized_revenue=Decimal("1000000"), annualized_cogs=Decimal("700000"),
        )
        # Org B ingesting for the SAME date must not conflict with Org A's snapshot - the
        # period-lock query is scoped per-organisation, not global. Realistic, dimensionally
        # consistent figures (WORKING-CAPITAL-PRECISION-R1/WC-DERIVED-METRIC-DIAGNOSTICS-R1): a
        # smaller but genuine business's balance sheet, not the prior degenerate
        # annualized_revenue=1 payload that produced a ~365-million-day DSO unrelated to what
        # this test actually proves (organisation scoping, not derived-metric magnitude).
        snapshot_b = await ingest_working_capital_snapshot(
            db_session, organisation_id=org_b, user_id=user_b, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("120000"), accounts_payable=Decimal("60000"),
            inventory_value=Decimal("40000"), cash_balance=Decimal("15000"),
            annualized_revenue=Decimal("900000"), annualized_cogs=Decimal("650000"),
        )
        assert snapshot_b.corrects_id is None
        assert snapshot_b.derived_metric_diagnostics == []  # realistic inputs - nothing to diagnose


class TestDerivedMetricStorageBoundary:
    """
    WC-DERIVED-METRIC-DIAGNOSTICS-R1: working_capital_snapshots.dso/dio/dpo/ccc are Numeric(9, 1) -
    at most 99999999.9 in magnitude. A genuinely non-zero but near-zero annualized_revenue/
    annualized_cogs denominator against a normal balance produces an arithmetically exact but
    unstorable result (WORKING-CAPITAL-PRECISION-R1's original reproduction: accounts_receivable=
    999999 against annualized_revenue=1 -> dso = ccc = 364999635.0 days). This class proves that
    case is now diagnosed, not a raw asyncpg.exceptions.NumericValueOutOfRangeError.
    """

    async def test_extreme_denominator_no_longer_raises_and_is_diagnosed(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "wc-extreme@example.com", "WC Extreme Org")
        # The exact degenerate payload that previously raised NumericValueOutOfRangeError.
        snapshot = await ingest_working_capital_snapshot(
            db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("999999"), accounts_payable=Decimal("1"),
            inventory_value=Decimal("1"), cash_balance=Decimal("1"),
            annualized_revenue=Decimal("1"), annualized_cogs=Decimal("1"),
        )
        # The affected metric is null - never zero, capped, or coerced.
        assert snapshot.dso is None
        # DIO/DPO were genuinely representable (365.0 each) and are persisted unchanged - a
        # different metric being out of range must not null out ones that are fine.
        assert snapshot.dio == Decimal("365.0")
        assert snapshot.dpo == Decimal("365.0")
        # CCC depends on dso, which is unavailable - null, never a partial/silently-computed value.
        assert snapshot.ccc is None
        assert snapshot.derived_metric_diagnostics == ["dso_out_of_range", "ccc_unavailable_dso_out_of_range"]
        # Every accepted raw source fact is preserved exactly as submitted.
        assert snapshot.accounts_receivable == Decimal("999999.0000")
        assert snapshot.accounts_payable == Decimal("1.0000")
        assert snapshot.inventory_value == Decimal("1.0000")
        assert snapshot.cash_balance == Decimal("1.0000")
        assert snapshot.annualized_revenue == Decimal("1.0000")
        assert snapshot.annualized_cogs == Decimal("1.0000")

    async def test_zero_denominator_ccc_unavailable_carries_no_out_of_range_diagnostic(self, client, db_session):
        """Distinguishes the pre-existing, already-correct zero-denominator None (§3.2 - never a
        fabricated 0 or 365) from this phase's new out-of-range handling: annualized_revenue=0
        makes dso None for an entirely different, pre-existing reason, and must not be reported
        as if it were newly out-of-range."""
        _, org_id, user_id = await _register_org(client, "wc-zero-rev@example.com", "WC Zero Revenue Org")
        snapshot = await ingest_working_capital_snapshot(
            db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("50000"), accounts_payable=Decimal("20000"),
            inventory_value=Decimal("10000"), cash_balance=Decimal("5000"),
            annualized_revenue=Decimal("0"), annualized_cogs=Decimal("400000"),
        )
        assert snapshot.dso is None  # zero denominator - pre-existing, unchanged behaviour
        assert snapshot.dio is not None
        assert snapshot.dpo is not None
        assert snapshot.ccc is None  # dso unavailable -> ccc unavailable, unchanged behaviour
        # No diagnostic at all - this is the existing, already-correct zero-denominator case, not
        # a new out-of-range condition this phase introduces handling for.
        assert snapshot.derived_metric_diagnostics == []

    async def test_zero_cogs_never_fabricates_zero_days(self, client, db_session):
        """Preserves existing handling: a zero/missing COGS denominator makes DIO/DPO/CCC None,
        never 0 - re-verified unchanged after this phase's storage-boundary guard was added."""
        _, org_id, user_id = await _register_org(client, "wc-zero-cogs@example.com", "WC Zero COGS Org")
        snapshot = await ingest_working_capital_snapshot(
            db_session, organisation_id=org_id, user_id=user_id, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("50000"), accounts_payable=Decimal("20000"),
            inventory_value=Decimal("10000"), cash_balance=Decimal("5000"),
            annualized_revenue=Decimal("400000"), annualized_cogs=Decimal("0"),
        )
        assert snapshot.dio is None
        assert snapshot.dpo is None
        assert snapshot.ccc is None
        assert snapshot.dso is not None  # unaffected - its own denominator (revenue) was fine
        assert snapshot.derived_metric_diagnostics == []
