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
        # period-lock query is scoped per-organisation, not global.
        snapshot_b = await ingest_working_capital_snapshot(
            db_session, organisation_id=org_b, user_id=user_b, as_of_date=date(2026, 8, 31),
            accounts_receivable=Decimal("999999"), accounts_payable=Decimal("1"),
            inventory_value=Decimal("1"), cash_balance=Decimal("1"),
            annualized_revenue=Decimal("1"), annualized_cogs=Decimal("1"),
        )
        assert snapshot_b.corrects_id is None
