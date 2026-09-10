"""
SG1: permanent regression surface for the repo-wide safe-GUC RLS retrofit (migration 0023).

Deliberately does NOT import migration 0023's own table tuple - the expected inventory below is
independently typed so a mistake in the migration (a dropped table, a wrong name, a missed
policy) cannot silently make this test agree with the same mistake. Cross-checks entirely
against live pg_catalog/pg_policies on the real, Alembic-migrated database, through the real
procureiq_app role - same evidentiary standard as test_rls_integration.py and
test_k2_auth_membership_rls.py, both left untouched by this file.

Run with: pytest backend/tests/test_sg1_repo_wide_guc_safety.py -v
"""
from __future__ import annotations

import psycopg

from app.core.config import get_settings

# Independently re-typed, not imported from the migration - the entire point of this list is to
# catch a migration mistake, not agree with it. All 35 tables that carry a tenant_isolation
# policy today (34 hardened by 0023 + organisation_memberships, already hardened by 0022).
EXPECTED_TENANT_ISOLATION_TABLES = {
    "organisation_memberships",  # 0022 - excluded from 0023, must remain untouched by it
    "organisation_settings", "locations",
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
    "route_profitability_snapshots",
    "fx_transaction_snapshots",
    "inventory_reconciliations", "inventory_reconciliation_bridges",
    "financial_amount_status_events", "financial_amount_evidence",
}

# Append-only tables (ADR-006): SELECT + INSERT only, never UPDATE/DELETE for procureiq_app.
EXPECTED_APPEND_ONLY_GRANTS = {
    "purchase_transactions": {"SELECT", "INSERT"},
    "purchase_invoices": {"SELECT", "INSERT"},
    "purchase_invoice_lines": {"SELECT", "INSERT"},
    "goods_receipts": {"SELECT", "INSERT"},
    "goods_receipt_lines": {"SELECT", "INSERT"},
}


def _admin_dsn() -> str:
    return get_settings().database_url_sync.replace("postgresql+psycopg://", "postgresql://", 1)


def _app_dsn() -> str:
    return get_settings().database_url_app.replace("postgresql+asyncpg://", "postgresql://", 1)


def test_every_expected_tenant_isolation_policy_exists_and_is_empty_string_safe():
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename, cmd, permissive, roles, qual, with_check FROM pg_policies "
                "WHERE schemaname='public' AND policyname='tenant_isolation'"
            )
            rows = {r[0]: r for r in cur.fetchall()}

    assert set(rows.keys()) == EXPECTED_TENANT_ISOLATION_TABLES, (
        f"tenant_isolation policy set drifted from the independently-encoded expected set - "
        f"missing: {EXPECTED_TENANT_ISOLATION_TABLES - set(rows)}, "
        f"unexpected: {set(rows) - EXPECTED_TENANT_ISOLATION_TABLES}"
    )
    assert len(rows) == 35

    vulnerable = []
    for table, (_, cmd, permissive, roles, qual, with_check) in rows.items():
        assert cmd == "ALL", f"{table}: expected FOR ALL, got {cmd}"
        assert permissive == "PERMISSIVE", f"{table}: expected PERMISSIVE, got {permissive}"
        assert roles == ["public"], f"{table}: expected roles=[public], got {roles}"
        assert with_check is None, f"{table}: expected WITH CHECK to remain NULL (derived), got {with_check}"
        assert "app.current_org_id" in qual, f"{table}: qual no longer references app.current_org_id: {qual}"
        if "NULLIF" not in qual:
            vulnerable.append(table)

    assert vulnerable == [], f"still-vulnerable (non-NULLIF) tenant_isolation policies remain: {vulnerable}"


def test_organisation_memberships_untouched_by_0023():
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT policyname, cmd, qual, with_check FROM pg_policies "
                "WHERE schemaname='public' AND tablename='organisation_memberships' "
                "ORDER BY policyname"
            )
            rows = cur.fetchall()

    by_name = {r[0]: r for r in rows}
    assert set(by_name) == {"self_membership_select", "tenant_isolation"}, by_name

    _, cmd, qual, with_check = by_name["tenant_isolation"]
    assert cmd == "ALL"
    assert with_check is None
    assert "NULLIF(current_setting('app.current_org_id'::text, true), ''::text)" in qual

    _, cmd, qual, with_check = by_name["self_membership_select"]
    assert cmd == "SELECT", "self_membership_select must remain SELECT-only - it must never gain write scope"
    assert with_check is None
    assert "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)" in qual


def test_no_unexpected_rls_policies_were_added_or_removed():
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public'")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity"
            )
            rls_tables = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity"
            )
            force_tables = cur.fetchone()[0]

    assert total == 36, f"expected exactly 36 policies (35 tenant_isolation + 1 self_membership_select), got {total}"
    assert rls_tables == 35
    assert force_tables == 35


def test_procureiq_app_role_invariants_unchanged():
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='procureiq_app'")
            rolsuper, rolbypassrls = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
                "WHERE r.rolname='procureiq_app' AND c.relkind='r'"
            )
            owned = cur.fetchone()[0]

    assert rolsuper is False
    assert rolbypassrls is False
    assert owned == 0


def test_append_only_privileges_unchanged():
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            for table, expected in EXPECTED_APPEND_ONLY_GRANTS.items():
                cur.execute(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee='procureiq_app' AND table_name=%s",
                    (table,),
                )
                actual = {r[0] for r in cur.fetchall()}
                assert actual == expected, f"{table}: expected grants {expected}, got {actual}"


# --------------------------------------------------------------------------------------------
# Runtime falsification: locations (chosen to match the exact table SG1 already used) - proves
# the actual defect is closed, not merely that the SQL text looks right.
# --------------------------------------------------------------------------------------------

def test_locations_valid_org_and_cross_tenant_and_empty_string_residue():
    with psycopg.connect(_admin_dsn(), autocommit=True) as admin_conn:
        with admin_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organisations (public_id, name) VALUES (gen_random_uuid(), 'SG1-R1 Org A') RETURNING id"
            )
            org_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO organisations (public_id, name) VALUES (gen_random_uuid(), 'SG1-R1 Org B') RETURNING id"
            )
            org_b = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO locations (public_id, organisation_id, code, name, location_type) "
                "VALUES (gen_random_uuid(), %s, 'SG1-R1-A', 'SG1-R1 Location A', 'warehouse')",
                (org_a,),
            )
            cur.execute(
                "INSERT INTO locations (public_id, organisation_id, code, name, location_type) "
                "VALUES (gen_random_uuid(), %s, 'SG1-R1-B', 'SG1-R1 Location B', 'warehouse')",
                (org_b,),
            )

    try:
        with psycopg.connect(_app_dsn(), autocommit=True) as conn:
            with conn.cursor() as cur:
                conn.autocommit = False

                # C first, deliberately: truly unset GUC, on a genuinely never-touched physical
                # connection - safe deny, not an error. Must run before A/B, which are what
                # first touch this GUC on this connection at all.
                cur.execute("SELECT current_setting('app.current_org_id', true)")
                assert cur.fetchone()[0] is None
                cur.execute("SELECT count(*) FROM locations WHERE organisation_id IN (%s, %s)", (org_a, org_b))
                assert cur.fetchone()[0] == 0
                conn.rollback()

                # A. Valid org - Org A's own row is visible.
                cur.execute(f"SET LOCAL app.current_org_id = '{org_a}'")
                cur.execute("SELECT code FROM locations WHERE organisation_id = %s", (org_a,))
                assert {r[0] for r in cur.fetchall()} == {"SG1-R1-A"}
                conn.rollback()

                # B. Cross-tenant - Org B's context must never see Org A's row.
                cur.execute(f"SET LOCAL app.current_org_id = '{org_b}'")
                cur.execute("SELECT code FROM locations WHERE organisation_id = %s", (org_a,))
                assert cur.fetchall() == []
                conn.rollback()

                # D. Empty-string residue on a REUSED physical connection - the actual defect.
                # (A/B above already proved, incidentally, that a ROLLBACK-ended SET LOCAL also
                # leaves this same '' residue, not just COMMIT - current_setting after B's
                # rollback would already read '' here too; COMMIT is used explicitly anyway to
                # match the exact scenario K2/SG1's own falsification evidence reproduced.)
                cur.execute(f"SET LOCAL app.current_org_id = '{org_a}'")
                conn.commit()  # SET LOCAL's scope ends here
                cur.execute("SELECT current_setting('app.current_org_id', true)")
                assert cur.fetchone()[0] == "", "test premise broken - Postgres's residue behavior changed"

                cur.execute("SELECT count(*) FROM locations WHERE organisation_id IN (%s, %s)", (org_a, org_b))
                assert cur.fetchone()[0] == 0  # safe deny, and critically: no exception raised getting here
                conn.rollback()
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute("DELETE FROM locations WHERE organisation_id IN (%s, %s)", (org_a, org_b))
                cur.execute("DELETE FROM organisations WHERE id IN (%s, %s)", (org_a, org_b))
