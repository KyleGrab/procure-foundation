"""Extends tenant isolation coverage to contracts (spec Section 33's pattern applied to Phase 3).
Same live-Postgres requirement as the rest of backend/tests/ - not run in this sandbox."""


async def _register_org_with_supplier_and_contract(client, email: str, org_name: str) -> tuple[str, str]:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    token = resp.json()["access_token"]
    supplier_resp = await client.post(
        "/suppliers", json={"legal_name": f"{org_name} Supplier", "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    supplier_id = supplier_resp.json()["public_id"]
    contract_resp = await client.post(
        "/contracts",
        json={
            "supplier_public_id": supplier_id, "title": f"{org_name} Contract",
            "start_date": "2026-01-01", "expiry_date": "2027-01-01",
            "notice_period_days": 90, "currency": "ZAR",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    return token, contract_resp.json()["public_id"]


async def test_contract_from_other_org_returns_404_not_data(client):
    token_a, contract_a_id = await _register_org_with_supplier_and_contract(
        client, "contract-org-a@example.com", "Contract Org A"
    )
    token_b, _ = await _register_org_with_supplier_and_contract(
        client, "contract-org-b@example.com", "Contract Org B"
    )

    cross_tenant_resp = await client.get(
        f"/contracts/{contract_a_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_tenant_resp.status_code == 404


async def test_contract_list_never_crosses_tenants(client):
    token_a, _ = await _register_org_with_supplier_and_contract(
        client, "contract-list-a@example.com", "Contract List Org A"
    )
    token_b, _ = await _register_org_with_supplier_and_contract(
        client, "contract-list-b@example.com", "Contract List Org B"
    )

    resp_a = await client.get("/contracts", headers={"Authorization": f"Bearer {token_a}"})
    resp_b = await client.get("/contracts", headers={"Authorization": f"Bearer {token_b}"})

    titles_a = {c["title"] for c in resp_a.json()}
    titles_b = {c["title"] for c in resp_b.json()}
    assert "Contract List Org A Contract" in titles_a and "Contract List Org A Contract" not in titles_b
    assert "Contract List Org B Contract" in titles_b and "Contract List Org B Contract" not in titles_a
