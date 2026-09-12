"""
PRICE-REVIEW-READ-R1: focused proofs for the explicit supplier_public_id response mapping in
app/api/v1/price_reviews.py.

Root cause (same class as SUPPLIER-PUBLIC-ID-R1/R2): PriceReviewRead.supplier_public_id was
populated via a bare PriceReviewRead.model_validate(review) call, but PriceReview has no
supplier relationship or property - this codebase never uses SQLAlchemy relationship() anywhere,
only a plain, NOT NULL supplier_id FK column. Every response through create/get failed with an
unhandled pydantic ValidationError ("supplier_public_id / Field required"), previously masked by
the RLS-TXN-R1 503 and, before that fix, by SUPPLIER-PUBLIC-ID-R1/R2's own findings.

Domain gate: unlike Opportunity/RebateAgreement, PriceReview.supplier_id is NOT NULL - every
price review has exactly one supplier, no either/or case. supplier_public_id correctly stays
required; the fix is purely the missing explicit mapping (app/api/v1/purchase_orders.py's
established _to_read_model pattern), not a nullability change.

Test C (list price reviews) from the phase's required proofs does not apply: there is no
GET /price-reviews list endpoint in this codebase at all (confirmed by direct source inspection -
see test_no_list_price_reviews_endpoint_exists below) - only create (POST) and get-by-id
(GET .../{id}) return PriceReviewRead. Both are covered by tests A/B below.
"""
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


@pytest.mark.integration
async def test_create_price_review_returns_201_and_exact_supplier_public_id(client):
    """Proof A."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "pr-create@example.com", "PR Create Org", "PR Create Supplier"
    )
    resp = await client.post(
        "/price-reviews",
        json={"supplier_public_id": supplier_public_id, "currency": "ZAR", "price_basis": "tax_exclusive"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["supplier_public_id"] == supplier_public_id


@pytest.mark.integration
async def test_get_price_review_returns_same_exact_supplier_public_id(client):
    """Proof B."""
    token, supplier_public_id = await _register_org_and_supplier(
        client, "pr-get@example.com", "PR Get Org", "PR Get Supplier"
    )
    create_resp = await client.post(
        "/price-reviews",
        json={"supplier_public_id": supplier_public_id, "currency": "ZAR", "price_basis": "tax_exclusive"},
        headers={"Authorization": f"Bearer {token}"},
    )
    review_public_id = create_resp.json()["public_id"]

    get_resp = await client.get(
        f"/price-reviews/{review_public_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["supplier_public_id"] == supplier_public_id


def test_no_list_price_reviews_endpoint_exists():
    """Documents why proof C (list) is not exercised: no GET /price-reviews list route is
    registered in this codebase - only POST (create) and GET .../{id} (get) return
    PriceReviewRead, both covered above. A future list endpoint would need this same explicit
    mapping, batched like app/api/v1/opportunities.py's list_opportunities."""
    from app.main import app

    list_routes = [
        r for r in app.routes
        if getattr(r, "path", None) == "/api/v1/price-reviews" and "GET" in getattr(r, "methods", set())
    ]
    assert list_routes == []


@pytest.mark.integration
async def test_cross_org_cannot_obtain_supplier_public_id_via_create_or_get(client):
    """Proof D. Org B cannot create a price review referencing org A's supplier, and cannot GET
    org A's price review at all - the established safe-deny (404, RLS-backed - the row is
    invisible, not "403 forbidden" which would confirm it exists), never another org's data."""
    token_a, supplier_a_public_id = await _register_org_and_supplier(
        client, "pr-cross-a@example.com", "PR Cross Org A", "PR Cross Org A Supplier"
    )
    token_b, _ = await _register_org_and_supplier(
        client, "pr-cross-b@example.com", "PR Cross Org B", "PR Cross Org B Supplier"
    )

    # Org B references org A's supplier on create - RLS hides it, service reports not found.
    cross_create_resp = await client.post(
        "/price-reviews",
        json={"supplier_public_id": supplier_a_public_id, "currency": "ZAR", "price_basis": "tax_exclusive"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_create_resp.status_code == 404

    # Org A's own review, fetched with org B's token.
    review_a_resp = await client.post(
        "/price-reviews",
        json={"supplier_public_id": supplier_a_public_id, "currency": "ZAR", "price_basis": "tax_exclusive"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert review_a_resp.status_code == 201
    review_a_public_id = review_a_resp.json()["public_id"]

    cross_get_resp = await client.get(
        f"/price-reviews/{review_a_public_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_get_resp.status_code == 404
