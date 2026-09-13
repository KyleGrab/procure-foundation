"""Multidimensional Cost-to-Serve execution engine: route_profitability_snapshots, append-only
(ADR-006), storing real trip-level revenue/COGS and the three granular cost pools (trip fixed,
distance variable, activity time) plus the computed net_net_profit. customer_id is String(128),
not a FK - no customers table exists in this schema, matching cost_to_serve_ledger's established
precedent. location_id is a real integer FK to locations.id, per this schema's standard internal-
relationship convention.

Written, not executed - no live Postgres in this sandbox, unchanged all sprint.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_profitability_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("trip_date", sa.Date(), nullable=False),
        sa.Column("location_id", sa.BigInteger(), sa.ForeignKey("locations.id")),
        sa.Column("customer_id", sa.String(128)),
        sa.Column("vehicle_registration", sa.String(32)),
        sa.Column("route_reference", sa.String(64)),
        sa.Column("revenue", sa.Numeric(18, 4), nullable=False),
        sa.Column("cogs", sa.Numeric(18, 4), nullable=False),
        sa.Column("trade_spend", sa.Numeric(18, 4), nullable=False),
        sa.Column("revenue_basis", sa.String(16), nullable=False),
        sa.Column("trip_fixed_costs", sa.Numeric(18, 4), nullable=False),
        sa.Column("distance_variable_costs", sa.Numeric(18, 4), nullable=False),
        sa.Column("activity_time_costs", sa.Numeric(18, 4), nullable=False),
        sa.Column("net_net_profit", sa.Numeric(18, 4), nullable=False),
        sa.Column("is_net_revenue_negative", sa.Boolean(), nullable=False),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("route_profitability_snapshots.id")),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_route_profitability_snapshots_org", "route_profitability_snapshots", ["organisation_id"])
    op.create_index("ix_route_profitability_snapshots_date", "route_profitability_snapshots", ["trip_date"])
    op.create_index("ix_route_profitability_snapshots_customer", "route_profitability_snapshots", ["customer_id"])

    op.execute("ALTER TABLE route_profitability_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE route_profitability_snapshots FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON route_profitability_snapshots
        USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                GRANT SELECT, INSERT ON route_profitability_snapshots TO procureiq_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON route_profitability_snapshots")
    op.drop_table("route_profitability_snapshots")
