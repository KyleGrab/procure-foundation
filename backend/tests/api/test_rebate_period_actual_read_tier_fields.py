"""
REBATE-PERIOD-READ-R1: focused proofs for the explicit RebatePeriodActualRead tier-field mapping
in app/api/v1/rebates.py.

Root cause: every RebatePeriodActualRead response site called
RebatePeriodActualRead.model_validate(period_actual) FIRST, then tried to exclude
next_tier_threshold/amount_to_next_tier from its model_dump() and merge in a separately-computed
derived dict - but the initial model_validate() call itself requires those two fields to exist as
attributes (their type allows None, but Pydantic v2 still requires the attribute to be present
without an explicit default), and RebatePeriodActual carries no such attributes at all. The
exclude/merge step never ran; the failure happened one step earlier, inside model_validate.

The fix threads rebate_service.get_derived_progress's existing, deterministic result (itself
delegating to app.analytics.rebate_calculations.calculate_progress_to_next_tier - no tier
arithmetic is duplicated here) directly into an explicit RebatePeriodActualRead(...) construction,
same established pattern as app/api/v1/purchase_orders.py's _to_read_model.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest


async def _register_org_and_supplier(client, email: str, org_name: str, supplier_name: str) -> tuple[str, str]:
    resp = await client.post(
        "/auth/register",
        json={"first_name": "Test", "last_name": "User", "email": email,
              "password": "correct-horse-battery-staple", "organisation_name": org_name},
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    supplier_resp = await client.post(
        "/suppliers", json={"legal_name": supplier_name, "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert supplier_resp.status_code == 201
    return token, supplier_resp.json()["public_id"]


async def _create_tiered_agreement(client, token: str, supplier_public_id: str) -> str:
    resp = await client.post(
        "/rebates",
        json={
            "supplier_public_id": supplier_public_id, "title": "Tiered rebate",
            "rebate_type": "tiered", "period_type": "quarterly",
            "bands": [
                {"threshold_spend": "1000", "rate_pct": "0.01"},
                {"threshold_spend": "5000", "rate_pct": "0.02"},
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()["public_id"]


async def _create_flat_agreement(client, token: str, supplier_public_id: str) -> str:
    resp = await client.post(
        "/rebates",
        json={
            "supplier_public_id": supplier_public_id, "title": "Non-tiered rebate",
            "rebate_type": "fixed_percentage", "period_type": "quarterly", "flat_rate_pct": "0.02",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()["public_id"]


async def _record_period(client, token: str, agreement_public_id: str, actual_spend: str,
                          period_start: date, period_end: date) -> dict:
    resp = await client.post(
        f"/rebates/{agreement_public_id}/periods",
        json={"period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
              "actual_spend": actual_spend},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.integration
async def test_open_tiered_period_below_next_tier_returns_exact_progress(client):
    """Proof A."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "tier-below@example.com", "Tier Below Org", "Tier Below Supplier"
    )
    agreement_public_id = await _create_tiered_agreement(client, token, supplier_public_id)
    body = await _record_period(
        client, token, agreement_public_id, "500",
        date(2026, 1, 1), date(2026, 3, 31),
    )
    # bands: 1000 (1%), 5000 (2%) - spend of 500 is below both, so the next reachable band is
    # 1000, with 500 remaining to reach it.
    assert Decimal(body["next_tier_threshold"]) == Decimal("1000")
    assert Decimal(body["amount_to_next_tier"]) == Decimal("500")


@pytest.mark.integration
async def test_tiered_period_at_top_band_returns_null_not_zero(client):
    """Proof B: spend already at/above the highest band - no higher tier exists. Must be null,
    never an invented 0."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "tier-top@example.com", "Tier Top Org", "Tier Top Supplier"
    )
    agreement_public_id = await _create_tiered_agreement(client, token, supplier_public_id)
    body = await _record_period(
        client, token, agreement_public_id, "6000",
        date(2026, 1, 1), date(2026, 3, 31),
    )
    assert body["next_tier_threshold"] is None
    assert body["amount_to_next_tier"] is None


@pytest.mark.integration
async def test_non_tiered_period_returns_null_and_does_not_fail(client):
    """Proof C."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "non-tiered@example.com", "Non Tiered Org", "Non Tiered Supplier"
    )
    agreement_public_id = await _create_flat_agreement(client, token, supplier_public_id)
    body = await _record_period(
        client, token, agreement_public_id, "2000",
        date(2026, 1, 1), date(2026, 3, 31),
    )
    assert body["next_tier_threshold"] is None
    assert body["amount_to_next_tier"] is None


@pytest.mark.integration
async def test_response_preserves_stored_financial_actuals_through_receipt(client):
    """Proof D + F (receipt path): actual_spend, and a recorded received_amount, come back
    exactly as stored - the derived-field fix changes nothing about the recorded facts."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "preserve-facts@example.com", "Preserve Facts Org", "Preserve Facts Supplier"
    )
    agreement_public_id = await _create_tiered_agreement(client, token, supplier_public_id)
    period = await _record_period(
        client, token, agreement_public_id, "1500",
        date(2026, 1, 1), date(2026, 3, 31),
    )
    assert period["actual_spend"] == "1500.0000"

    get_resp = await client.get(
        f"/rebates/{agreement_public_id}/periods/{period['public_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["actual_spend"] == "1500.0000"
    # 5000 - 1500 = 3500 remaining to the top band.
    assert Decimal(get_resp.json()["next_tier_threshold"]) == Decimal("5000")
    assert Decimal(get_resp.json()["amount_to_next_tier"]) == Decimal("3500")

    receipt_resp = await client.post(
        f"/rebates/{agreement_public_id}/periods/{period['public_id']}/receipt",
        json={"received_amount": "30", "received_reference": "CN-TEST-001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert receipt_resp.status_code == 200
    receipt_body = receipt_resp.json()
    assert receipt_body["period_actual"]["actual_spend"] == "1500.0000"
    assert receipt_body["period_actual"]["received_amount"] == "30.0000"
    assert receipt_body["period_actual"]["received_reference"] == "CN-TEST-001"
    # Still not at the top band - the receipt doesn't change actual_spend, so tier progress is
    # unaffected and must still be a real value, not lost or zeroed by this response path either.
    assert Decimal(receipt_body["period_actual"]["next_tier_threshold"]) == Decimal("5000")
    assert Decimal(receipt_body["period_actual"]["amount_to_next_tier"]) == Decimal("3500")


@pytest.mark.integration
async def test_closed_period_response_includes_complete_tier_fields(client):
    """Proof F (close path): a period whose end date has already passed can be closed, and the
    response still carries the full, correct tier-progress contract - not just create/get."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "close-period@example.com", "Close Period Org", "Close Period Supplier"
    )
    agreement_public_id = await _create_tiered_agreement(client, token, supplier_public_id)
    yesterday = date.today() - timedelta(days=1)
    period = await _record_period(
        client, token, agreement_public_id, "800",
        yesterday - timedelta(days=90), yesterday,
    )
    close_resp = await client.post(
        f"/rebates/{agreement_public_id}/periods/{period['public_id']}/close",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert close_resp.status_code == 200
    body = close_resp.json()
    assert body["actual_spend"] == "800.0000"
    assert Decimal(body["next_tier_threshold"]) == Decimal("1000")
    assert Decimal(body["amount_to_next_tier"]) == Decimal("200")


@pytest.mark.integration
async def test_cross_org_period_returns_safe_deny_not_validation_error(client):
    """Proof E: another organisation's rebate period is a plain 404 - never a response-validation
    error, and never another org's data."""
    token_a, supplier_a_public_id = await _register_org_and_supplier(
        client, "period-cross-a@example.com", "Period Cross Org A", "Period Cross Org A Supplier"
    )
    token_b, _ = await _register_org_and_supplier(
        client, "period-cross-b@example.com", "Period Cross Org B", "Period Cross Org B Supplier"
    )
    agreement_public_id = await _create_tiered_agreement(client, token_a, supplier_a_public_id)
    period = await _record_period(
        client, token_a, agreement_public_id, "500",
        date(2026, 1, 1), date(2026, 3, 31),
    )

    # Org B doesn't even have the agreement (RLS hides it from _get_agreement first).
    cross_resp = await client.get(
        f"/rebates/{agreement_public_id}/periods/{period['public_id']}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_resp.status_code == 404
