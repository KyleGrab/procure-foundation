"""
Integration tests for POST /treasury/calculate-exposure. Same live-Postgres requirement as
every other file in backend/tests/ - written, not executed (no live Postgres, no pytest
install, unchanged all engagement).
"""


async def _register_org(client, email: str, org_name: str) -> str:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    return resp.json()["access_token"]


_DEMO_UNHEDGED_PAYLOAD = {
    "transaction_date": "2026-06-01", "reporting_date": "2026-08-28", "customer_id": None,
    "currency_code": "USD", "foreign_currency_amount": "100000",
    "transaction_date_spot_rate": "18.00", "reporting_date_spot_rate": "19.80",
}


async def test_missing_jwt_returns_401(client):
    resp = await client.post("/treasury/calculate-exposure", json=_DEMO_UNHEDGED_PAYLOAD)
    assert resp.status_code == 401


async def test_valid_unhedged_payload_returns_201_with_real_verified_variance(client):
    token = await _register_org(client, "treasury-fresh@example.com", "Treasury Fresh Org")
    resp = await client.post(
        "/treasury/calculate-exposure", json=_DEMO_UNHEDGED_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_hedged"] is False
    assert body["unrealized_variance"] == "180000.0000"
    assert body["hedging_gain_loss"] is None


async def test_hedged_payload_with_fec_returns_hedging_gain_not_unrealized_variance(client):
    token = await _register_org(client, "treasury-hedged@example.com", "Treasury Hedged Org")
    hedged_payload = {**_DEMO_UNHEDGED_PAYLOAD, "fec_contract_rate": "18.20"}
    resp = await client.post(
        "/treasury/calculate-exposure", json=hedged_payload, headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_hedged"] is True
    assert body["hedging_gain_loss"] == "160000.0000"
    assert body["unrealized_variance"] is None


async def test_zero_spot_rate_returns_422_not_a_generic_400(client):
    token = await _register_org(client, "treasury-invalid@example.com", "Treasury Invalid Org")
    bad_payload = {**_DEMO_UNHEDGED_PAYLOAD, "transaction_date_spot_rate": "0"}
    resp = await client.post(
        "/treasury/calculate-exposure", json=bad_payload, headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"
