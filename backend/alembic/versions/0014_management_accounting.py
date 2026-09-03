"""Management accounting: cost_allocation_rules (mutable config), cost_to_serve_ledger,
working_capital_snapshots, aging_ledger_snapshots (all append-only, ADR-006). RLS ENABLE+FORCE+
grants from creation (ADR-011). Written, not executed - no live Postgres exists in the sandbox
that authored this migration; execution is the next real environment's job.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_MUTABLE_TABLES = ("cost_allocation_rules",)
_APPEND_ONLY_TABLES = ("cost_to_serve_ledger", "working_capital_snapshots", "aging_ledger_snapshots")


def upgrade() -> None:
    op.create_table(
        "cost_allocation_rules",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("cost_category", sa.String(64), nullable=False),
        sa.Column("allocation_method", sa.String(32), nullable=False),
        sa.Column("default_unit_rate", sa.Numeric(18, 4)),
        sa.Column("set_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cost_allocation_rules_org", "cost_allocation_rules", ["organisation_id"])

    op.create_table(
        "cost_to_serve_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("invoice_id", sa.String(128)),
        sa.Column("order_id", sa.String(128)),
        sa.Column("customer_id", sa.String(128)),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id")),
        sa.Column("net_revenue", sa.Numeric(18, 4), nullable=False),
        sa.Column("cogs", sa.Numeric(18, 4), nullable=False),
        sa.Column("direct_logistics_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("allocated_warehouse_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("allocated_overhead_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("net_margin", sa.Numeric(18, 4), nullable=False),
        sa.Column("net_margin_pct", sa.Numeric(9, 4)),
        sa.Column("allocation_level", sa.String(16), nullable=False),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("cost_to_serve_ledger.id")),
        sa.Column("source_file_storage_key", sa.String(512)),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cost_to_serve_ledger_org", "cost_to_serve_ledger", ["organisation_id"])
    op.create_index("ix_cost_to_serve_ledger_customer", "cost_to_serve_ledger", ["customer_id"])

    op.create_table(
        "working_capital_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("accounts_receivable", sa.Numeric(18, 4), nullable=False),
        sa.Column("accounts_payable", sa.Numeric(18, 4), nullable=False),
        sa.Column("inventory_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("cash_balance", sa.Numeric(18, 4)),
        sa.Column("annualized_revenue", sa.Numeric(18, 4), nullable=False),
        sa.Column("annualized_cogs", sa.Numeric(18, 4), nullable=False),
        sa.Column("dso", sa.Numeric(9, 1)),
        sa.Column("dio", sa.Numeric(9, 1)),
        sa.Column("dpo", sa.Numeric(9, 1)),
        sa.Column("ccc", sa.Numeric(9, 1)),
        sa.Column("working_capital_ratio", sa.Numeric(9, 2)),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("working_capital_snapshots.id")),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_working_capital_snapshots_org", "working_capital_snapshots", ["organisation_id"])
    op.create_index("ix_working_capital_snapshots_date", "working_capital_snapshots", ["as_of_date"])

    op.create_table(
        "aging_ledger_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ledger_type", sa.String(16), nullable=False),
        sa.Column("current_balance", sa.Numeric(18, 4), nullable=False),
        sa.Column("days_30", sa.Numeric(18, 4), nullable=False),
        sa.Column("days_60", sa.Numeric(18, 4), nullable=False),
        sa.Column("days_90", sa.Numeric(18, 4), nullable=False),
        sa.Column("days_120_plus", sa.Numeric(18, 4), nullable=False),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("aging_ledger_snapshots.id")),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_aging_ledger_snapshots_org", "aging_ledger_snapshots", ["organisation_id"])
    op.create_index("ix_aging_ledger_snapshots_date", "aging_ledger_snapshots", ["as_of_date"])

    all_tables = _MUTABLE_TABLES + _APPEND_ONLY_TABLES
    for table in all_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
            """
        )

    for table in _MUTABLE_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO procureiq_app;
                END IF;
            END $$;
            """
        )
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                    GRANT SELECT, INSERT ON {table} TO procureiq_app;
                END IF;
            END $$;
            """
        )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO procureiq_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    all_tables = _MUTABLE_TABLES + _APPEND_ONLY_TABLES
    for table in reversed(all_tables):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("aging_ledger_snapshots")
    op.drop_table("working_capital_snapshots")
    op.drop_table("cost_to_serve_ledger")
    op.drop_table("cost_allocation_rules")
