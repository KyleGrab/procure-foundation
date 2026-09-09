"""
K2 targeted test surface: register/login/me/switch-org against the real, Alembic-migrated
schema (migration 0022's organisation_memberships hardening: NULLIF-guarded tenant_isolation +
new self_membership_select), through the real procureiq_app role and real RLS.

New, isolated file - does not modify test_rls_integration.py or any other existing test file.
Uses conftest.py's already-Alembic-bootstrapped client/db_session/db_conn fixtures (same
migrated database the rest of tests/ uses), not testcontainers - unlike test_rls_integration.py,
whose own separate, isolated testcontainers Postgres is exercised afterward as an unmodified
regression check, not by this file.

Run with: pytest backend/tests/test_k2_auth_membership_rls.py -v
"""
from __future__ import annotations

import uuid

import psycopg
from sqlalchemy import text

from app.core.config import get_settings
from app.db.models import Organisation, OrganisationMembership


def _sync_admin_dsn_as_plain_url() -> str:
    return get_settings().database_url_sync.replace("postgresql+psycopg://", "postgresql://", 1)


def _sync_app_dsn_as_plain_url() -> str:
    return get_settings().database_url_app.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _register(client, email: str, org_name: str, password: str = "correct-horse-battery-staple"):
    return await client.post(
        "/auth/register",
        json={
            "first_name": "K2", "last_name": "Test", "email": email,
            "password": password, "organisation_name": org_name,
        },
    )


# --------------------------------------------------------------------------------------------
# REGISTER
# --------------------------------------------------------------------------------------------

async def test_register_succeeds_under_real_force_rls(client):
    resp = await _register(client, "k2-register@example.com", "K2 Register Org")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "access_token" in body and "refresh_token" in body


async def test_founding_membership_belongs_to_new_user_and_org(client):
    resp = await _register(client, "k2-founding@example.com", "K2 Founding Org")
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["email"] == "k2-founding@example.com"
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["organisation_name"] == "K2 Founding Org"
    assert body["memberships"][0]["role"] == "owner"
    assert body["memberships"][0]["status"] == "active"


# --------------------------------------------------------------------------------------------
# LOGIN
# --------------------------------------------------------------------------------------------

async def test_login_discovers_active_membership_after_correct_password(client):
    await _register(client, "k2-login@example.com", "K2 Login Org", password="right-password-123")
    resp = await client.post(
        "/auth/login", json={"email": "k2-login@example.com", "password": "right-password-123"}
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()


async def test_login_wrong_password_never_gains_membership_visibility(client):
    await _register(client, "k2-wrongpw@example.com", "K2 WrongPW Org", password="right-password-123")
    resp = await client.post(
        "/auth/login", json={"email": "k2-wrongpw@example.com", "password": "totally-wrong-password"}
    )
    assert resp.status_code == 401, resp.text
    assert "access_token" not in resp.json()


# --------------------------------------------------------------------------------------------
# /auth/me - self-membership isolation
# --------------------------------------------------------------------------------------------

async def test_auth_me_returns_only_callers_memberships(client):
    resp_a = await _register(client, "k2-me-a@example.com", "K2 Me Org A")
    await _register(client, "k2-me-b@example.com", "K2 Me Org B")
    token_a = resp_a.json()["access_token"]

    me_a = await client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    assert me_a.status_code == 200, me_a.text
    org_names = {m["organisation_name"] for m in me_a.json()["memberships"]}
    assert org_names == {"K2 Me Org A"}  # never sees user B's org, despite both existing rows
    # being on the same physical table with the same session/pool infrastructure.


# --------------------------------------------------------------------------------------------
# SWITCH-ORG
# --------------------------------------------------------------------------------------------

async def test_switch_org_denied_when_user_belongs_only_to_org_a(client):
    resp_a = await _register(client, "k2-switch-a-only@example.com", "K2 Switch A Only")
    resp_b = await _register(client, "k2-switch-b-other@example.com", "K2 Switch B Other")
    token_a = resp_a.json()["access_token"]

    me_b = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {resp_b.json()['access_token']}"}
    )
    org_b_public_id = me_b.json()["memberships"][0]["organisation_public_id"]

    resp = await client.post(
        "/auth/switch-org",
        json={"organisation_public_id": org_b_public_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, resp.text


async def test_switch_org_denied_for_nonexistent_org(client):
    resp_a = await _register(client, "k2-switch-nonexistent@example.com", "K2 Switch Nonexistent")
    token_a = resp_a.json()["access_token"]

    resp = await client.post(
        "/auth/switch-org",
        json={"organisation_public_id": str(uuid.uuid4())},  # forged/nonexistent target
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, resp.text


async def test_switch_org_allowed_when_user_belongs_to_both_and_denied_when_inactive(client, db_session):
    resp_a = await _register(client, "k2-switch-multi@example.com", "K2 Switch Multi Org A")
    token_a = resp_a.json()["access_token"]

    # Seed a second, real membership for the SAME user directly via the admin connection - no
    # invite-acceptance HTTP flow exists to test through yet (same established pattern as
    # conftest.py's own p03_seed fixture: "tests that need to set up data no ingestion API
    # exists for yet").
    me_a = await client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    user_public_id = me_a.json()["public_id"]

    result = await db_session.execute(
        text("SELECT id FROM users WHERE public_id = :pid"), {"pid": user_public_id}
    )
    user_id = result.scalar_one()

    org_b = Organisation(name="K2 Switch Multi Org B")
    org_c = Organisation(name="K2 Switch Multi Org C (inactive membership)")
    db_session.add_all([org_b, org_c])
    await db_session.flush()
    db_session.add(OrganisationMembership(user_id=user_id, organisation_id=org_b.id, role="member", status="active"))
    db_session.add(
        OrganisationMembership(user_id=user_id, organisation_id=org_c.id, role="member", status="invited")
    )
    await db_session.commit()
    org_b_public_id, org_c_public_id = str(org_b.public_id), str(org_c.public_id)

    # Org A + Org B -> Org B allowed.
    resp_allowed = await client.post(
        "/auth/switch-org",
        json={"organisation_public_id": org_b_public_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_allowed.status_code == 200, resp_allowed.text
    assert "access_token" in resp_allowed.json()

    # Inactive membership in Org C -> denied.
    resp_inactive = await client.post(
        "/auth/switch-org",
        json={"organisation_public_id": org_c_public_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_inactive.status_code == 403, resp_inactive.text


# --------------------------------------------------------------------------------------------
# CRITICAL: pooled-connection empty-string GUC regression test (mandatory per K2-R1 §9)
# --------------------------------------------------------------------------------------------

def test_empty_string_current_org_id_on_reused_connection_is_a_safe_deny_not_a_cast_error():
    """
    Reproduces exactly the defect the K2 investigation verified: SET LOCAL a custom GUC once on
    a physical connection, let that transaction end, then - on the SAME physical connection,
    with no fresh SET - current_setting('app.current_org_id', true) reads back '' rather than
    NULL. Before migration 0022, evaluating organisation_memberships' tenant_isolation policy in
    that state raised `invalid input syntax for type bigint: ""` (a hard SQL error). After 0022,
    NULLIF(..., '')::bigint turns that residue into NULL, and the policy evaluates to a normal,
    safe deny (zero rows), never an error.

    Deliberately a single raw psycopg connection (not the ORM/pool) so the "physical connection
    reuse" state is exact and directly observed, not inferred - same raw-SQL-observation
    rationale as test_rls_integration.py's own FORCE RLS demonstration tests. Seeds its own
    org/user/membership via the admin connection rather than depending on another test in this
    module having already run, so it passes in isolation too (pytest -k, reordering, etc.).
    """
    with psycopg.connect(_sync_admin_dsn_as_plain_url(), autocommit=True) as admin_conn:
        with admin_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organisations (public_id, name) VALUES (gen_random_uuid(), %s) RETURNING id",
                ("K2 GUC Regression Org",),
            )
            seed_org_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO users (public_id, first_name, last_name, email, password_hash) "
                "VALUES (gen_random_uuid(), 'K2', 'GUC', 'k2-guc-regression@example.com', 'x') RETURNING id",
                (),
            )
            seed_user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO organisation_memberships (public_id, user_id, organisation_id, role, status) "
                "VALUES (gen_random_uuid(), %s, %s, 'owner', 'active')",
                (seed_user_id, seed_org_id),
            )

    with psycopg.connect(_sync_app_dsn_as_plain_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            # Establish, then end, a real org context on this physical connection.
            conn.autocommit = False
            cur.execute("SET LOCAL app.current_org_id = '1'")
            cur.execute("SELECT current_setting('app.current_org_id', true)")
            assert cur.fetchone()[0] == "1"
            conn.commit()  # SET LOCAL's scope ends here

            # New transaction, SAME physical connection, nothing re-set - reproduces the residue.
            cur.execute("SELECT current_setting('app.current_org_id', true)")
            residue = cur.fetchone()[0]
            assert residue == "", (
                f"expected the historical '' residue this test exists to guard against, got "
                f"{residue!r} - if Postgres's behavior here has changed, this test's premise "
                f"needs re-checking, not the migration."
            )

            # The actual regression check: querying the RLS-protected table in this exact state
            # must not raise, and must safely return zero rows (never another tenant's data).
            cur.execute("SELECT count(*) FROM organisation_memberships")
            count = cur.fetchone()[0]
            assert count == 0
            conn.rollback()

    with psycopg.connect(_sync_app_dsn_as_plain_url(), autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_org_id = '999999999'")
            conn.commit()  # leave '' residue on app.current_org_id again

            # SET LOCAL takes a literal, not a bind parameter - seed_user_id is our own just-
            # inserted integer id (RETURNING id above), never client input, same as
            # test_rls_integration.py's identical f-string SET LOCAL pattern.
            cur.execute(f"SET LOCAL app.current_user_id = '{seed_user_id}'")
            cur.execute("SELECT count(*) FROM organisation_memberships WHERE user_id = %s", (seed_user_id,))
            count = cur.fetchone()[0]
            assert count >= 1, "self_membership_select should surface this user's own row even with '' org residue"
            conn.rollback()
