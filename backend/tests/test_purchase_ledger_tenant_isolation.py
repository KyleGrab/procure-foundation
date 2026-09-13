"""Extends tenant isolation coverage to Phase 4c's tables (purchase_orders, purchase_invoices).
Same live-Postgres requirement as the rest of backend/tests/ - not run in this sandbox."""


async def _register_org_with_supplier(client, email: str, org_name: str) -> tuple[str, str]:
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
    return token, supplier_resp.json()["public_id"]


async def test_purchase_order_from_other_org_returns_404(client):
    token_a, supplier_a = await _register_org_with_supplier(client, "po-org-a@example.com", "PO Org A")
    token_b, _ = await _register_org_with_supplier(client, "po-org-b@example.com", "PO Org B")

    create_resp = await client.post(
        "/purchase-orders",
        json={
            "supplier_public_id": supplier_a, "po_number": "PO-1001", "order_date": "2026-01-15",
            "currency": "ZAR",
            "lines": [{"description": "Widget", "quantity_ordered": "10", "unit_price": "50.00"}],
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    order_id = create_resp.json()["public_id"]

    cross_tenant_resp = await client.get(
        f"/purchase-orders/{order_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_tenant_resp.status_code == 404


async def test_purchase_invoice_cannot_be_ingested_against_another_orgs_supplier(client):
    token_a, supplier_a = await _register_org_with_supplier(client, "inv-org-a@example.com", "Invoice Org A")
    token_b, _ = await _register_org_with_supplier(client, "inv-org-b@example.com", "Invoice Org B")

    # Org B must not be able to ingest an invoice against Org A's supplier_id - the supplier
    # lookup itself is RLS-scoped, so this should fail (supplier not found), never succeed
    # against a supplier org B can't actually see.
    cross_tenant_resp = await client.post(
        "/purchase-invoices",
        json={
            "supplier_public_id": supplier_a, "invoice_number": "INV-9001", "invoice_date": "2026-02-01",
            "currency": "ZAR",
            "lines": [{"description": "Widget", "quantity": "10", "unit_price": "50.00"}],
        },
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_tenant_resp.status_code == 404
