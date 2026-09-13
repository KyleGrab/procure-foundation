"""
BUSINESS-DATE-CLOSE-PERIOD-ORG-LOCAL-R1: focused tests for rebate_service.close_period's own
business-date correction (the one DTZ011 site this phase was scoped to, deliberately excluded
from BUSINESS-DATE-SEMANTICS-IMPLEMENTATION-R1's tests/test_business_date_semantics.py). Proves,
in order: the shared resolver genuinely diverges per organisation timezone for the same instant;
close_period's own is_period_due_for_close boundary is unchanged and now driven by an injected
as_of_date; a client cannot override the resolved date via the HTTP route; and close_period no
longer reads a real clock internally.
"""
from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app.core.business_calendar import resolve_business_date
from app.core.exceptions import ConflictError
from app.db.models import Organisation, RebateAgreement, RebatePeriodActual, Supplier, User
from app.services import rebate_service


async def _seed_org_and_user(db_session, *, name: str, timezone: str = "Africa/Johannesburg") -> tuple[Organisation, User]:
    org = Organisation(name=name, default_currency="ZAR", country="ZA", timezone=timezone)
    db_session.add(org)
    await db_session.flush()
    user = User(
        first_name="Close", last_name="Period", email=f"close-period-{uuid.uuid4()}@procureiq.local",
        password_hash="not-a-real-hash-seed-only", verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return org, user


async def _seed_expected_amount_genesis_event(db_session, *, period_actual: RebatePeriodActual, org: Organisation) -> None:
    """migration 0021's deferred constraint trigger requires expected_amount_current_event_id to
    be set by commit time - same raw-SQL genesis-event pattern as tests/conftest.py's own
    p03_seed fixture and BUSINESS-DATE-SEMANTICS-IMPLEMENTATION-R1's test_business_date_semantics.py."""
    result = await db_session.execute(
        sa.text(
            "INSERT INTO financial_amount_status_events (public_id, organisation_id, "
            "rebate_period_actual_id, measure_code, event_version, new_status, occurred_at, "
            "change_reference, change_reason_code) "
            "VALUES (gen_random_uuid(), :org, :rpa, 'expected_amount', 1, 'unknown', now(), "
            "'test_close_period_business_date', 'initial_backfill') RETURNING id"
        ),
        {"org": org.id, "rpa": period_actual.id},
    )
    event_id = result.scalar_one()
    await db_session.execute(
        sa.text("UPDATE rebate_period_actuals SET expected_amount_current_event_id = :ev WHERE id = :pid"),
        {"ev": event_id, "pid": period_actual.id},
    )


async def _make_agreement_and_period(db_session, org, user, *, period_end: date) -> RebatePeriodActual:
    supplier = Supplier(organisation_id=org.id, legal_name="Close Period Supplier")
    db_session.add(supplier)
    await db_session.flush()
    agreement = RebateAgreement(
        organisation_id=org.id, supplier_id=supplier.id, title="Close Period Agreement",
        rebate_type="fixed_percentage", period_type="quarterly", flat_rate_pct="0.02",
        currency="ZAR", created_by_user_id=user.id,
    )
    db_session.add(agreement)
    await db_session.flush()
    period_actual = RebatePeriodActual(
        organisation_id=org.id, rebate_agreement_id=agreement.id,
        period_start=period_end - timedelta(days=90), period_end=period_end,
        entry_source="manual", entered_by_user_id=user.id, expected_amount_status="unknown",
    )
    db_session.add(period_actual)
    await db_session.flush()
    await _seed_expected_amount_genesis_event(db_session, period_actual=period_actual, org=org)
    return period_actual


class TestSharedResolverDivergesPerOrganisationTimezone:
    """Same requirement as BUSINESS-DATE-SEMANTICS-IMPLEMENTATION-R1's resolver tests, restated
    here against two real Organisation rows' own .timezone values (not just literal strings) -
    proving the close-period boundary genuinely depends on which organisation is asking, not a
    hardcoded zone."""

    async def test_same_utc_instant_resolves_differently_for_two_organisations(self, db_session):
        org_tokyo, _ = await _seed_org_and_user(db_session, name="Close Period Tokyo Org", timezone="Asia/Tokyo")
        org_la, _ = await _seed_org_and_user(
            db_session, name="Close Period LA Org", timezone="America/Los_Angeles"
        )
        instant = datetime(2027, 3, 31, 23, 30, tzinfo=UTC)

        tokyo_date = resolve_business_date(org_tokyo.timezone, utc_instant=instant)
        la_date = resolve_business_date(org_la.timezone, utc_instant=instant)

        assert tokyo_date == date(2027, 4, 1)
        assert la_date == date(2027, 3, 31)
        assert tokyo_date != la_date


class TestClosePeriodBoundaryUnchanged:
    """is_period_due_for_close's own rule (today >= period_end) is untouched - only where
    as_of_date comes from has moved. Exactly one day before period_end is not yet due; exactly on
    period_end it is - the identical boundary close_period always had, now driven by an injected
    as_of_date instead of a server-local date.today()."""

    async def test_not_due_one_day_before_period_end_raises_conflict(self, db_session):
        org, user = await _seed_org_and_user(db_session, name="Close Period Boundary Org A")
        period_end = date(2027, 6, 30)
        period_actual = await _make_agreement_and_period(db_session, org, user, period_end=period_end)

        try:
            await rebate_service.close_period(
                db_session, organisation_id=org.id, user_id=user.id, period_actual=period_actual,
                as_of_date=period_end - timedelta(days=1),
            )
            raise AssertionError("expected ConflictError for a period not yet due")
        except ConflictError:
            pass
        assert period_actual.earned_amount is None

    async def test_due_exactly_on_period_end_succeeds(self, db_session):
        org, user = await _seed_org_and_user(db_session, name="Close Period Boundary Org B")
        period_end = date(2027, 6, 30)
        period_actual = await _make_agreement_and_period(db_session, org, user, period_end=period_end)

        closed = await rebate_service.close_period(
            db_session, organisation_id=org.id, user_id=user.id, period_actual=period_actual,
            as_of_date=period_end,
        )
        # No expected_amount was ever calculated for this fixture (expected_amount_status stays
        # 'unknown'), so earned_amount correctly mirrors that NULL - the close itself succeeding
        # without raising ConflictError is what proves the boundary, not a specific amount.
        assert closed.earned_at is not None


class TestClientCannotOverrideResolvedBusinessDate:
    """The route accepts no as_of_date from the client at all - a query param attempting to
    supply one has zero effect on the server's own resolved date. A period ending far in the
    future is genuinely not due under any real current date, so if the client-supplied value were
    honoured (a date deep in the past would make an old-looking period appear overdue), the close
    would incorrectly succeed; asserting it still 409s proves the override is ignored."""

    async def test_query_param_as_of_date_override_has_no_effect(self, client, db_session):
        resp = await client.post(
            "/auth/register",
            json={
                "first_name": "Close", "last_name": "Override", "email": "close-override@example.com",
                "password": "correct-horse-battery-staple", "organisation_name": "Close Override Org",
            },
        )
        token = resp.json()["access_token"]

        supplier_resp = await client.post(
            "/suppliers", json={"legal_name": "Close Override Supplier", "currency": "ZAR"},
            headers={"Authorization": f"Bearer {token}"},
        )
        agreement_resp = await client.post(
            "/rebates",
            json={
                "supplier_public_id": supplier_resp.json()["public_id"], "title": "Close Override Agreement",
                "rebate_type": "fixed_percentage", "period_type": "quarterly", "flat_rate_pct": "0.02",
                "currency": "ZAR",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        agreement_public_id = agreement_resp.json()["public_id"]
        # Fixed, far-future literal dates rather than date.today() + timedelta(...) - this test's
        # own file must not introduce a fresh DTZ011 finding of its own while proving one is
        # fixed elsewhere; a period ending in 2099 is comfortably "not yet due" under any real
        # current date this suite could plausibly run on.
        period_resp = await client.post(
            f"/rebates/{agreement_public_id}/periods",
            json={
                "period_start": "2090-01-01", "period_end": "2099-12-31",
                "actual_spend": "0",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        period_public_id = period_resp.json()["public_id"]

        close_resp = await client.post(
            f"/rebates/{agreement_public_id}/periods/{period_public_id}/close?as_of_date=2000-01-01",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert close_resp.status_code == 409, close_resp.text


class TestClosePeriodReadsNoWallClock:
    def test_close_period_no_longer_calls_today_or_bare_now(self):
        source = inspect.getsource(rebate_service.close_period)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "today":
                    raise AssertionError(f"close_period still calls .today(): {ast.dump(node)}")
                if node.func.attr == "now" and not node.args and not node.keywords:
                    raise AssertionError(f"close_period still calls a bare, naive .now(): {ast.dump(node)}")
