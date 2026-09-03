"""
GET /canvas/nodes?lens=management integration tests. Same live-Postgres requirement as every
other file in backend/tests/ (conftest.py's own docstring: "RLS policies are meaningless against
SQLite/mocks") - written following the established test_phase5_api.py pattern, not executed.
pytest itself still isn't installed in the sandbox that authored this file, on top of there being
no live Postgres - both constraints unchanged all session.
"""
import pytest


async def _register_org(client, email: str, org_name: str) -> str:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    return resp.json()["access_token"]


async def test_management_lens_returns_200_with_empty_graph_when_no_data_ingested(client):
    # A fresh org has no working_capital_snapshots yet - build_management_lens's own documented
    # behavior is an empty graph, not a 404/500. This is the real, expected first-run state.
    token = await _register_org(client, "mgmt-lens-org@example.com", "Mgmt Lens Org")
    resp = await client.get("/canvas/nodes?lens=management", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"nodes": [], "edges": []}


async def test_unsupported_lens_value_returns_422_not_a_500(client):
    token = await _register_org(client, "mgmt-lens-bad@example.com", "Bad Lens Org")
    resp = await client.get("/canvas/nodes?lens=accounting", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422  # Literal[...] validation rejects it before the route body runs


async def test_management_lens_rls_isolation_across_orgs(client):
    # Org A and Org B both have empty (no-data) management lenses at this point - the real
    # assertion is that querying with either token never errors trying to read the other org's
    # rows, matching the same tenant-isolation smoke test used for every other lens.
    token_a = await _register_org(client, "mgmt-lens-a@example.com", "Mgmt Lens Org A")
    token_b = await _register_org(client, "mgmt-lens-b@example.com", "Mgmt Lens Org B")

    resp_a = await client.get("/canvas/nodes?lens=management", headers={"Authorization": f"Bearer {token_a}"})
    resp_b = await client.get("/canvas/nodes?lens=management", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_a.status_code == 200 and resp_b.status_code == 200
    assert resp_a.json() == resp_b.json() == {"nodes": [], "edges": []}


async def test_response_matches_the_react_flow_schema_shape(client):
    """
    Schema-shape check against the procurement lens instead of management (procurement's graph
    is non-empty even with zero seeded data - it iterates real Supplier rows if any exist, but
    more importantly this asserts the *shape* every lens's serializer produces, via
    app/api/v1/canvas.py's shared _serialize_graph function - one function, one schema, checked
    once here rather than duplicated per lens).
    """
    token = await _register_org(client, "mgmt-lens-shape@example.com", "Shape Check Org")
    await client.post(
        "/suppliers", json={"legal_name": "Shape Check Supplier", "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get("/canvas/nodes?lens=procurement", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body
    for node in body["nodes"]:
        assert node["type"] == "customLensNode"
        assert set(node["data"].keys()) >= {"label", "nodeType", "metricValue", "status", "trend", "details"}
    for edge in body["edges"]:
        assert "source" in edge and "target" in edge
        assert isinstance(edge["animated"], bool)
