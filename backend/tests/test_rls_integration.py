"""
RLS & DB integration suite (ADR-003, ADR-011). Spins up a real, ephemeral Postgres via
testcontainers (the same `pgvector/pgvector:pg16` image docker-compose.yml uses - not a generic
postgres image, since migration 0002's `CREATE EXTENSION "pgvector"` would fail against one),
runs the actual Alembic migrations against it, and tests the real DDL: RLS enabled *and forced*
on every tenant-scoped table, the `tenant_isolation` policy referencing the real session variable
(`app.current_org_id` - see below for why this isn't `app.current_tenant_id`), the `procureiq_app`
role's actual privileges, and an end-to-end cross-tenant leak test connecting as that role, not
as an admin/superuser (a leak test that only ever connects as an owner/superuser proves nothing
useful - RLS binds to non-owners by default with or without FORCE, so a naive version of this
test would have passed even before ADR-011's fix, for the wrong reason).

Needs Docker and network access to actually run (`pip install -e ".[dev]"` pulls testcontainers;
the container image itself needs to be pulled). Not executed in the sandbox that wrote this - see
docs/phase4-rebate-leakage-plan.md and every prior phase's tests/ directory for the same
constraint. Run with: `pytest backend/tests/test_rls_integration.py -v`.

On the two schema names in the original request that don't exist in this codebase:
- `app.current_tenant_id` -> the real variable, set in every migration since 0001 and read in
  app/db/session.py, is `app.current_org_id`. Testing a variable name the schema doesn't use
  would prove nothing - this suite tests the real one.
- `contract_clauses` -> no such table. Phase 3 built `contracts` (verified fields) and
  `contract_extractions` (AI staging, ADR-004's pattern) - this suite tests both real tables.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

# Same list as migration 0004 - kept independent (not imported from the migration) on purpose:
# this test should fail loudly if a future migration adds a tenant-scoped table and someone
# forgets to add it to *both* lists, rather than silently trusting whatever the migration itself
# claims.
TENANT_SCOPED_TABLES = (
    "organisation_memberships", "organisation_settings", "locations",
    "suppliers", "price_reviews", "price_review_files", "price_review_mapping_templates",
    "price_review_lines", "opportunities",
    "contracts", "contract_extractions", "contract_alerts",
    "rebate_agreements", "rebate_period_actuals", "rebate_alerts",
    "purchase_transactions",
    "purchase_orders", "purchase_order_lines",
    "purchase_invoices", "purchase_invoice_lines",
    "goods_receipts", "goods_receipt_lines",
    "duplicate_sku_flags", "supplier_consolidation_flags",
    "inventory_snapshots",
    "cost_allocation_rules", "cost_to_serve_ledger", "working_capital_snapshots", "aging_ledger_snapshots",
)

DEV_APP_PASSWORD = "procureiq_app_dev_only_rotate_in_production"  # must match migration 0004


def _insert_org_and_supplier(app_dsn: str, org_name: str, supplier_name: str) -> tuple[int, int]:
    """Module-level, not a private method on one test class - TestConcurrentSessionIsolation
    below needs the exact same logic, and duplicating it would risk the two versions drifting
    apart the way rebate_aggregation_service.py's pre-ADR-014 duplication did."""
    with psycopg.connect(app_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organisations (public_id, name) VALUES (gen_random_uuid(), %s) RETURNING id",
                (org_name,),
            )
            org_id = cur.fetchone()[0]
            cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
            cur.execute(
                "INSERT INTO suppliers (organisation_id, public_id, legal_name, currency) "
                "VALUES (%s, gen_random_uuid(), %s, 'ZAR') RETURNING id",
                (org_id, supplier_name),
            )
            supplier_id = cur.fetchone()[0]
            conn.commit()
    return org_id, supplier_id


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(
        "pgvector/pgvector:pg16", username="procureiq", password="procureiq", dbname="procureiq"
    ) as container:
        yield container


@pytest.fixture(scope="session")
def admin_dsn(pg_container) -> str:
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    return f"host={host} port={port} dbname=procureiq user=procureiq password=procureiq"


@pytest.fixture(scope="session")
def app_dsn(pg_container) -> str:
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    return f"host={host} port={port} dbname=procureiq user=procureiq_app password={DEV_APP_PASSWORD}"


@pytest.fixture(scope="session", autouse=True)
def run_migrations(pg_container, admin_dsn):
    """
    Runs the real Alembic migration chain (0001-0004) against the container - not a hand-rolled
    schema. If a migration is broken, this fixture fails before any test gets a chance to pass
    for the wrong reason.
    """
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    os.environ["DATABASE_URL"] = f"postgresql+asyncpg://procureiq:procureiq@{host}:{port}/procureiq"
    os.environ["DATABASE_URL_SYNC"] = f"postgresql+psycopg://procureiq:procureiq@{host}:{port}/procureiq"
    os.environ["DATABASE_URL_APP"] = (
        f"postgresql+asyncpg://procureiq_app:{DEV_APP_PASSWORD}@{host}:{port}/procureiq"
    )
    os.environ["SECRET_KEY"] = "rls-integration-test-secret"

    from app.core.config import get_settings
    get_settings.cache_clear()  # env vars above must win over anything cached from an earlier test

    from alembic.config import Config

    from alembic import command

    backend_dir = __import__("pathlib").Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")

    # A brand-new role needs a moment to be queryable in some CI/container setups - a fixed
    # sleep is not elegant, but this fixture only runs once per test session.
    time.sleep(0.5)
    yield


class TestRlsEnabledAndForced:
    """The exact check ADR-011 exists for - both flags, not just one."""

    def test_every_tenant_scoped_table_has_rls_enabled_and_forced(self, admin_dsn):
        with psycopg.connect(admin_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = ANY(%s) AND relkind = 'r'
                    """,
                (list(TENANT_SCOPED_TABLES),),
            )
            rows = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

        assert set(rows.keys()) == set(TENANT_SCOPED_TABLES), (
            f"missing tables in schema: {set(TENANT_SCOPED_TABLES) - set(rows.keys())}"
        )
        for table, (enabled, forced) in rows.items():
            assert enabled, f"{table}: ENABLE ROW LEVEL SECURITY is not set"
            assert forced, f"{table}: FORCE ROW LEVEL SECURITY is not set (ADR-011)"

    def test_tenant_isolation_policy_references_correct_session_variable(self, admin_dsn):
        with psycopg.connect(admin_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                    SELECT tablename, qual FROM pg_policies
                    WHERE schemaname = 'public' AND policyname = 'tenant_isolation'
                    """
            )
            policies = dict(cur.fetchall())

        for table in TENANT_SCOPED_TABLES:
            assert table in policies, f"{table}: no tenant_isolation policy found"
            # The real variable - see module docstring re: app.current_tenant_id not existing.
            assert "app.current_org_id" in policies[table]
            assert "app.current_tenant_id" not in policies[table]


class TestProcureiqAppRolePrivileges:
    def test_role_exists_and_is_not_superuser_and_cannot_bypass_rls(self, admin_dsn):
        with psycopg.connect(admin_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'procureiq_app'"
            )
            row = cur.fetchone()
        assert row is not None, "procureiq_app role does not exist (ADR-011)"
        rolsuper, rolbypassrls = row
        assert not rolsuper
        assert not rolbypassrls

    def test_role_does_not_own_any_tenant_scoped_table(self, admin_dsn):
        # The actual mechanism ADR-011 fixes: if this ever comes back true, FORCE ROW LEVEL
        # SECURITY is the only thing standing between procureiq_app and every other tenant's data.
        with psycopg.connect(admin_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                    SELECT c.relname FROM pg_class c
                    JOIN pg_roles r ON r.oid = c.relowner
                    WHERE r.rolname = 'procureiq_app' AND c.relname = ANY(%s)
                    """,
                (list(TENANT_SCOPED_TABLES),),
            )
            owned = [row[0] for row in cur.fetchall()]
        assert owned == [], f"procureiq_app owns tables it should not: {owned}"

    def test_role_cannot_update_or_delete_audit_logs(self, app_dsn):
        with psycopg.connect(app_dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_logs (action, entity_type, context) "
                    "VALUES ('test_action', 'test_entity', '{}'::jsonb) RETURNING id"
                )
                audit_id = cur.fetchone()[0]
                conn.commit()

            with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("UPDATE audit_logs SET action = 'tampered' WHERE id = %s", (audit_id,))
            conn.rollback()

            with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM audit_logs WHERE id = %s", (audit_id,))
            conn.rollback()

    def test_role_cannot_update_or_delete_purchase_transactions(self, app_dsn):
        # Same append-only guarantee as audit_logs (migration 0006), for the same reason
        # (ADR-006): a financial fact row is corrected by inserting a new row referencing it via
        # corrects_id, never by mutating the original. Self-contained (creates its own user row)
        # rather than assuming one exists from another test's side effects.
        with psycopg.connect(app_dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organisations (public_id, name) VALUES (gen_random_uuid(), 'PT Role Test Org') RETURNING id"
                )
                org_id = cur.fetchone()[0]
                cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
                cur.execute(
                    "INSERT INTO users (public_id, first_name, last_name, email, password_hash) "
                    "VALUES (gen_random_uuid(), 'PT', 'RoleTest', "
                    "'pt-role-test@example.com', 'unused-hash') RETURNING id"
                )
                user_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO suppliers (organisation_id, public_id, legal_name, currency) "
                    "VALUES (%s, gen_random_uuid(), 'PT Role Test Supplier', 'ZAR') RETURNING id",
                    (org_id,),
                )
                supplier_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO purchase_transactions "
                    "(organisation_id, public_id, supplier_id, transaction_date, amount, uploaded_by_user_id) "
                    "VALUES (%s, gen_random_uuid(), %s, CURRENT_DATE, 100.00, %s) RETURNING id",
                    (org_id, supplier_id, user_id),
                )
                txn_id = cur.fetchone()[0]
                conn.commit()

            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute(
                        "UPDATE purchase_transactions SET amount = 999999 WHERE id = %s", (txn_id,)
                    )
            conn.rollback()

    def test_role_cannot_update_or_delete_purchase_invoices(self, app_dsn):
        # Same append-only guarantee as purchase_transactions above, for purchase_invoices
        # (migration 0008, Phase 4c) - a posted invoice is corrected by a new invoice referencing
        # corrects_id, never by mutating the original.
        with psycopg.connect(app_dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organisations (public_id, name) VALUES (gen_random_uuid(), 'PI Role Test Org') RETURNING id"
                )
                org_id = cur.fetchone()[0]
                cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
                cur.execute(
                    "INSERT INTO users (public_id, first_name, last_name, email, password_hash) "
                    "VALUES (gen_random_uuid(), 'PI', 'RoleTest', 'pi-role-test@example.com', 'unused-hash') "
                    "RETURNING id"
                )
                user_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO suppliers (organisation_id, public_id, legal_name, currency) "
                    "VALUES (%s, gen_random_uuid(), 'PI Role Test Supplier', 'ZAR') RETURNING id",
                    (org_id,),
                )
                supplier_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO purchase_invoices "
                    "(organisation_id, public_id, supplier_id, invoice_number, invoice_date, uploaded_by_user_id) "
                    "VALUES (%s, gen_random_uuid(), %s, 'INV-TEST-001', CURRENT_DATE, %s) RETURNING id",
                    (org_id, supplier_id, user_id),
                )
                invoice_id = cur.fetchone()[0]
                conn.commit()

            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute(
                        "UPDATE purchase_invoices SET invoice_number = 'TAMPERED' WHERE id = %s",
                        (invoice_id,),
                    )
            conn.rollback()


class TestCrossTenantIsolation:
    """
    The actual isolation proof - connecting AS procureiq_app (never as admin/superuser, per the
    module docstring's note on why that distinction is the whole point), inserting two
    organisations' data, and confirming SET LOCAL app.current_org_id strictly scopes every query.
    """

    def test_supplier_rows_are_invisible_across_orgs(self, app_dsn):
        org_a_id, _ = _insert_org_and_supplier(app_dsn, "RLS Test Org A", "RLS Test Supplier A")
        org_b_id, _ = _insert_org_and_supplier(app_dsn, "RLS Test Org B", "RLS Test Supplier B")

        with psycopg.connect(app_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_a_id}'")
                cur.execute("SELECT legal_name FROM suppliers")
                names_visible_to_a = {row[0] for row in cur.fetchall()}

            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_b_id}'")
                cur.execute("SELECT legal_name FROM suppliers")
                names_visible_to_b = {row[0] for row in cur.fetchall()}

        assert "RLS Test Supplier A" in names_visible_to_a
        assert "RLS Test Supplier B" not in names_visible_to_a
        assert "RLS Test Supplier B" in names_visible_to_b
        assert "RLS Test Supplier A" not in names_visible_to_b

    def test_no_session_variable_set_returns_no_rows_not_all_rows(self, app_dsn):
        # A missing/unset session variable must fail closed (nothing visible), never fail open
        # (everything visible) - this is what `current_setting(..., true)`'s NULL-on-missing
        # behavior in the policy is supposed to guarantee. Worth its own explicit test rather
        # than an assumption.
        _insert_org_and_supplier(app_dsn, "RLS Test Org C", "RLS Test Supplier C")
        with psycopg.connect(app_dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT legal_name FROM suppliers")
            rows = cur.fetchall()
        assert rows == []

    def test_cross_tenant_update_is_blocked_not_just_select(self, app_dsn):
        # RLS policies in this schema use USING only (no WITH CHECK) - meaning the SELECT side
        # is proven above, but an UPDATE targeting another tenant's row by primary key must also
        # affect zero rows, not raise, and not silently succeed.
        org_a_id, supplier_a_id = _insert_org_and_supplier(app_dsn, "RLS Test Org D", "RLS Test Supplier D")
        org_b_id, _ = _insert_org_and_supplier(app_dsn, "RLS Test Org E", "RLS Test Supplier E")

        with psycopg.connect(app_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_b_id}'")
                cur.execute(
                    "UPDATE suppliers SET legal_name = 'TAMPERED' WHERE id = %s", (supplier_a_id,)
                )
                assert cur.rowcount == 0, "org B's session updated org A's row - RLS failed"
            conn.rollback()


class TestForceRlsMechanismDemonstration:
    """
    Not testing any real application table - a throwaway scratch table demonstrating the exact
    mechanism ADR-011 fixes, so this suite proves understanding of *why* FORCE matters, not just
    that it's present. Connects as the owning (admin) role deliberately, since that's the only
    way to observe the difference ENABLE-without-FORCE makes.
    """

    def test_enable_without_force_leaks_to_the_owning_role(self, admin_dsn):
        with psycopg.connect(admin_dsn) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS rls_demo_scratch")
                cur.execute(
                    "CREATE TABLE rls_demo_scratch (id serial primary key, tenant_id int, value text)"
                )
                cur.execute("ALTER TABLE rls_demo_scratch ENABLE ROW LEVEL SECURITY")  # no FORCE
                cur.execute(
                    "CREATE POLICY t ON rls_demo_scratch USING (tenant_id = current_setting('app.demo_tenant', true)::int)"
                )
                cur.execute("INSERT INTO rls_demo_scratch (tenant_id, value) VALUES (1, 'secret-a'), (2, 'secret-b')")
                cur.execute("SET app.demo_tenant = '1'")
                cur.execute("SELECT value FROM rls_demo_scratch")
                # The owning role sees BOTH rows despite the policy - this is the exact gap
                # ADR-011 found in the real schema, reproduced deliberately here.
                values = {row[0] for row in cur.fetchall()}
        assert values == {"secret-a", "secret-b"}, (
            "expected the owner to see both rows without FORCE - if this fails, Postgres's "
            "behavior here has changed and ADR-011's reasoning needs re-checking, not this test"
        )

    def test_force_fixes_the_leak_for_the_same_owning_role(self, admin_dsn):
        with psycopg.connect(admin_dsn) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE rls_demo_scratch FORCE ROW LEVEL SECURITY")
                cur.execute("SET app.demo_tenant = '1'")
                cur.execute("SELECT value FROM rls_demo_scratch")
                values = {row[0] for row in cur.fetchall()}
                cur.execute("DROP TABLE rls_demo_scratch")
        assert values == {"secret-a"}, "FORCE did not restrict the owning role - fix did not work"


class TestConcurrentSessionIsolation:
    """
    Phase 2 of the ground-truth engineering plan: RLS under real concurrent load, not just
    sequential SET LOCAL checks (TestCrossTenantIsolation above proves the policy is correct in
    principle; this class proves it holds when many real, separate connections are actually
    hammering the same tables at the same time - the scenario a production connection pool
    creates and a sequential test cannot exercise).

    Real OS threads with real, separate psycopg connections per thread - not asyncio. psycopg's
    blocking network I/O releases the GIL during each round-trip, so genuine interleaving between
    threads happens without needing to fake it; a threading.Barrier is used only to maximize the
    *chance* of overlap on each iteration, not to simulate it.
    """

    def test_concurrent_reads_across_many_organisations_never_leak_under_load(self, app_dsn):
        org_count = 6
        iterations_per_org = 25
        supplier_names = [f"Concurrency Supplier {i}" for i in range(org_count)]
        org_ids = [
            _insert_org_and_supplier(app_dsn, f"Concurrency Org {i}", supplier_names[i])[0]
            for i in range(org_count)
        ]
        barrier = threading.Barrier(org_count)

        def worker(org_id: int, expected_name: str) -> None:
            with psycopg.connect(app_dsn) as conn:
                for _ in range(iterations_per_org):
                    barrier.wait()  # maximize overlap with every other worker's query this round
                    with conn.cursor() as cur:
                        cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
                        cur.execute("SELECT legal_name FROM suppliers")
                        visible = {row[0] for row in cur.fetchall()}
                    conn.rollback()  # end the SET LOCAL's transaction scope explicitly each round
                    assert visible == {expected_name}, (
                        f"org {org_id} saw {visible - {expected_name}} belonging to another org"
                    )

        with ThreadPoolExecutor(max_workers=org_count) as pool:
            futures = [
                pool.submit(worker, org_id, name) for org_id, name in zip(org_ids, supplier_names)
            ]
            for future in as_completed(futures):
                future.result()  # re-raises inside the main thread if any worker's assertion failed

    def test_concurrent_interleaved_writes_produce_correct_per_org_row_counts(self, app_dsn):
        org_count = 4
        inserts_per_org = 15
        orgs = [
            _insert_org_and_supplier(app_dsn, f"Write Concurrency Org {i}", f"Write Concurrency Seed Supplier {i}")
            for i in range(org_count)
        ]
        barrier = threading.Barrier(org_count)

        def writer(org_id: int) -> None:
            with psycopg.connect(app_dsn) as conn:
                for n in range(inserts_per_org):
                    barrier.wait()
                    with conn.cursor() as cur:
                        cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
                        cur.execute(
                            "INSERT INTO suppliers (organisation_id, public_id, legal_name, currency) "
                            "VALUES (%s, gen_random_uuid(), %s, 'ZAR')",
                            (org_id, f"Write Concurrency Row {org_id}-{n}"),
                        )
                    conn.commit()

        with ThreadPoolExecutor(max_workers=org_count) as pool:
            futures = [pool.submit(writer, org_id) for org_id, _ in orgs]
            for future in as_completed(futures):
                future.result()

        # +1 per org for the seed supplier _insert_org_and_supplier already created.
        for org_id, _ in orgs:
            with psycopg.connect(app_dsn) as conn, conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_id}'")
                cur.execute("SELECT count(*) FROM suppliers")
                count = cur.fetchone()[0]
            assert count == inserts_per_org + 1, (
                f"org {org_id} has {count} supplier rows, expected {inserts_per_org + 1} - "
                f"a concurrent write race either dropped or leaked rows across organisations"
            )

    def test_set_local_resets_cleanly_when_a_physical_connection_is_reused_across_different_orgs(self, app_dsn):
        """
        Not multi-threaded - the realistic bug this test actually targets doesn't need
        concurrency to reproduce, only connection reuse: a pooled connection serving Org A's
        request, then immediately serving Org B's request on the exact same TCP connection. If
        SET LOCAL's transaction-scoped reset ever failed to fully clear between transactions on
        one physical connection, this is the test that would catch it - the multi-threaded tests
        above use a fresh connection per thread and would never exercise this specific path.
        """
        org_a_id, _ = _insert_org_and_supplier(app_dsn, "Reuse Org A", "Reuse Supplier A")
        org_b_id, _ = _insert_org_and_supplier(app_dsn, "Reuse Org B", "Reuse Supplier B")

        with psycopg.connect(app_dsn) as conn:
            # "Request" 1: serves Org A.
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_a_id}'")
                cur.execute("SELECT legal_name FROM suppliers")
                visible_to_a = {row[0] for row in cur.fetchall()}
            conn.commit()  # transaction ends - SET LOCAL's scope ends with it

            # "Request" 2: the SAME physical connection, immediately reused for Org B.
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_b_id}'")
                cur.execute("SELECT legal_name FROM suppliers")
                visible_to_b = {row[0] for row in cur.fetchall()}
            conn.commit()

            # "Request" 3: back to Org A on the same connection again.
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL app.current_org_id = '{org_a_id}'")
                cur.execute("SELECT legal_name FROM suppliers")
                visible_to_a_again = {row[0] for row in cur.fetchall()}
            conn.commit()

        assert visible_to_a == {"Reuse Supplier A"}
        assert visible_to_b == {"Reuse Supplier B"}
        assert visible_to_a_again == {"Reuse Supplier A"}
