"""
AUDIT-ENTITY-ID-R2: focused tests for app.services.audit_service.record's entity_id
canonicalization boundary, plus the two previously-defective callers
(treasury_service.ingest_fx_transaction, route_profitability_service.ingest_route_profitability)
this phase corrects.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import InvalidAuditIdentifierError
from app.core.security import decode_access_token
from app.db.models import AuditLog, Organisation, User
from app.services import audit_service
from app.services.route_profitability_service import ingest_route_profitability
from app.services.treasury_service import ingest_fx_transaction


async def _register_org(client, email: str, org_name: str) -> tuple[str, int, int]:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    token = resp.json()["access_token"]
    claims = decode_access_token(token)
    return token, claims.active_org_id, claims.user_id


async def _latest_audit_row(db_session, *, organisation_id: int, action: str) -> AuditLog:
    result = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.organisation_id == organisation_id)
        .where(AuditLog.action == action)
        .order_by(AuditLog.id.desc())
    )
    row = result.scalars().first()
    assert row is not None, f"no audit row found for action={action!r}, organisation_id={organisation_id!r}"
    return row


class TestCanonicalizationBoundary:
    """Direct, DB-free-of-workflow proofs of audit_service.record's own contract - each
    canonicalized value is checked immediately against what actually persisted."""

    async def test_integer_entity_id_persists_as_canonical_text(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "audit-int@example.com", "Audit Int Org")
        await audit_service.record(
            db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_int_case",
            entity_type="test_entity", entity_id=42,
        )
        await db_session.commit()
        row = await _latest_audit_row(db_session, organisation_id=org_id, action="audit_r2_int_case")
        assert row.entity_id == "42"
        assert isinstance(row.entity_id, str)

    async def test_string_entity_id_persists_unchanged(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "audit-str@example.com", "Audit Str Org")
        await audit_service.record(
            db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_str_case",
            entity_type="test_entity", entity_id="already-a-string-42",
        )
        await db_session.commit()
        row = await _latest_audit_row(db_session, organisation_id=org_id, action="audit_r2_str_case")
        assert row.entity_id == "already-a-string-42"

    async def test_uuid_entity_id_persists_as_canonical_text(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "audit-uuid@example.com", "Audit UUID Org")
        identifier = uuid.uuid4()
        await audit_service.record(
            db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_uuid_case",
            entity_type="test_entity", entity_id=identifier,
        )
        await db_session.commit()
        row = await _latest_audit_row(db_session, organisation_id=org_id, action="audit_r2_uuid_case")
        assert row.entity_id == str(identifier)

    async def test_none_entity_id_still_persists_as_null(self, client, db_session):
        """Pre-existing, deliberate call sites (e.g. working_capital_service's batch ingestions)
        rely on entity_id=None meaning "no single target row" - must remain unaffected."""
        _, org_id, user_id = await _register_org(client, "audit-none@example.com", "Audit None Org")
        await audit_service.record(
            db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_none_case",
            entity_type="test_entity", entity_id=None,
        )
        await db_session.commit()
        row = await _latest_audit_row(db_session, organisation_id=org_id, action="audit_r2_none_case")
        assert row.entity_id is None

    async def test_unsupported_entity_id_type_raises_before_db_write(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "audit-bad@example.com", "Audit Bad Org")
        with pytest.raises(InvalidAuditIdentifierError):
            await audit_service.record(
                db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_unsupported_case",
                entity_type="test_entity", entity_id=["not", "a", "real", "identifier"],
            )
        # Never reached db.add()/the database at all - nothing pending, nothing persisted.
        assert not db_session.new
        result = await db_session.execute(
            select(AuditLog).where(AuditLog.action == "audit_r2_unsupported_case")
        )
        assert result.scalars().first() is None

    async def test_bool_entity_id_raises_rather_than_silently_stringifying(self, client, db_session):
        """bool is technically an int subclass in Python - must not silently become "True"/"False",
        almost certainly the wrong variable at a real call site rather than a genuine identifier."""
        _, org_id, user_id = await _register_org(client, "audit-bool@example.com", "Audit Bool Org")
        with pytest.raises(InvalidAuditIdentifierError):
            await audit_service.record(
                db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_bool_case",
                entity_type="test_entity", entity_id=True,
            )


class TestTreasuryWorkflowAuditCanonicalization:
    async def test_treasury_workflow_no_longer_raises_and_creates_canonical_audit_row(self, client, db_session):
        token, org_id, user_id = await _register_org(client, "audit-treasury@example.com", "Audit Treasury Org")
        resp = await client.post(
            "/treasury/calculate-exposure",
            json={
                "transaction_date": "2026-06-01", "reporting_date": "2026-08-28", "customer_id": None,
                "currency_code": "USD", "foreign_currency_amount": "100000",
                "transaction_date_spot_rate": "18.00", "reporting_date_spot_rate": "19.80",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201  # no NumericValueOutOfRangeError/DataError - request succeeds
        snapshot_id = resp.json()["snapshot_id"]

        row = await _latest_audit_row(db_session, organisation_id=org_id, action="fx_transaction_ingested")
        assert row.entity_id == str(snapshot_id)
        assert isinstance(row.entity_id, str)
        assert row.entity_type == "fx_transaction_snapshot"
        assert row.organisation_id == org_id
        assert row.user_id == user_id


class TestRouteProfitabilityWorkflowAuditCanonicalization:
    """POST /logistics/route-profitability is unconditionally fail-closed (F-03,
    EvidenceRequiredError, raised before ingest_route_profitability is ever reached - see
    app/api/v1/logistics.py:92) - the same reason test_route_profitability_integration.py's own
    TestEvidenceGateNeverCallsIngestion tests the route function directly rather than via HTTP.
    Proving the audit fix for this service therefore means calling ingest_route_profitability
    directly, the only currently-reachable path to it - the identical, established pattern this
    file's own sibling already uses for the equivalent reason."""

    async def test_direct_service_call_no_longer_raises_and_creates_canonical_audit_row(self, client, db_session):
        org = Organisation(name="Audit Route Profit Org", default_currency="ZAR", country="ZA")
        db_session.add(org)
        await db_session.flush()
        user = User(first_name="Audit", last_name="RouteProfit", email="audit-route-profit@example.com",
                    password_hash="not-a-real-hash-seed-only", verified=True)
        db_session.add(user)
        await db_session.flush()

        result = await ingest_route_profitability(
            db_session, organisation_id=org.id, user_id=user.id, trip_date=date(2026, 1, 1),
            revenue=Decimal("1000"), cogs=Decimal("800"), trade_spend=Decimal("0"), revenue_basis="gross",
            trip_fixed_costs=Decimal("50"), distance_variable_costs=Decimal("20"), activity_time_costs=Decimal("10"),
        )  # previously raised asyncpg.exceptions.DataError: expected str, got int

        row = await _latest_audit_row(db_session, organisation_id=org.id, action="route_profitability_ingested")
        assert row.entity_id == str(result["snapshot_id"])
        assert isinstance(row.entity_id, str)
        assert row.entity_type == "route_profitability_snapshot"


class TestAuditTenantIsolationAndFailureSemanticsUnchanged:
    async def test_audit_rows_retain_correct_organisation_and_stay_scoped(self, client, db_session):
        _, org_a, user_a = await _register_org(client, "audit-tenant-a@example.com", "Audit Tenant Org A")
        _, org_b, user_b = await _register_org(client, "audit-tenant-b@example.com", "Audit Tenant Org B")
        await audit_service.record(
            db_session, organisation_id=org_a, user_id=user_a, action="audit_r2_tenant_case",
            entity_type="test_entity", entity_id=1,
        )
        await audit_service.record(
            db_session, organisation_id=org_b, user_id=user_b, action="audit_r2_tenant_case",
            entity_type="test_entity", entity_id=1,
        )
        await db_session.commit()

        row_a = await _latest_audit_row(db_session, organisation_id=org_a, action="audit_r2_tenant_case")
        row_b = await _latest_audit_row(db_session, organisation_id=org_b, action="audit_r2_tenant_case")
        assert row_a.organisation_id == org_a
        assert row_b.organisation_id == org_b
        assert row_a.id != row_b.id
        # Both canonicalized identically despite belonging to different orgs - canonicalization
        # doesn't leak or mix identifiers across tenants.
        assert row_a.entity_id == row_b.entity_id == "1"

    async def test_audit_failure_propagates_uncaught_and_transaction_is_not_silently_saved(self, client, db_session):
        """Not swallowed, not best-effort, not backgrounded: an entity_id that fails
        canonicalization still aborts the whole call exactly as any other unhandled exception in
        this session would - existing transaction semantics (the caller's own commit is what
        would have persisted everything together) are untouched by this phase's change."""
        _, org_id, user_id = await _register_org(client, "audit-failure@example.com", "Audit Failure Org")
        with pytest.raises(InvalidAuditIdentifierError):
            await audit_service.record(
                db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_never_persisted",
                entity_type="test_entity", entity_id=object(),
            )
        # The session is still usable afterward for a real write - canonicalization failing
        # didn't corrupt the transaction or require a rollback to recover.
        await audit_service.record(
            db_session, organisation_id=org_id, user_id=user_id, action="audit_r2_recovery_case",
            entity_type="test_entity", entity_id="fine",
        )
        await db_session.commit()
        result = await db_session.execute(
            select(AuditLog).where(AuditLog.action == "audit_r2_never_persisted")
        )
        assert result.scalars().first() is None
        row = await _latest_audit_row(db_session, organisation_id=org_id, action="audit_r2_recovery_case")
        assert row.entity_id == "fine"
