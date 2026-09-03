"""Gate A: inventory_reconciliations + inventory_reconciliation_bridges. Persists what
check_inventory_reconciliation/resolve_gated_inventory_value/refuse_timing_bridge_allocation
already compute (real, tested since the Chaos Audit) - this migration adds no new reconciliation
logic, only a durable record of a period's result.

Deliberately seeds NO data. A prior document presented R21,399,596.84 as a "required record" for
August 2026 - that figure was already identified as fabricated earlier in this engagement (it
rounds to a previously-rejected R21.4M placeholder, and the source Inventory Valuation Report has
been unreadable this entire engagement: no xlrd, no network, never successfully read). The one
real, independently-verified figure available is R21,895,070.82 (the actual Balance Sheet
control total) - even that is a service-layer decision to insert when real data exists, not
something this migration hard-codes.

inventory_reconciliation_bridges has no product/customer/location/warehouse/route column at
all - not nullable, genuinely absent - matching refuse_timing_bridge_allocation's principle that
an unallocated reconciliation gap must be structurally impossible to allocate to any entity.

Written, not executed - no live Postgres in this sandbox, unchanged all engagement.

Revision ID: 0020
Revises: 0019
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_reconciliations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("valuation_basis", sa.String(32), nullable=False, server_default="moving_average_cost"),
        sa.Column("raw_subledger_total", sa.Numeric(18, 4)),
        sa.Column("gl_control_total", sa.Numeric(18, 4)),
        sa.Column("bridge_total", sa.Numeric(18, 4)),
        sa.Column("reconciled_total", sa.Numeric(18, 4)),
        sa.Column("final_variance", sa.Numeric(18, 4)),
        sa.Column("tolerance", sa.Numeric(18, 4), nullable=False, server_default="0.01"),
        sa.Column("raw_detail_row_count", sa.Integer()),
        sa.Column("bridge_row_count", sa.Integer()),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("inventory_reconciliations.id"), unique=True),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_inv_recon_valuation_basis", "inventory_reconciliations",
        "valuation_basis = 'moving_average_cost'",
    )
    op.create_check_constraint(
        "ck_inv_recon_reconciled_identity", "inventory_reconciliations",
        "reconciled_total = raw_subledger_total + bridge_total",
    )
    op.create_check_constraint(
        "ck_inv_recon_variance_identity", "inventory_reconciliations",
        "final_variance = reconciled_total - gl_control_total",
    )
    op.create_index(
        "uq_inv_recon_root_per_org_date", "inventory_reconciliations",
        ["organisation_id", "snapshot_date"], unique=True, postgresql_where=sa.text("corrects_id IS NULL"),
    )
    op.create_index("ix_inv_recon_org", "inventory_reconciliations", ["organisation_id"])

    op.create_table(
        "inventory_reconciliation_bridges",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("reconciliation_id", sa.BigInteger(), sa.ForeignKey("inventory_reconciliations.id"), nullable=False),
        sa.Column("reference_code", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False, server_default="GL_SUBLEDGER_TIMING_VARIANCE"),
        sa.Column("allocation_scope", sa.String(32), nullable=False, server_default="organisation_unallocated"),
        sa.Column("evidence_checksum", sa.String(128)),
        sa.Column("source_reference", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_inv_recon_bridge_reason", "inventory_reconciliation_bridges",
        "reason_code = 'GL_SUBLEDGER_TIMING_VARIANCE'",
    )
    op.create_check_constraint(
        "ck_inv_recon_bridge_scope", "inventory_reconciliation_bridges",
        "allocation_scope = 'organisation_unallocated'",
    )
    op.create_index("ix_inv_recon_bridge_org", "inventory_reconciliation_bridges", ["organisation_id"])
    op.create_index(
        "ix_inv_recon_bridge_reconciliation", "inventory_reconciliation_bridges", ["reconciliation_id"]
    )

    for table in ("inventory_reconciliations", "inventory_reconciliation_bridges"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
            """
        )
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


def downgrade() -> None:
    for table in ("inventory_reconciliation_bridges", "inventory_reconciliations"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("inventory_reconciliation_bridges")
    op.drop_table("inventory_reconciliations")
