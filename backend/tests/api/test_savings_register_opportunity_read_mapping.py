"""
SAVINGS-REGISTER-READ-R1: focused proofs for the explicit supplier_public_id mapping in
app/api/v1/savings_register.py.

Root cause (same class as SUPPLIER-PUBLIC-ID-R1/R2, PRICE-REVIEW-READ-R1, REBATE-PERIOD-READ-R1):
GET /savings-register called OpportunityRead.model_validate(o) directly on the bare Opportunity
ORM instance, but Opportunity.supplier_public_id doesn't exist as an attribute at all - no ORM
relationship exists anywhere in this codebase, only a plain, nullable supplier_id FK column. Every
response with at least one supplier-backed opportunity failed with an unhandled pydantic
ValidationError ("supplier_public_id / Field required").

Fix mirrors app/api/v1/opportunities.py's already-established pattern (a local, independent copy,
not a shared import - each route stays its own thin file): explicit, RLS-scoped, batched
select(Supplier.id, Supplier.public_id) plus explicit OpportunityRead construction.
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
async def test_supplier_backed_opportunity_returns_exact_supplier_public_id(client):
    """Proof A."""
    token = await _register(client, "sr-with-supplier@example.com", "SR With Supplier Org")
    supplier_public_id = await _create_supplier(client, token, "SR Supplier")

    create_resp = await client.post(
        "/opportunities",
        json={"title": "SR opp with supplier", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_public_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201

    sr_resp = await client.get("/savings-register", headers={"Authorization": f"Bearer {token}"})
    assert sr_resp.status_code == 200
    matching = [o for o in sr_resp.json() if o["public_id"] == create_resp.json()["public_id"]]
    assert len(matching) == 1
    assert matching[0]["supplier_public_id"] == supplier_public_id


@pytest.mark.integration
async def test_supplierless_opportunity_returns_null_and_does_not_fail(client):
    """Proof B."""
    token = await _register(client, "sr-no-supplier@example.com", "SR No Supplier Org")

    create_resp = await client.post(
        "/opportunities",
        json={"title": "SR opp without supplier", "opportunity_type": "price_increase_challenge"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201

    sr_resp = await client.get("/savings-register", headers={"Authorization": f"Bearer {token}"})
    assert sr_resp.status_code == 200
    matching = [o for o in sr_resp.json() if o["public_id"] == create_resp.json()["public_id"]]
    assert len(matching) == 1
    assert matching[0]["supplier_public_id"] is None


@pytest.mark.integration
async def test_savings_register_matches_opportunities_route_representation(client):
    """Proof C: the savings-register response for a given opportunity is identical to the
    established /opportunities route's own representation of the same row - one underlying
    table, two reporting views, same contract."""
    token = await _register(client, "sr-cross-route@example.com", "SR Cross Route Org")
    supplier_public_id = await _create_supplier(client, token, "SR Cross Route Supplier")

    create_resp = await client.post(
        "/opportunities",
        json={"title": "SR cross-route opp", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_public_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201
    opportunity_public_id = create_resp.json()["public_id"]

    opp_list_resp = await client.get("/opportunities", headers={"Authorization": f"Bearer {token}"})
    assert opp_list_resp.status_code == 200
    opp_row = next(o for o in opp_list_resp.json() if o["public_id"] == opportunity_public_id)

    sr_resp = await client.get("/savings-register", headers={"Authorization": f"Bearer {token}"})
    assert sr_resp.status_code == 200
    sr_row = next(o for o in sr_resp.json() if o["public_id"] == opportunity_public_id)

    assert sr_row == opp_row


@pytest.mark.integration
async def test_savings_register_filter_and_waterfall_unaffected(client):
    """Proof D: savings_type filtering and the waterfall totals endpoint are untouched by this
    response-mapping repair - both read straight off stored/calculated fields, never
    supplier_public_id."""
    token = await _register(client, "sr-filter-waterfall@example.com", "SR Filter Waterfall Org")
    supplier_public_id = await _create_supplier(client, token, "SR Filter Waterfall Supplier")

    hard_saving_resp = await client.post(
        "/opportunities",
        json={"title": "Hard saving opp", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_public_id, "savings_type": "hard_saving",
              "baseline_methodology": "budget"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hard_saving_resp.status_code == 201

    other_resp = await client.post(
        "/opportunities",
        json={"title": "Cost avoidance opp", "opportunity_type": "price_increase_challenge",
              "savings_type": "cost_avoidance"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert other_resp.status_code == 201

    filtered_resp = await client.get(
        "/savings-register", params={"savings_type": "hard_saving"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert filtered_resp.status_code == 200
    filtered_ids = {o["public_id"] for o in filtered_resp.json()}
    assert hard_saving_resp.json()["public_id"] in filtered_ids
    assert other_resp.json()["public_id"] not in filtered_ids

    waterfall_resp = await client.get("/savings-register/waterfall", headers={"Authorization": f"Bearer {token}"})
    assert waterfall_resp.status_code == 200
    body = waterfall_resp.json()
    assert set(body.keys()) == {
        "identified", "validated", "approved", "implementation", "realised",
        "excluded_count", "excluded_reason_breakdown",
    }
    # Neither opportunity has a calculated/estimated annual_financial_impact yet - both excluded,
    # not fabricated into a stage total.
    assert body["excluded_count"] == 2


@pytest.mark.integration
async def test_cross_org_cannot_obtain_supplier_public_id_via_savings_register(client):
    """Proof E: org B's savings register never shows org A's opportunities or suppliers - the
    established safe deny (an empty list, RLS-scoped), never another org's data."""
    token_a = await _register(client, "sr-cross-org-a@example.com", "SR Cross Org A")
    token_b = await _register(client, "sr-cross-org-b@example.com", "SR Cross Org B")
    supplier_a_public_id = await _create_supplier(client, token_a, "SR Cross Org A Supplier")

    create_resp = await client.post(
        "/opportunities",
        json={"title": "SR org A opp", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_a_public_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert create_resp.status_code == 201

    sr_b_resp = await client.get("/savings-register", headers={"Authorization": f"Bearer {token_b}"})
    assert sr_b_resp.status_code == 200
    assert sr_b_resp.json() == []

    # Org B also cannot create its own opportunity referencing org A's supplier.
    cross_create_resp = await client.post(
        "/opportunities",
        json={"title": "SR cross-org attempt", "opportunity_type": "price_increase_challenge",
              "supplier_public_id": supplier_a_public_id},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_create_resp.status_code == 404
