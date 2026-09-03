"""Phase 5b (ADR-018): inventory_snapshots, append-only (ADR-006). Grain (description,
supplier_sku, location_id, snapshot_date) - no DB-level UNIQUE constraint on the grain (see
InventorySnapshot's docstring for why); the pure validate_snapshot_grain check flags violations
explicitly instead. RLS ENABLE+FORCE+grants from creation (ADR-011).

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("location_id", sa.BigInteger(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("supplier_sku", sa.String(128)),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("quantity_on_hand", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 4)),
        sa.Column("reorder_level", sa.Numeric(18, 4)),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("inventory_snapshots.id")),
        sa.Column("source_file_storage_key", sa.String(512)),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_inventory_snapshots_org", "inventory_snapshots", ["organisation_id"])
    op.create_index("ix_inventory_snapshots_location", "inventory_snapshots", ["location_id"])
    op.create_index("ix_inventory_snapshots_date", "inventory_snapshots", ["snapshot_date"])
    # Supports the grain lookup pattern (one item, one location, across dates) that
    # calculate_days_since_last_movement's caller will need - not a uniqueness constraint,
    # purely for query performance.
    op.create_index(
        "ix_inventory_snapshots_grain_lookup", "inventory_snapshots",
        ["organisation_id", "location_id", "description", "snapshot_date"],
    )

    op.execute("ALTER TABLE inventory_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE inventory_snapshots FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON inventory_snapshots
        USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                -- Append-only (ADR-006) - no UPDATE/DELETE, same as purchase_transactions/
                -- purchase_invoices/goods_receipts. A bad snapshot is corrected by a new row
                -- referencing corrects_id, never mutated.
                GRANT SELECT, INSERT ON inventory_snapshots TO procureiq_app;
                GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO procureiq_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON inventory_snapshots")
    op.drop_table("inventory_snapshots")
