"""
BACKEND-REBATE-DECIMAL-TYPING-R1: proves RebateAgreement/RebatePeriodActual's NUMERIC(9,6)/
NUMERIC(18,4) columns round-trip through a real Postgres connection as `Decimal`, not `float`,
and that the established rebate formulas (calculate_expected_rebate, calculate_rebate_leakage -
app.analytics.rebate_calculations, already correctly Decimal-typed and untouched by this phase)
produce identical results whether read straight off a freshly-persisted ORM row or through the
real HTTP API.

Uses the real API (register/supplier/rebate agreement/period-actual/receipt) rather than direct
ORM construction, deliberately - the historical RebateAgreement fixture/constraint issue is
out of scope for this phase, and every existing rebate test in this file's directory
(test_rebate_period_actual_read_tier_fields.py, test_rebate_tenant_isolation.py) already
establishes this exact API-driven pattern as the safe way to get a real, constraint-valid
RebateAgreement/RebatePeriodActual row.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.analytics.rebate_calculations import (
    RebateType,
    calculate_expected_rebate,
    calculate_rebate_leakage,
)
from app.db.models import RebateAgreement, RebatePeriodActual


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


async def _create_fixed_pct_agreement(client, token: str, supplier_public_id: str, flat_rate_pct: str) -> dict:
    resp = await client.post(
        "/rebates",
        json={
            "supplier_public_id": supplier_public_id, "title": "Decimal typing rebate",
            "rebate_type": "fixed_percentage", "period_type": "quarterly", "flat_rate_pct": flat_rate_pct,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _record_period(client, token: str, agreement_public_id: str, *, actual_spend: str,
                          actual_volume: str | None = None) -> dict:
    payload = {
        "period_start": date(2026, 1, 1).isoformat(), "period_end": date(2026, 3, 31).isoformat(),
        "actual_spend": actual_spend,
    }
    if actual_volume is not None:
        payload["actual_volume"] = actual_volume
    resp = await client.post(
        f"/rebates/{agreement_public_id}/periods", json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _refetch_agreement(db_session, public_id: str) -> RebateAgreement:
    """A single expire_all() followed by a single select forces a real read back from Postgres
    (db_session is expire_on_commit=False, so without this, attribute access would just be the
    Python value the test itself already sent, proving nothing about what the driver returns for
    a NUMERIC column) - but expire_all() must not be called again before the caller finishes
    reading this object's attributes, or the async ORM's lazy-reload has no greenlet context to
    run in (MissingGreenlet)."""
    db_session.expire_all()
    result = await db_session.execute(select(RebateAgreement).where(RebateAgreement.public_id == public_id))
    return result.scalar_one()


async def _refetch_period(db_session, public_id: str) -> RebatePeriodActual:
    """Same one-expire-one-select discipline as _refetch_agreement, and for the same reason -
    call this only once further attribute access on any previously-refetched object in the same
    test is no longer needed."""
    db_session.expire_all()
    result = await db_session.execute(select(RebatePeriodActual).where(RebatePeriodActual.public_id == public_id))
    return result.scalar_one()


async def _refetch_agreement_and_period(db_session, agreement_public_id: str, period_public_id: str):
    """For tests that need both rows fresh at once: exactly one expire_all() before both selects,
    so neither returned object is re-expired before the caller reads its attributes."""
    db_session.expire_all()
    agreement = (await db_session.execute(
        select(RebateAgreement).where(RebateAgreement.public_id == agreement_public_id)
    )).scalar_one()
    period = (await db_session.execute(
        select(RebatePeriodActual).where(RebatePeriodActual.public_id == period_public_id)
    )).scalar_one()
    return agreement, period


async def test_persisted_rebate_numeric_fields_return_as_decimal_not_float(client, db_session):
    token, supplier_public_id = await _register_org_and_supplier(
        client, "rebate-decimal-a@example.com", "Rebate Decimal Org A", "Rebate Decimal Supplier A",
    )
    agreement = await _create_fixed_pct_agreement(client, token, supplier_public_id, "0.017500")
    period = await _record_period(client, token, agreement["public_id"], actual_spend="123456.7891")

    fetched_agreement, fetched_period = await _refetch_agreement_and_period(
        db_session, agreement["public_id"], period["public_id"]
    )

    assert isinstance(fetched_agreement.flat_rate_pct, Decimal)
    assert not isinstance(fetched_agreement.flat_rate_pct, float)
    assert fetched_agreement.flat_rate_pct == Decimal("0.017500")

    assert isinstance(fetched_period.actual_spend, Decimal)
    assert not isinstance(fetched_period.actual_spend, float)
    assert fetched_period.actual_spend == Decimal("123456.7891")
    assert isinstance(fetched_period.expected_amount, Decimal)
    assert not isinstance(fetched_period.expected_amount, float)


async def test_known_rate_and_base_produce_exact_established_formula_result(client, db_session):
    """flat_rate_pct=0.017500 against actual_spend=123456.7891 is chosen because the product has
    more significant digits than float64 can carry exactly - the expected value is derived from
    the real, existing calculate_expected_rebate formula (never a new one invented for this test),
    and the API/DB round-trip must reproduce that exact Decimal, not a float-drifted approximation."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "rebate-decimal-b@example.com", "Rebate Decimal Org B", "Rebate Decimal Supplier B",
    )
    agreement = await _create_fixed_pct_agreement(client, token, supplier_public_id, "0.017500")
    period = await _record_period(client, token, agreement["public_id"], actual_spend="123456.7891")

    expected = calculate_expected_rebate(
        Decimal("123456.7891"), RebateType.FIXED_PERCENTAGE, flat_rate_pct=Decimal("0.017500"),
    )
    assert period["expected_amount"] == str(expected)
    assert period["expected_amount_status"] == "calculated"

    fetched_period = await _refetch_period(db_session, period["public_id"])
    assert fetched_period.expected_amount == expected


async def test_receipt_leakage_matches_established_formula_not_a_new_rule(client, db_session):
    """calculate_rebate_leakage(expected, received) is the one and only place this figure is
    computed - this proves the receipt endpoint's response reproduces exactly what that existing
    function returns for a real expected_amount and a real, partial received_amount."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "rebate-decimal-c@example.com", "Rebate Decimal Org C", "Rebate Decimal Supplier C",
    )
    agreement = await _create_fixed_pct_agreement(client, token, supplier_public_id, "0.020000")
    period = await _record_period(client, token, agreement["public_id"], actual_spend="50000.0000")
    expected_amount = calculate_expected_rebate(
        Decimal("50000.0000"), RebateType.FIXED_PERCENTAGE, flat_rate_pct=Decimal("0.020000"),
    )
    assert period["expected_amount"] == str(expected_amount)

    received_amount = Decimal("750.0000")
    receipt_resp = await client.post(
        f"/rebates/{agreement['public_id']}/periods/{period['public_id']}/receipt",
        json={"received_amount": str(received_amount), "received_reference": "CN-DECIMAL-TYPING-001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert receipt_resp.status_code == 200
    body = receipt_resp.json()

    expected_leakage = calculate_rebate_leakage(expected_amount, received_amount)
    assert body["leakage_result"]["leakage"] == str(expected_leakage)
    assert body["leakage_result"]["status"] == "ok"
    assert body["period_actual"]["received_amount"] == str(received_amount)

    fetched_period = await _refetch_period(db_session, period["public_id"])
    assert fetched_period.received_amount == received_amount
    assert isinstance(fetched_period.received_amount, Decimal)


async def test_nullable_rebate_fields_remain_none_not_zero(client, db_session):
    """actual_volume is never sent - earned_amount/received_amount are set only by close/receipt,
    neither called here. All three must come back as None (API and ORM), never 0, 0.0, Decimal(0),
    or NaN - the exact fabricated-value guardrail this whole engagement exists to enforce."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "rebate-decimal-d@example.com", "Rebate Decimal Org D", "Rebate Decimal Supplier D",
    )
    agreement = await _create_fixed_pct_agreement(client, token, supplier_public_id, "0.015000")
    period = await _record_period(client, token, agreement["public_id"], actual_spend="1000.0000")

    assert period["actual_volume"] is None
    assert period["earned_amount"] is None
    assert period["received_amount"] is None

    fetched_period = await _refetch_period(db_session, period["public_id"])
    assert fetched_period.actual_volume is None
    assert fetched_period.earned_amount is None
    assert fetched_period.received_amount is None


async def test_rebate_agreement_and_period_read_schema_serialization_unchanged(client):
    """RebateAgreementRead/RebatePeriodActualRead.model_validate(...) are the exact calls
    app/api/v1/rebates.py uses. Proves the retype didn't change the public response shape: same
    field names, Decimal values still serialize, and null fields still serialize as null."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "rebate-decimal-e@example.com", "Rebate Decimal Org E", "Rebate Decimal Supplier E",
    )
    agreement = await _create_fixed_pct_agreement(client, token, supplier_public_id, "0.017500")
    period = await _record_period(client, token, agreement["public_id"], actual_spend="123456.7891")

    assert set(agreement.keys()) == {
        "public_id", "supplier_public_id", "title", "rebate_type", "period_type",
        "flat_rate_pct", "bands", "fixed_amount", "currency", "status",
    }
    assert agreement["flat_rate_pct"] == "0.017500"
    assert agreement["fixed_amount"] is None

    assert set(period.keys()) == {
        "public_id", "period_start", "period_end", "actual_spend", "actual_volume",
        "entry_source", "expected_amount", "expected_amount_status", "expected_amount_source_basis",
        "earned_amount", "received_amount", "received_reference", "status", "status_calculated_at",
        "next_tier_threshold", "amount_to_next_tier",
    }
    assert period["actual_spend"] == "123456.7891"
    assert period["actual_volume"] is None
