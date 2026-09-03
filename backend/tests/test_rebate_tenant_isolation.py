"""Extends tenant isolation coverage to Phase 4's tables (rebate_agreements,
rebate_period_actuals, purchase_transactions) - the same coverage test_contract_tenant_isolation.py
gives contracts, applied to what Phase 4 added. Same live-Postgres requirement as the rest of
backend/tests/ - not run in this sandbox."""
import pytest


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


async def _create_rebate_agreement(client, token: str, supplier_id: str, title: str) -> str:
    resp = await client.post(
        "/rebates",
        json={
            "supplier_public_id": supplier_id, "title": title,
            "rebate_type": "fixed_percentage", "period_type": "quarterly",
            "flat_rate_pct": "0.025", "currency": "ZAR",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["public_id"]


async def test_rebate_agreement_from_other_org_returns_404_not_data(client):
    token_a, supplier_a = await _register_org_with_supplier(client, "rebate-org-a@example.com", "Rebate Org A")
    token_b, _ = await _register_org_with_supplier(client, "rebate-org-b@example.com", "Rebate Org B")
    agreement_a = await _create_rebate_agreement(client, token_a, supplier_a, "Org A Rebate")

    cross_tenant_resp = await client.get(
        f"/rebates/{agreement_a}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_tenant_resp.status_code == 404


async def test_rebate_period_actual_from_other_org_returns_404(client):
    token_a, supplier_a = await _register_org_with_supplier(client, "rebate-period-a@example.com", "Rebate Period Org A")
    token_b, _ = await _register_org_with_supplier(client, "rebate-period-b@example.com", "Rebate Period Org B")
    agreement_a = await _create_rebate_agreement(client, token_a, supplier_a, "Period Test Rebate")

    period_resp = await client.post(
        f"/rebates/{agreement_a}/periods",
        json={"period_start": "2026-01-01", "period_end": "2026-03-31", "actual_spend": "1000000"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    period_id = period_resp.json()["public_id"]

    cross_tenant_resp = await client.get(
        f"/rebates/{agreement_a}/periods/{period_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    # Org B doesn't even have the parent agreement visible, so this must 404 at the agreement
    # lookup, not leak the period's existence via a different error shape.
    assert cross_tenant_resp.status_code == 404


async def test_purchase_transaction_upload_isolated_by_supplier_org(client):
    token_a, supplier_a = await _register_org_with_supplier(client, "txn-org-a@example.com", "Txn Org A")
    token_b, _ = await _register_org_with_supplier(client, "txn-org-b@example.com", "Txn Org B")

    # Org B must not be able to upload transactions against Org A's supplier at all - the
    # supplier lookup itself is RLS-scoped, so this should 404 rather than silently succeed
    # against a supplier_id org B can't actually see.
    files = {"file": ("transactions.xlsx", b"not-a-real-file", "application/vnd.ms-excel")}
    cross_tenant_resp = await client.post(
        f"/purchase-transactions/{supplier_a}/upload",
        files=files, headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_tenant_resp.status_code == 404
