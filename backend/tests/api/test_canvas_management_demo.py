"""
E2E verification that the management lens canvas renders Gourmet-informed real financial figures
end-to-end: seed via app.db.seeds.management_accounting_demo (real AsyncSession, not mocked),
log in as the demo org through the real /auth/login endpoint (never an organisation_id query
param - see app/api/v1/canvas.py's own docstring on why that would be an RLS bypass), call the
real GET /canvas/nodes?lens=management route, assert against the exact `expected` dict the seed
function itself returns (computed by the real pure engine, not a second hand-transcribed copy).

Same live-Postgres + pytest-install requirement as every other file in backend/tests/ - written,
not executed in this sandbox.
"""
from decimal import Decimal

import pytest

from app.db.seeds.management_accounting_demo import seed_management_accounting_demo

EXPECTED_NODE_IDS = {
    "gross_revenue", "cogs", "warehouse_abc", "logistics_cts", "net_profitability",
    "working_capital_summary", "node-dso", "node-dio", "node-dpo", "node-ccc",
}


@pytest.fixture
async def seeded_demo(db_session):
    return await seed_management_accounting_demo(db_session)


async def _login(client, email: str, password: str) -> str:
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_all_ten_management_nodes_present(client, seeded_demo):
    # "8 core nodes" in the original request undercounts by 2: DSO, DIO, and DPO are three
    # separate nodes (not one "DIO/DSO/DPO" node), matching what build_management_lens_graph
    # (tests_pure/test_canvas_lens.py) actually produces and what the canvas route actually
    # returns - asserting the real 10-node set, not the abbreviated description.
    token = await _login(client, seeded_demo["login_email"], seeded_demo["login_password"])
    resp = await client.get("/canvas/nodes?lens=management", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == EXPECTED_NODE_IDS


async def test_no_organisation_id_query_param_accepted(client, seeded_demo):
    # The literal RLS-bypass shape from an earlier request - confirms it's rejected as an
    # unrecognized query param (FastAPI ignores unknown query params by default, so this
    # actually checks the safer thing: passing organisation_id does NOT change which org's data
    # comes back, since the route never reads it).
    token = await _login(client, seeded_demo["login_email"], seeded_demo["login_password"])
    resp = await client.get(
        "/canvas/nodes?lens=management&organisation_id=99999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    node_ids = {n["id"] for n in resp.json()["nodes"]}
    assert node_ids == EXPECTED_NODE_IDS  # identical to the no-param case - the extra param did nothing


async def test_revenue_cogs_and_margin_nodes_match_seeded_ledger_totals(client, seeded_demo):
    token = await _login(client, seeded_demo["login_email"], seeded_demo["login_password"])
    resp = await client.get("/canvas/nodes?lens=management", headers={"Authorization": f"Bearer {token}"})
    nodes_by_id = {n["id"]: n for n in resp.json()["nodes"]}
    expected = seeded_demo["expected"]

    assert Decimal(nodes_by_id["gross_revenue"]["data"]["metricValue"]) == expected["gross_revenue"]
    assert Decimal(nodes_by_id["cogs"]["data"]["metricValue"]) == expected["cogs"]
    assert Decimal(nodes_by_id["net_profitability"]["data"]["metricValue"]) == expected["net_margin"]


async def test_ccc_node_matches_real_gourmet_working_capital_calculation(client, seeded_demo):
    token = await _login(client, seeded_demo["login_email"], seeded_demo["login_password"])
    resp = await client.get("/canvas/nodes?lens=management", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    nodes_by_id = {n["id"]: n for n in body["nodes"]}
    expected = seeded_demo["expected"]

    ccc_node = nodes_by_id["node-ccc"]
    assert Decimal(ccc_node["data"]["details"]["total_ccc_days"]) == expected["current_ccc"]

    dso_node = nodes_by_id["node-dso"]
    assert Decimal(dso_node["data"]["details"]["value_days"]) == expected["current_dso"]
    # variance_vs_prior must be present and non-null - the whole point of seeding two consecutive
    # WorkingCapitalSnapshot periods (spec's own requirement) is that this is NOT None here.
    assert dso_node["data"]["details"]["variance_vs_prior"] is not None
    assert Decimal(dso_node["data"]["details"]["variance_vs_prior"]) == expected["dso_variance"]


async def test_management_lens_rls_isolation_from_a_different_org(client, seeded_demo):
    # A brand-new, unrelated org must see an EMPTY management lens, never the demo org's real
    # Gourmet-informed figures - the actual tenant-isolation property this whole feature depends on.
    other_resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Other", "last_name": "Org", "email": "other-org-mgmt-lens@example.com",
            "password": "correct-horse-battery-staple", "organisation_name": "Unrelated Org",
        },
    )
    other_token = other_resp.json()["access_token"]
    resp = await client.get("/canvas/nodes?lens=management", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}
