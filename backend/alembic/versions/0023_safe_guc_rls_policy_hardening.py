"""SG1: repo-wide safe-GUC hardening for the remaining tenant_isolation policies.

Migration 0022 fixed exactly one table (organisation_memberships) against a real, reproduced
defect: once a custom GUC has been `SET LOCAL`'d at least once on a physical connection,
Postgres returns '' (not NULL) for it after that transaction ends, and every request-serving
role shares one connection pool - so a reused connection can carry that '' residue into a later
request. `current_setting('app.current_org_id', true)::bigint` then raises
`invalid input syntax for type bigint: ""` - a hard SQL error, not a safe deny.

The SG1 investigation inventoried every tenant_isolation policy in the schema (35 total, via both
migration-source inspection and live pg_policies inspection - both in exact agreement) and found
34 more carrying the identical unguarded expression, all with identical shape: FOR ALL,
PERMISSIVE, roles={public}, WITH CHECK NULL (Postgres derives WITH CHECK from USING when none is
given - confirmed empirically, both before and after 0022). organisation_memberships is excluded
here - it is already safe (0022) and is not touched by this migration at all.

Uses ALTER POLICY, not DROP+CREATE: since WITH CHECK is NULL for every one of these (never
explicitly set), altering only the USING expression updates both the row-visibility semantics
(SELECT/UPDATE/DELETE) and the row-acceptance semantics (INSERT/UPDATE) together, automatically -
exactly the same derivation 0022 already relies on for organisation_memberships. ALTER POLICY
also cannot change command scope, permissive/restrictive mode, or roles even by accident, which a
34-times-repeated DROP+CREATE block would risk on a copy/paste error.

No GRANT/REVOKE, no ownership change, no ENABLE/FORCE RLS change, no schema change, no accounting
logic change. The only semantic difference, for every one of these 34 tables:

BEFORE: an unset/empty-residue app.current_org_id can raise a bigint cast error.
AFTER:  an unset/empty-residue app.current_org_id resolves through NULLIF to SQL NULL, and the
        policy evaluates to its already-existing safe deny (no rows visible, no write accepted) -
        never an error. A valid organisation id continues to behave identically to before.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-10
"""
from __future__ import annotations

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# Deterministic, explicit list - not discovered at migration execution time. Independently
# re-derived from live pg_policies against the authoritative-source-migrated database
# immediately before writing this migration (35 tenant_isolation policies total; 1 already safe -
# organisation_memberships, excluded below on purpose; these are the other 34).
_UNSAFE_TENANT_ISOLATION_TABLES = (
    "aging_ledger_snapshots",
    "contract_alerts",
    "contract_extractions",
    "contracts",
    "cost_allocation_rules",
    "cost_to_serve_ledger",
    "duplicate_sku_flags",
    "financial_amount_evidence",
    "financial_amount_status_events",
    "fx_transaction_snapshots",
    "goods_receipt_lines",
    "goods_receipts",
    "inventory_reconciliation_bridges",
    "inventory_reconciliations",
    "inventory_snapshots",
    "locations",
    "opportunities",
    "organisation_settings",
    "price_review_files",
    "price_review_lines",
    "price_review_mapping_templates",
    "price_reviews",
    "purchase_invoice_lines",
    "purchase_invoices",
    "purchase_order_lines",
    "purchase_orders",
    "purchase_transactions",
    "rebate_agreements",
    "rebate_alerts",
    "rebate_period_actuals",
    "route_profitability_snapshots",
    "supplier_consolidation_flags",
    "suppliers",
    "working_capital_snapshots",
)


def upgrade() -> None:
    for table in _UNSAFE_TENANT_ISOLATION_TABLES:
        op.execute(
            f"""
            ALTER POLICY tenant_isolation ON {table}
            USING (
                organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint
            )
            """
        )


def downgrade() -> None:
    for table in _UNSAFE_TENANT_ISOLATION_TABLES:
        op.execute(
            f"""
            ALTER POLICY tenant_isolation ON {table}
            USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
            """
        )
