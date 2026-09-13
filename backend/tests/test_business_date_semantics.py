"""
BUSINESS-DATE-SEMANTICS-IMPLEMENTATION-R1: one deterministic boundary-state test per approved
service (contract_service.refresh_status, contract_service.run_alert_check,
rebate_service.check_threshold_alert, rebate_service.record_receipt's derived-status portion,
canvas_service.build_inventory_lens), plus a structural regression test that none of the five
still reads a real clock internally. Every test below calls the service function directly with
db_session (admin connection, same established pattern as tests/conftest.py's own p03_seed
fixture) rather than through HTTP - the routes' own resolution of as_of_date via
app.db.session.get_organisation_business_date is a separate, thin wiring concern with no
business logic of its own to assert against here.

close_period is deliberately absent from this file - it is explicitly excluded from this phase
and still resolves its own "today" internally exactly as before.
"""
from __future__ import annotations

import ast
import inspect
import uuid
from datetime import date, timedelta
from decimal import Decimal

import sqlalchemy as sa

from app.db.models import (
    Contract,
    InventorySnapshot,
    Location,
    Organisation,
    RebateAgreement,
    RebatePeriodActual,
    Supplier,
    User,
)
from app.schemas.rebate import RebateReceiptRecord
from app.services import canvas_service, contract_service, rebate_service


async def _seed_org_and_user(db_session, *, name: str) -> tuple[Organisation, User]:
    org = Organisation(name=name, default_currency="ZAR", country="ZA")
    db_session.add(org)
    await db_session.flush()
    user = User(
        first_name="Business", last_name="Date", email=f"bdate-{uuid.uuid4()}@procureiq.local",
        password_hash="not-a-real-hash-seed-only", verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return org, user


async def _seed_expected_amount_genesis_event(db_session, *, period_actual: RebatePeriodActual, org: Organisation) -> None:
    """migration 0021's deferred constraint trigger requires expected_amount_current_event_id to
    be set by commit time - same raw-SQL genesis-event pattern as tests/conftest.py's own
    p03_seed fixture (a version-1 event, old_* fields NULL, new_status='unknown' matching this
    row's own starting status)."""
    result = await db_session.execute(
        sa.text(
            "INSERT INTO financial_amount_status_events (public_id, organisation_id, "
            "rebate_period_actual_id, measure_code, event_version, new_status, occurred_at, "
            "change_reference, change_reason_code) "
            "VALUES (gen_random_uuid(), :org, :rpa, 'expected_amount', 1, 'unknown', now(), "
            "'test_business_date_semantics', 'initial_backfill') RETURNING id"
        ),
        {"org": org.id, "rpa": period_actual.id},
    )
    event_id = result.scalar_one()
    await db_session.execute(
        sa.text("UPDATE rebate_period_actuals SET expected_amount_current_event_id = :ev WHERE id = :pid"),
        {"ev": event_id, "pid": period_actual.id},
    )


class TestRefreshStatusBoundary:
    """classify_contract_status's own 90-day expiring_soon threshold (inclusive) - a contract
    with notice_period_days=0 keeps notice_deadline pinned to expiry_date itself, so the only
    boundary this test can cross is the expiring_soon one, not the notice-deadline one."""

    async def test_status_flips_from_active_to_expiring_soon_exactly_at_the_90_day_boundary(
        self, db_session,
    ):
        org, user = await _seed_org_and_user(db_session, name="Refresh Status Boundary Org")
        supplier = Supplier(organisation_id=org.id, legal_name="Refresh Status Supplier")
        db_session.add(supplier)
        await db_session.flush()
        expiry = date(2027, 1, 1)

        contract = Contract(
            organisation_id=org.id, supplier_id=supplier.id, title="Boundary Contract",
            start_date=date(2026, 1, 1), expiry_date=expiry, notice_period_days=0,
            currency="ZAR", created_by_user_id=user.id,
        )

        contract_service.refresh_status(contract, as_of_date=expiry - timedelta(days=91))
        assert contract.status == "active"

        contract_service.refresh_status(contract, as_of_date=expiry - timedelta(days=90))
        assert contract.status == "expiring_soon"


class TestRunAlertCheckBoundary:
    """determine_due_alerts' expiry_90 threshold (one of DEFAULT_ALERT_THRESHOLDS_DAYS) - one
    day on either side of exactly 90 days out changes whether that specific alert is due."""

    async def _make_contract(self, db_session, org, user, *, expiry: date) -> Contract:
        supplier = Supplier(organisation_id=org.id, legal_name="Alert Check Supplier")
        db_session.add(supplier)
        await db_session.flush()
        contract = Contract(
            organisation_id=org.id, supplier_id=supplier.id, title="Alert Check Contract",
            start_date=date(2026, 1, 1), expiry_date=expiry, notice_period_days=0,
            currency="ZAR", created_by_user_id=user.id,
        )
        db_session.add(contract)
        await db_session.flush()
        return contract

    async def test_expiry_90_alert_fires_at_90_days_but_not_at_91(self, db_session):
        org, user = await _seed_org_and_user(db_session, name="Alert Check Boundary Org")
        expiry = date(2027, 6, 30)

        contract_not_due = await self._make_contract(db_session, org, user, expiry=expiry)
        not_due_alerts = await contract_service.run_alert_check(
            db_session, organisation_id=org.id, contract=contract_not_due,
            as_of_date=expiry - timedelta(days=91),
        )
        assert "expiry_90" not in [a.alert_type for a in not_due_alerts]

        contract_due = await self._make_contract(db_session, org, user, expiry=expiry)
        due_alerts = await contract_service.run_alert_check(
            db_session, organisation_id=org.id, contract=contract_due,
            as_of_date=expiry - timedelta(days=90),
        )
        assert "expiry_90" in [a.alert_type for a in due_alerts]


class TestCheckThresholdAlertBoundary:
    """is_threshold_alert_due's 30-day buffer_days window - exactly 30 days before period_end is
    still within the window, 31 days before is not, independent of the spend condition (held
    constant at 90% of the next tier's threshold, above the 85% buffer_pct, in both cases)."""

    async def _make_agreement_and_period(self, db_session, org, user, *, period_end: date):
        supplier = Supplier(organisation_id=org.id, legal_name="Threshold Alert Supplier")
        db_session.add(supplier)
        await db_session.flush()
        agreement = RebateAgreement(
            organisation_id=org.id, supplier_id=supplier.id, title="Threshold Alert Agreement",
            rebate_type="tiered", period_type="quarterly",
            bands=[{"threshold_spend": "100000", "rate_pct": "0.02"}],
            currency="ZAR", created_by_user_id=user.id,
        )
        db_session.add(agreement)
        await db_session.flush()
        period_actual = RebatePeriodActual(
            organisation_id=org.id, rebate_agreement_id=agreement.id,
            period_start=period_end - timedelta(days=90), period_end=period_end,
            actual_spend="90000", entry_source="manual", entered_by_user_id=user.id,
            expected_amount_status="unknown",
        )
        db_session.add(period_actual)
        await db_session.flush()
        await _seed_expected_amount_genesis_event(db_session, period_actual=period_actual, org=org)
        return agreement, period_actual

    async def test_alert_fires_at_30_days_from_close_but_not_at_31(self, db_session):
        org, user = await _seed_org_and_user(db_session, name="Threshold Alert Boundary Org")
        period_end = date(2027, 3, 31)

        agreement_a, period_a = await self._make_agreement_and_period(
            db_session, org, user, period_end=period_end
        )
        not_due = await rebate_service.check_threshold_alert(
            db_session, organisation_id=org.id, agreement=agreement_a, period_actual=period_a,
            as_of_date=period_end - timedelta(days=31),
        )
        assert not_due is None

        agreement_b, period_b = await self._make_agreement_and_period(
            db_session, org, user, period_end=period_end
        )
        due = await rebate_service.check_threshold_alert(
            db_session, organisation_id=org.id, agreement=agreement_b, period_actual=period_b,
            as_of_date=period_end - timedelta(days=30),
        )
        assert due is not None
        assert due.alert_type == "threshold_approaching"


class TestRecordReceiptDerivedStatusIsDeterministic:
    """P-03's own _refresh_status does not currently consult its `today` argument at all in the
    classification it performs (classify_rebate_status takes no date parameter) - so the
    observable proof available for record_receipt's derived-status portion is that the result is
    identical for two different as_of_date values (real wall-clock independence), not a status
    flip at a boundary. This test also confirms the persisted receipt fields
    (received_amount/received_reference) - explicitly excluded from this phase's change - are
    set from the request exactly as before, untouched by as_of_date."""

    async def _make_period_actual(self, db_session, org, user):
        supplier = Supplier(organisation_id=org.id, legal_name="Receipt Determinism Supplier")
        db_session.add(supplier)
        await db_session.flush()
        agreement = RebateAgreement(
            organisation_id=org.id, supplier_id=supplier.id, title="Receipt Determinism Agreement",
            rebate_type="fixed_percentage", period_type="quarterly", flat_rate_pct="0.02",
            currency="ZAR", created_by_user_id=user.id,
        )
        db_session.add(agreement)
        await db_session.flush()
        period_actual = RebatePeriodActual(
            organisation_id=org.id, rebate_agreement_id=agreement.id,
            period_start=date(2027, 1, 1), period_end=date(2027, 3, 31),
            entry_source="manual", entered_by_user_id=user.id, expected_amount_status="unknown",
        )
        db_session.add(period_actual)
        await db_session.flush()
        await _seed_expected_amount_genesis_event(db_session, period_actual=period_actual, org=org)
        return period_actual

    async def test_derived_status_and_persisted_fields_identical_across_two_as_of_dates(
        self, db_session,
    ):
        org, user = await _seed_org_and_user(db_session, name="Receipt Determinism Org")
        payload = RebateReceiptRecord(received_amount="1000.00", received_reference="CN-0001")

        period_a = await self._make_period_actual(db_session, org, user)
        result_a = await rebate_service.record_receipt(
            db_session, organisation_id=org.id, user_id=user.id, period_actual=period_a,
            payload=payload, as_of_date=date(2026, 1, 1),
        )

        period_b = await self._make_period_actual(db_session, org, user)
        result_b = await rebate_service.record_receipt(
            db_session, organisation_id=org.id, user_id=user.id, period_actual=period_b,
            payload=payload, as_of_date=date(2030, 12, 31),
        )

        assert result_a["period_actual"].status == result_b["period_actual"].status
        assert result_a["leakage_result"] == result_b["leakage_result"]
        # The receipt itself - explicitly out of scope for this phase - is set from the request,
        # not from as_of_date, in both cases.
        for result in (result_a, result_b):
            assert Decimal(str(result["period_actual"].received_amount)) == Decimal("1000.00")
            assert result["period_actual"].received_reference == "CN-0001"


class TestBuildInventoryLensBoundary:
    """classify_expiry_risk's warning_window_days=30 boundary (inclusive) - a snapshot expiring
    exactly 30 days after as_of_date is expiring_soon, 31 days out is still healthy."""

    async def _make_snapshot(self, db_session, org, user, *, expiry_date: date) -> None:
        location = Location(organisation_id=org.id, code="WH1", name="Warehouse 1", location_type="warehouse")
        db_session.add(location)
        await db_session.flush()
        db_session.add(InventorySnapshot(
            organisation_id=org.id, location_id=location.id, description="Boundary SKU",
            snapshot_date=date(2026, 1, 1), quantity_on_hand="10", expiry_date=expiry_date,
            uploaded_by_user_id=user.id,
        ))
        await db_session.flush()

    async def test_expiry_status_flips_from_healthy_to_expiring_soon_exactly_at_30_days(
        self, db_session,
    ):
        as_of = date(2026, 6, 1)

        org_healthy, user_healthy = await _seed_org_and_user(db_session, name="Inventory Lens Healthy Org")
        await self._make_snapshot(db_session, org_healthy, user_healthy, expiry_date=as_of + timedelta(days=31))
        healthy_graph = await canvas_service.build_inventory_lens(
            db_session, organisation_id=org_healthy.id, as_of_date=as_of
        )
        healthy_aging_node = next(n for n in healthy_graph.nodes if n.node_type == "inventory_aging")
        assert healthy_aging_node.status.value == "positive"

        org_soon, user_soon = await _seed_org_and_user(db_session, name="Inventory Lens Expiring Org")
        await self._make_snapshot(db_session, org_soon, user_soon, expiry_date=as_of + timedelta(days=30))
        soon_graph = await canvas_service.build_inventory_lens(
            db_session, organisation_id=org_soon.id, as_of_date=as_of
        )
        soon_aging_node = next(n for n in soon_graph.nodes if n.node_type == "inventory_aging")
        assert soon_aging_node.status.value != "positive"


class TestApprovedServicesNoLongerReadTheWallClock:
    """Structural regression proof, AST-based rather than a whole-file string search: rebate_
    service.py legitimately still calls date.today() inside close_period (explicitly excluded
    from this phase), so a whole-module check would incorrectly fail. Each of the five specific
    approved functions is checked in isolation instead - none may contain a `.today()` call or a
    bare (naive) `datetime.now()` call. datetime.now(UTC)/datetime.now(tz=...) calls used for
    system-event timestamps (status_calculated_at, occurred_at, earned_at) are a different
    concern entirely (not flagged by Ruff's DTZ011, not part of this phase's scope) and are left
    untouched wherever they already existed."""

    def _assert_function_reads_no_wall_clock(self, func) -> None:
        source = inspect.getsource(func)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "today":
                    raise AssertionError(f"{func.__qualname__} still calls .today(): {ast.dump(node)}")
                if node.func.attr == "now" and not node.args and not node.keywords:
                    raise AssertionError(
                        f"{func.__qualname__} still calls a bare, naive .now(): {ast.dump(node)}"
                    )

    def test_refresh_status_reads_no_wall_clock(self):
        self._assert_function_reads_no_wall_clock(contract_service.refresh_status)

    def test_run_alert_check_reads_no_wall_clock(self):
        self._assert_function_reads_no_wall_clock(contract_service.run_alert_check)

    def test_check_threshold_alert_reads_no_wall_clock(self):
        self._assert_function_reads_no_wall_clock(rebate_service.check_threshold_alert)

    def test_record_receipt_reads_no_wall_clock(self):
        self._assert_function_reads_no_wall_clock(rebate_service.record_receipt)

    def test_build_inventory_lens_reads_no_wall_clock(self):
        self._assert_function_reads_no_wall_clock(canvas_service.build_inventory_lens)

    def test_close_period_now_also_reads_no_wall_clock(self):
        """close_period was deliberately excluded from THIS phase (BUSINESS-DATE-SEMANTICS-
        IMPLEMENTATION-R1) and still called date.today() at the time this file was written - see
        BUSINESS-DATE-CLOSE-PERIOD-ORG-LOCAL-R1 (tests/test_close_period_business_date.py) for
        the dedicated phase and focused tests that closed that gap afterward. This assertion is
        updated to match, rather than left asserting stale, now-false behaviour."""
        self._assert_function_reads_no_wall_clock(rebate_service.close_period)
