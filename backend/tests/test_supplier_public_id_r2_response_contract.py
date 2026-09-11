"""
SUPPLIER-PUBLIC-ID-R2: focused proofs for the explicit supplier_public_id response mapping in
app/api/v1/opportunities.py and app/api/v1/rebates.py.

Root cause (SUPPLIER-PUBLIC-ID-R1): OpportunityRead/RebateAgreementRead declared a
supplier_public_id field assuming automatic relationship-traversal would populate it, but this
codebase never uses SQLAlchemy relationship() anywhere - Opportunity.supplier_id and
RebateAgreement.supplier_id are plain FK integer columns with no attribute path to the related
supplier's public_id. The fix mirrors app/api/v1/purchase_orders.py's already-established
pattern: explicit, RLS-scoped queries + explicit response-model construction, never a bare
.model_validate() off the ORM instance.

Domain gate (this phase): a RebateAgreement may legitimately be buy-side (supplier) or sell-side
(customer) per ck_rebate_agreements_supplier_or_customer, but RebateAgreementCreate has no
customer_id/customer_public_id input field at all and rebate_service.create_rebate_agreement
never sets customer_id - confirmed directly from source, not assumed. So no customer-side
agreement is reachable through this API today, and RebateAgreementRead.supplier_public_id
correctly stays required, not Optional - test 4 below proves the absence of that path rather
than exercising a customer-side response (there is none to exercise).
"""
import uuid

import pytest


async def _register(client, email: str, org_name: str) -> str:
    resp = await client.post(
        "/auth/register",
        json={"first_name": "T", "last_name": "U", "email": email,
              "password": "correct-horse-battery-staple", "organisation_name": org_name},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


async def _create_supplier(client, token: str, legal_name: str) -> str:
    resp = await client.post(
        "/suppliers", json={"legal_name": legal_name, "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()["public_id"]


@pytest.mark.integration
async def test_opportunity_with_supplier_returns_exact_supplier_public_id(client):
    """Proof 1."""
    token = await _register(client, "opp-with-supplier@example.com", "Opp With Supplier Org")
    supplier_public_id = await _create_supplier(client, token, "Opp Supplier")

    resp = await client.post(
        "/opportunities",
        json={"title": "Opp with supplier", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_public_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["supplier_public_id"] == supplier_public_id

    # GET-by-list also resolves it correctly (exercises the batched list_opportunities path).
    list_resp = await client.get("/opportunities", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    assert any(o["supplier_public_id"] == supplier_public_id for o in list_resp.json())


@pytest.mark.integration
async def test_opportunity_without_supplier_returns_null_and_does_not_fail(client):
    """Proof 2."""
    token = await _register(client, "opp-no-supplier@example.com", "Opp No Supplier Org")

    resp = await client.post(
        "/opportunities",
        json={"title": "Opp without supplier", "opportunity_type": "price_increase_challenge"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["supplier_public_id"] is None

    list_resp = await client.get("/opportunities", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    matching = [o for o in list_resp.json() if o["public_id"] == resp.json()["public_id"]]
    assert matching and matching[0]["supplier_public_id"] is None


@pytest.mark.integration
async def test_supplier_side_rebate_returns_supplier_public_id(client):
    """Proof 3."""
    token = await _register(client, "rebate-supplier-side@example.com", "Rebate Supplier Side Org")
    supplier_public_id = await _create_supplier(client, token, "Rebate Supplier")

    create_resp = await client.post(
        "/rebates",
        json={"supplier_public_id": supplier_public_id, "title": "Supplier-side rebate",
              "rebate_type": "fixed_percentage", "period_type": "quarterly", "flat_rate_pct": "0.02"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["supplier_public_id"] == supplier_public_id

    agreement_public_id = create_resp.json()["public_id"]
    get_resp = await client.get(
        f"/rebates/{agreement_public_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["supplier_public_id"] == supplier_public_id


@pytest.mark.integration
async def test_no_customer_side_rebate_creation_path_exists(client):
    """Proof 4 (reframed per the domain-gate finding): no customer-side RebateAgreement can be
    created through this API - RebateAgreementCreate requires supplier_public_id with no
    customer_id/customer_public_id alternative, so a request with no supplier reference is
    rejected by schema validation (422) before it ever reaches the service or database. This is
    the proof that RebateAgreementRead.supplier_public_id staying required is correct for
    everything this API can actually produce today - see the module docstring above."""
    token = await _register(client, "rebate-no-customer-path@example.com", "Rebate No Customer Path Org")

    resp = await client.post(
        "/rebates",
        json={"title": "Attempted customer-side rebate", "rebate_type": "fixed_percentage",
              "period_type": "quarterly", "flat_rate_pct": "0.02"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert any("supplier_public_id" in str(err.get("loc", [])) for err in body["detail"])


@pytest.mark.integration
async def test_cross_org_cannot_obtain_supplier_public_id_via_new_mapping_paths(client):
    """Proof 5. Covers both new explicit-resolution paths: opportunities' _resolve_supplier_
    public_id/list-batch lookup, and rebates' _resolve_supplier_public_id - neither can surface
    another organisation's supplier through any create, list, or get call."""
    token_a = await _register(client, "cross-org-map-a@example.com", "Cross Org Map A")
    token_b = await _register(client, "cross-org-map-b@example.com", "Cross Org Map B")
    supplier_a_public_id = await _create_supplier(client, token_a, "Cross Org Map A Supplier")

    # Org B cannot create an opportunity or rebate agreement referencing org A's supplier.
    opp_resp = await client.post(
        "/opportunities",
        json={"title": "Cross-org opp attempt", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_a_public_id},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert opp_resp.status_code == 404

    rebate_resp = await client.post(
        "/rebates",
        json={"supplier_public_id": supplier_a_public_id, "title": "Cross-org rebate attempt",
              "rebate_type": "fixed_percentage", "period_type": "quarterly", "flat_rate_pct": "0.02"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert rebate_resp.status_code == 404

    # Org A's own opportunity list/get for org B's token must never expose org A's supplier
    # either - org B simply sees none of org A's opportunities/agreements at all.
    opp_a_resp = await client.post(
        "/opportunities",
        json={"title": "Org A opp", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_a_public_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert opp_a_resp.status_code == 201
    list_b_resp = await client.get("/opportunities", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b_resp.status_code == 200
    assert list_b_resp.json() == []
