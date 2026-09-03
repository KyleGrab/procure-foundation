"""
Extends test_tenant_isolation.py's coverage to Phase 2's tables (spec Section 33: "Organisation A
must never access Organisation B's price reviews, files, price-review lines, supplier prices,
exports, AI context"). Same caveat as the rest of backend/tests/: needs a live Postgres, not run
in this sandbox - see tests_pure/ for what's genuinely executed here.
"""
import pytest


async def _register_org_and_supplier(client, email: str, org_name: str, supplier_name: str) -> tuple[str, str]:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    token = resp.json()["access_token"]
    supplier_resp = await client.post(
        "/suppliers", json={"legal_name": supplier_name, "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return token, supplier_resp.json()["public_id"]


async def test_supplier_list_never_crosses_tenants(client):
    token_a, _ = await _register_org_and_supplier(client, "org-a@example.com", "Org A", "Supplier A")
    token_b, _ = await _register_org_and_supplier(client, "org-b@example.com", "Org B", "Supplier B")

    resp_a = await client.get("/suppliers", headers={"Authorization": f"Bearer {token_a}"})
    resp_b = await client.get("/suppliers", headers={"Authorization": f"Bearer {token_b}"})

    names_a = {s["legal_name"] for s in resp_a.json()}
    names_b = {s["legal_name"] for s in resp_b.json()}
    assert "Supplier A" in names_a and "Supplier A" not in names_b
    assert "Supplier B" in names_b and "Supplier B" not in names_a


async def test_price_review_from_other_org_is_not_found_not_leaked(client):
    token_a, supplier_a_id = await _register_org_and_supplier(client, "reviewer-a@example.com", "Reviewer Org A", "S1")
    token_b, _ = await _register_org_and_supplier(client, "reviewer-b@example.com", "Reviewer Org B", "S2")

    review_resp = await client.post(
        "/price-reviews",
        json={"supplier_public_id": supplier_a_id, "currency": "ZAR", "price_basis": "tax_exclusive"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    review_id = review_resp.json()["public_id"]

    # Org B must get a 404 (RLS-backed: the row is invisible, not "403 forbidden" which would
    # confirm the row exists) - never the review's data.
    cross_tenant_resp = await client.get(
        f"/price-reviews/{review_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_tenant_resp.status_code == 404
