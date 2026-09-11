"""
RLS-TXN-R1: focused proofs for the central transaction-lifecycle fix in app/db/session.py.

The defect this repairs: get_db used to apply app.current_org_id exactly once, right after the
session opened. set_config's third arg (is_local=true) is SET LOCAL semantics - scoped to the
current transaction only - so a service calling db.commit() mid-request silently entered its next
transaction with no tenant context at all, and RLS correctly (but unhelpfully) denied visibility
into rows the same request just wrote.

The fix: a Session.after_begin event, scoped to a dedicated sync_session_class used only by
app/db/session.py's sessionmaker, re-applies the request's org id (carried on session.info, never
a module-global) to every transaction the session opens - not just the first.

These tests exercise app.db.session._session_factory directly (the real procureiq_app engine,
RLS FORCE-active) rather than only through HTTP, so the transaction-lifecycle behavior itself is
proven, not merely inferred from one route's success.
"""
import uuid

import pytest
from sqlalchemy import text

from app.db.session import _ORG_ID_INFO_KEY, _session_factory


async def _seed_org(db_session, name: str) -> int:
    """Raw INSERT via the admin (table-owner) connection - RLS-exempt, matching every other
    fixture's seeding convention in this suite (p03_seed, the K2 regression test)."""
    result = await db_session.execute(
        text("INSERT INTO organisations (public_id, name) VALUES (:pid, :name) RETURNING id"),
        {"pid": str(uuid.uuid4()), "name": name},
    )
    org_id = result.scalar_one()
    await db_session.commit()
    return org_id


async def _insert_supplier_as(org_id: int, legal_name: str) -> int:
    """INSERT a supplier row through the real procureiq_app-role session factory, with org_id
    carried on session.info exactly the way get_db does it - proving the after_begin hook, not a
    test-only shortcut."""
    session = _session_factory()
    session.sync_session.info[_ORG_ID_INFO_KEY] = org_id
    try:
        result = await session.execute(
            text(
                "INSERT INTO suppliers (public_id, organisation_id, legal_name, currency, active) "
                "VALUES (:pid, :org_id, :name, 'ZAR', true) RETURNING id"
            ),
            {"pid": str(uuid.uuid4()), "org_id": org_id, "name": legal_name},
        )
        supplier_id = result.scalar_one()
        await session.commit()
        return supplier_id
    finally:
        await session.close()


@pytest.mark.integration
async def test_supplier_create_returns_201_with_valid_public_id(client):
    """Proof A - the end-to-end HTTP path RLS-TXN-R1 exists to fix."""
    register_resp = await client.post(
        "/auth/register",
        json={
            "first_name": "RLS", "last_name": "Txn", "email": f"rls-txn-{uuid.uuid4()}@example.com",
            "password": "correct-horse-battery-staple", "organisation_name": "RLS-TXN-R1 Org",
        },
    )
    assert register_resp.status_code == 201
    token = register_resp.json()["access_token"]

    supplier_resp = await client.post(
        "/suppliers", json={"legal_name": "RLS-TXN-R1 Supplier", "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert supplier_resp.status_code == 201
    body = supplier_resp.json()
    assert "public_id" in body
    uuid.UUID(body["public_id"])  # a real, parseable UUID - not a placeholder/empty value


@pytest.mark.integration
async def test_multiple_commit_cycles_retain_own_org_context(db_session):
    """Proof B + C: a session's SECOND (and later) transaction, after an earlier commit, still
    carries its own org's RLS context - not just the first transaction. Writes two suppliers
    across two separate commit boundaries on the SAME session, then reads both back in a THIRD
    transaction on that same session - all three transaction boundaries must see this org's data
    and never the other org's."""
    org_a = await _seed_org(db_session, "RLS-TXN-R1 Multi-Commit Org A")
    org_b = await _seed_org(db_session, "RLS-TXN-R1 Multi-Commit Org B")
    # A row in org B that org A's session must never see, at any point below.
    await _insert_supplier_as(org_b, "Org B Decoy Supplier")

    session = _session_factory()
    session.sync_session.info[_ORG_ID_INFO_KEY] = org_a
    try:
        # Transaction 1 (this session's first - proves the base case still works).
        await session.execute(
            text("INSERT INTO suppliers (public_id, organisation_id, legal_name, currency, active) "
                 "VALUES (:pid, :org_id, 'First', 'ZAR', true)"),
            {"pid": str(uuid.uuid4()), "org_id": org_a},
        )
        await session.commit()

        # Transaction 2 - autobegins fresh after the commit above. This is exactly the boundary
        # the pre-fix code lost its RLS context across.
        await session.execute(
            text("INSERT INTO suppliers (public_id, organisation_id, legal_name, currency, active) "
                 "VALUES (:pid, :org_id, 'Second', 'ZAR', true)"),
            {"pid": str(uuid.uuid4()), "org_id": org_a},
        )
        await session.commit()

        # Transaction 3 - a read, after two commits, on the same session. Must see both of this
        # org's rows and none of org B's.
        result = await session.execute(
            text("SELECT legal_name FROM suppliers WHERE organisation_id = :org_id ORDER BY legal_name"),
            {"org_id": org_a},
        )
        names = [row[0] for row in result.all()]
        assert names == ["First", "Second"]

        result = await session.execute(text("SELECT count(*) FROM suppliers"))
        # RLS-scoped count from org A's own context - the decoy in org B must not be visible.
        assert result.scalar_one() == 2
    finally:
        await session.close()


@pytest.mark.integration
async def test_two_pooled_sessions_do_not_leak_org_context(db_session):
    """Proof D: two sessions from the same factory (the same pool _apply_tenant_context is scoped
    to) with different org contexts never see each other's rows, whether or not they happen to
    reuse the same physical pooled connection."""
    org_a = await _seed_org(db_session, "RLS-TXN-R1 Pool Org A")
    org_b = await _seed_org(db_session, "RLS-TXN-R1 Pool Org B")
    supplier_a = await _insert_supplier_as(org_a, "Pool Org A Supplier")
    supplier_b = await _insert_supplier_as(org_b, "Pool Org B Supplier")
    assert supplier_a and supplier_b

    session_a = _session_factory()
    session_a.sync_session.info[_ORG_ID_INFO_KEY] = org_a
    try:
        result = await session_a.execute(text("SELECT legal_name FROM suppliers"))
        assert [row[0] for row in result.all()] == ["Pool Org A Supplier"]
    finally:
        await session_a.close()

    session_b = _session_factory()
    session_b.sync_session.info[_ORG_ID_INFO_KEY] = org_b
    try:
        result = await session_b.execute(text("SELECT legal_name FROM suppliers"))
        assert [row[0] for row in result.all()] == ["Pool Org B Supplier"]
    finally:
        await session_b.close()


@pytest.mark.integration
async def test_session_with_no_org_context_is_fail_closed(db_session):
    """Proof E: a session that never had session.info[_ORG_ID_INFO_KEY] set (matching
    get_db_unauthenticated, or any bug that failed to set it) gets no automatic set_config call at
    all - RLS then denies every row by default, the same safe-deny K2 already established for
    empty-string residue, here for the genuinely-unset case."""
    org_a = await _seed_org(db_session, "RLS-TXN-R1 No-Context Org")
    await _insert_supplier_as(org_a, "No-Context Org Supplier")

    session = _session_factory()  # deliberately: no session.sync_session.info[_ORG_ID_INFO_KEY]
    try:
        result = await session.execute(text("SELECT count(*) FROM suppliers"))
        assert result.scalar_one() == 0
    finally:
        await session.close()
