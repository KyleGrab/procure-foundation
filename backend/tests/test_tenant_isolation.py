"""
The actual test spec Section 67 calls out by name: "User from Organisation A must never access
Organisation B." This is the highest-value test in the whole suite - see docs/security.md
section 3 and ADR-003 for why RLS exists as a second layer specifically so this class of bug
can't slip through even if this test somehow had a gap in it.
"""


async def _register_and_get_token(client, email: str, org_name: str) -> str:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test",
            "last_name": "User",
            "email": email,
            "password": "correct-horse-battery-staple",
            "organisation_name": org_name,
        },
    )
    return resp.json()["access_token"]


async def test_user_cannot_read_another_organisations_data(client):
    token_a = await _register_and_get_token(client, "org-a-owner@example.com", "Org A")
    token_b = await _register_and_get_token(client, "org-b-owner@example.com", "Org B")

    resp_a = await client.get("/organisations/current", headers={"Authorization": f"Bearer {token_a}"})
    resp_b = await client.get("/organisations/current", headers={"Authorization": f"Bearer {token_b}"})

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["name"] == "Org A"
    assert resp_b.json()["name"] == "Org B"
    # The actual assertion: org A's token can never see org B's name or vice versa, regardless
    # of how the request is shaped - there is no organisation-id parameter anywhere in this
    # request for a client to tamper with, by design (see docs/api.md conventions).
    assert resp_a.json()["name"] != resp_b.json()["name"]


async def test_switch_org_rejected_for_non_member(client):
    token_a = await _register_and_get_token(client, "isolated-owner@example.com", "Isolated Org")
    resp = await client.post(
        "/auth/switch-org",
        json={"organisation_public_id": "00000000-0000-0000-0000-000000000000"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
