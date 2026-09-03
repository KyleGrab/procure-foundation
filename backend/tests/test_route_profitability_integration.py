"""
Integration tests for POST /logistics/route-profitability - the actual HTTP-level 401/422/201
behavior. Same live-Postgres requirement as every other file in backend/tests/ - written, not
executed (no live Postgres, no pytest install, unchanged all engagement).

F-03 (foundation hardening): the endpoint now fails closed unconditionally - no evidenced
revenue/COGS/trade-spend source exists anywhere in this codebase, so caller-supplied financial
figures can never be persisted or returned as real. This is a genuine, necessary consequence for
three PRE-EXISTING tests below, not just new tests added - their old assertions described
behavior that's no longer correct, and leaving them unchanged would mean either failing outright
or silently passing while testing something false. Each updated test says explicitly what
changed and why.

TestEvidenceGateNeverCallsIngestion is a deliberate deviation from this file's own convention:
every other test here goes through the `client` fixture (the real, unmodified app, hitting a
real Postgres - conftest.py has no dependency_overrides pattern anywhere in this codebase). A
genuinely DB-free proof that ingest_route_profitability is never called requires calling the
route function directly, bypassing FastAPI's dependency injection (and therefore get_db)
entirely - there's no existing convention to match here since nothing else in this codebase
tests a route this way, so this is a new, narrowly-scoped pattern, not a reused one.
"""
import io
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import EvidenceRequiredError
from app.core.security import AccessTokenClaims, decode_access_token


async def _register_org(client, email: str, org_name: str) -> str:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    return resp.json()["access_token"]


_REAL_WEST_COAST_PAYLOAD = {
    "trip_date": "2026-07-03",
    "customer_id": "CUST039",
    "vehicle_registration": "CAA 127155",
    "route_reference": "WEST-COAST-15110",
    # Real telematics
    "distance_km": "55", "stop_count": 24,
    "total_drop_weight_kg": "686.435", "vehicle_max_payload_kg": "8000",
    # Real revenue/COGS
    "revenue": "45189.62", "cogs": "36686.08", "trade_spend": "0", "revenue_basis": "gross",
    # [DEMO] cost pool inputs
    "driver_base_salary": "850", "co_driver_base_salary": "0", "fixed_vehicle_asset_cost": "1200",
    "stem_distance_km": "15", "drop_distance_km": "25", "base_rate_per_km": "8.50", "stop_start_multiplier": "1.3",
    "sku_line_count": 18, "total_cube_m3": "4.2", "rate_per_line": "12.50", "rate_per_cube_m3": "35.00",
    "time_at_bay_minutes": "50", "free_time_minutes": "30", "demurrage_rate_per_minute": "15",
}


@pytest.mark.integration
async def test_missing_jwt_returns_401(client):
    # Unaffected by F-03 - auth resolves via Depends before the evidence gate is ever reached,
    # so a missing JWT is still rejected before any business logic runs, exactly as before.
    resp = await client.post("/logistics/route-profitability", json=_REAL_WEST_COAST_PAYLOAD)
    assert resp.status_code == 401


@pytest.mark.integration
async def test_previously_valid_payload_now_returns_422_evidence_required(client):
    # CHANGED by F-03: this payload used to return 201 with a real, computed gross_margin. That
    # behavior was the actual defect - no evidenced revenue/COGS source exists anywhere in this
    # codebase, so it was never legitimate to return a real financial figure for it. Same payload,
    # correct new behavior: rejected, not persisted, before any cost figure is even computed.
    token = await _register_org(client, "route-profit-fresh@example.com", "Route Profit Fresh Org")
    resp = await client.post(
        "/logistics/route-profitability", json=_REAL_WEST_COAST_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "evidence_required"
    assert "gross_margin" not in body  # never even computed, let alone returned


@pytest.mark.integration
async def test_evidence_gate_fires_before_plausibility_check_even_for_implausible_payloads(client):
    # CHANGED by F-03: this used to prove the plausibility check ran before cost computation.
    # It still does (unaffected, untouched code) - but it's now unreachable via this endpoint,
    # since the evidence gate sits even earlier and fires unconditionally. This test now proves
    # THAT ordering explicitly: an implausible payload is still rejected for the evidence reason,
    # not the plausibility reason, confirming the gate is genuinely first, not just usually first.
    token = await _register_org(client, "route-profit-implausible@example.com", "Route Profit Implausible Org")
    bad_payload = {**_REAL_WEST_COAST_PAYLOAD, "distance_km": "0"}
    resp = await client.post(
        "/logistics/route-profitability", json=bad_payload, headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "evidence_required"


@pytest.mark.integration
async def test_evidence_gate_fires_before_the_double_counting_guard_too(client):
    # CHANGED by F-03: this used to exercise the revenue_basis double-counting guard through this
    # route. That guard is real, tested, and untouched (app/analytics/management_accounting.py) -
    # it's just unreachable via THIS endpoint now, for the same reason as the plausibility check
    # above. Renamed and reasserted to reflect what's actually true post-change.
    token = await _register_org(client, "route-profit-doublecounted@example.com", "Route Profit Double Count Org")
    bad_payload = {**_REAL_WEST_COAST_PAYLOAD, "revenue_basis": "net_of_waterfall", "trade_spend": "1000"}
    resp = await client.post(
        "/logistics/route-profitability", json=bad_payload, headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "evidence_required"


@pytest.mark.integration
async def test_error_response_exposes_no_internal_detail(client):
    token = await _register_org(client, "route-profit-noleak@example.com", "Route Profit No Leak Org")
    resp = await client.post(
        "/logistics/route-profitability", json=_REAL_WEST_COAST_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    body_text = resp.text.lower()
    for leaked_term in ("traceback", "postgresql", "asyncpg", "/home/", "/users/", ".py\", line"):
        assert leaked_term not in body_text


class TestEvidenceGateNeverCallsIngestion:
    """
    Genuinely DB-free - calls the route function directly, bypassing FastAPI's Depends chain
    (and therefore get_db) entirely. See the module docstring for why this deviates from every
    other test in this file.
    """

    async def test_ingest_route_profitability_is_never_called(self):
        from app.api.v1.logistics import RouteProfitabilityRequest, create_route_profitability

        payload = RouteProfitabilityRequest(**_REAL_WEST_COAST_PAYLOAD)
        claims = AccessTokenClaims(user_id=1, active_org_id=1, role="owner", issued_at=0, expires_at=0)

        with patch("app.api.v1.logistics.ingest_route_profitability", new_callable=AsyncMock) as mock_ingest:
            with pytest.raises(EvidenceRequiredError):
                await create_route_profitability(payload=payload, claims=claims, db=None)
            mock_ingest.assert_not_called()


@pytest.mark.integration
async def test_no_database_write_occurs_for_a_rejected_request(client, db_session):
    from sqlalchemy import func, select

    from app.db.models import RouteProfitabilitySnapshot

    count_before = (
        await db_session.execute(select(func.count()).select_from(RouteProfitabilitySnapshot))
    ).scalar_one()

    token = await _register_org(client, "route-profit-nowrite@example.com", "Route Profit No Write Org")
    resp = await client.post(
        "/logistics/route-profitability", json=_REAL_WEST_COAST_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    count_after = (
        await db_session.execute(select(func.count()).select_from(RouteProfitabilitySnapshot))
    ).scalar_one()
    assert count_after == count_before


@pytest.mark.integration
async def test_existing_records_are_unchanged_by_a_rejected_request(client, db_session):
    from sqlalchemy import select

    from app.db.models import Organisation, RouteProfitabilitySnapshot, User

    # Seed one real row directly via db_session - the established pattern this file's own
    # fixture already documents for pre-ingestion-API setup (see conftest.py's db_session
    # docstring), used here because no evidenced ingestion path exists to create one otherwise.
    org = Organisation(name="Route Profit Preexisting Org", default_currency="ZAR", country="ZA")
    db_session.add(org)
    await db_session.flush()
    user = User(first_name="Seed", last_name="User", email="route-profit-preexisting@example.com",
                password_hash="not-a-real-hash-seed-only", verified=True)
    db_session.add(user)
    await db_session.flush()
    seeded = RouteProfitabilitySnapshot(
        organisation_id=org.id, trip_date="2026-01-01", revenue=1000, cogs=800, trade_spend=0,
        revenue_basis="gross", trip_fixed_costs=50, distance_variable_costs=20, activity_time_costs=10,
        net_net_profit=120, is_net_revenue_negative=False, uploaded_by_user_id=user.id,
    )
    db_session.add(seeded)
    await db_session.commit()
    seeded_id = seeded.id
    original_net_net_profit = seeded.net_net_profit

    token = await _register_org(client, "route-profit-preexisting-caller@example.com", "Route Profit Caller Org")
    resp = await client.post(
        "/logistics/route-profitability", json=_REAL_WEST_COAST_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    reread = (
        await db_session.execute(select(RouteProfitabilitySnapshot).where(RouteProfitabilitySnapshot.id == seeded_id))
    ).scalar_one()
    assert reread.net_net_profit == original_net_net_profit
