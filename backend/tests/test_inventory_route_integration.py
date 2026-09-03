"""
Integration tests for POST /inventory/upload-valuation - the actual HTTP-level behavior
(401/422/409/201) that cannot correctly be tested without a running app and, past the
missing-JWT case, a live database. Same live-Postgres requirement as every other file in
backend/tests/ - written, not executed (no live Postgres, no pytest install, no pydantic/FastAPI
stack installed in this specific sandbox either - see tests_pure/test_inventory_route_security.py's
docstring for that last one).
"""
import io

import pytest

from app.core.security import decode_access_token
from app.db.models import Location


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


async def _create_location(db_session, organisation_id: int, code: str) -> str:
    location = Location(
        organisation_id=organisation_id, code=code, name=f"Test Warehouse {code}",
        location_type="warehouse", country="ZA",
    )
    db_session.add(location)
    await db_session.flush()
    await db_session.commit()
    return str(location.public_id)


_SAMPLE_CSV = (
    "Stock Code,Description,Qty On Hand,MAC Unit Cost\n"
    "SKU004,BEEF MINCE 1KG,124,137.73\n"
    "SKU001,CHICKEN BREAST 2KG,674,4.79\n"
)


async def test_missing_jwt_returns_401(client):
    resp = await client.post(
        "/inventory/upload-valuation",
        data={"location_id": "00000000-0000-0000-0000-000000000000", "snapshot_date": "2026-08-26"},
        files={"file": ("valuation.csv", io.BytesIO(_SAMPLE_CSV.encode()), "text/csv")},
    )
    assert resp.status_code == 401


async def test_valid_upload_returns_201_with_correct_record_count(client, db_session):
    token, org_id, _ = await _register_org(client, "iv-route-fresh@example.com", "IV Route Fresh Org")
    location_public_id = await _create_location(db_session, org_id, "WH1")
    resp = await client.post(
        "/inventory/upload-valuation",
        data={"location_id": location_public_id, "snapshot_date": "2026-08-26"},
        files={"file": ("valuation.csv", io.BytesIO(_SAMPLE_CSV.encode()), "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["record_count"] == 2


async def test_malformed_row_returns_422_with_diagnostic_details_array(client, db_session):
    token, org_id, _ = await _register_org(client, "iv-route-bad@example.com", "IV Route Bad Org")
    location_public_id = await _create_location(db_session, org_id, "WH2")
    bad_csv = "Stock Code,Description,Qty On Hand,MAC Unit Cost\nSKU999,BAD ROW,not-a-number,10.00\n"
    resp = await client.post(
        "/inventory/upload-valuation",
        data={"location_id": location_public_id, "snapshot_date": "2026-08-26"},
        files={"file": ("valuation.csv", io.BytesIO(bad_csv.encode()), "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert any(d["field"] == "quantity_on_hand" for d in details)


async def test_reupload_same_location_and_date_without_correction_returns_409(client, db_session):
    token, org_id, _ = await _register_org(client, "iv-route-conflict@example.com", "IV Route Conflict Org")
    location_public_id = await _create_location(db_session, org_id, "WH3")
    payload = dict(
        data={"location_id": location_public_id, "snapshot_date": "2026-08-26"},
        headers={"Authorization": f"Bearer {token}"},
    )
    first = await client.post(
        "/inventory/upload-valuation", files={"file": ("v.csv", io.BytesIO(_SAMPLE_CSV.encode()), "text/csv")}, **payload,
    )
    assert first.status_code == 201
    second = await client.post(
        "/inventory/upload-valuation", files={"file": ("v.csv", io.BytesIO(_SAMPLE_CSV.encode()), "text/csv")}, **payload,
    )
    assert second.status_code == 409


async def test_xls_extension_is_explicitly_rejected_not_silently_mishandled(client, db_session):
    token, org_id, _ = await _register_org(client, "iv-route-xls@example.com", "IV Route XLS Org")
    location_public_id = await _create_location(db_session, org_id, "WH4")
    resp = await client.post(
        "/inventory/upload-valuation",
        data={"location_id": location_public_id, "snapshot_date": "2026-08-26"},
        files={"file": ("valuation.xls", io.BytesIO(b"not real BIFF8 bytes"), "application/vnd.ms-excel")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert "xls" in resp.json()["error"]["message"].lower()


async def test_upload_scoped_to_own_org_location_only(client, db_session):
    # A location belonging to a different organisation must never be usable, even by guessing a
    # valid-looking UUID - confirms the query's WHERE organisation_id == claims.active_org_id
    # clause actually does its job.
    token_a, org_a, _ = await _register_org(client, "iv-route-scope-a@example.com", "IV Route Scope Org A")
    _, org_b, _ = await _register_org(client, "iv-route-scope-b@example.com", "IV Route Scope Org B")
    location_b_public_id = await _create_location(db_session, org_b, "WH-B-ONLY")

    resp = await client.post(
        "/inventory/upload-valuation",
        data={"location_id": location_b_public_id, "snapshot_date": "2026-08-26"},
        files={"file": ("v.csv", io.BytesIO(_SAMPLE_CSV.encode()), "text/csv")},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404
