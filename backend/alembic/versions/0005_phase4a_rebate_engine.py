"""Phase 4a: rebate_agreements, rebate_period_actuals, rebate_alerts - RLS (ENABLE + FORCE per
ADR-011, not just ENABLE like 0001-0003 originally had it) and procureiq_app grants applied in
the same migration that creates the tables, not as a follow-up - the whole point of ADR-011 was
that a gap between "table exists" and "table is actually protected" is exactly the risk.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_RLS_TABLES = ("rebate_agreements", "rebate_period_actuals", "rebate_alerts")


def upgrade() -> None:
    op.create_table(
        "rebate_agreements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), sa.ForeignKey("contracts.id")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("rebate_type", sa.String(32), nullable=False),
        sa.Column("period_type", sa.String(16), nullable=False, server_default="quarterly"),
        sa.Column("flat_rate_pct", sa.Numeric(9, 6)),
        sa.Column("bands", postgresql.JSONB()),
        sa.Column("fixed_amount", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "rebate_type NOT IN ('fixed_percentage','volume','growth') OR flat_rate_pct IS NOT NULL",
            name="ck_rebate_flat_rate_required",
        ),
        sa.CheckConstraint(
            "rebate_type NOT IN ('tiered','retrospective') OR bands IS NOT NULL",
            name="ck_rebate_bands_required",
        ),
        sa.CheckConstraint(
            "rebate_type != 'fixed_amount' OR fixed_amount IS NOT NULL",
            name="ck_rebate_fixed_amount_required",
        ),
    )
    op.create_index("ix_rebate_agreements_org", "rebate_agreements", ["organisation_id"])
    op.create_index("ix_rebate_agreements_supplier", "rebate_agreements", ["supplier_id"])

    op.create_table(
        "rebate_period_actuals",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("rebate_agreement_id", sa.BigInteger(), sa.ForeignKey("rebate_agreements.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("actual_spend", sa.Numeric(18, 4)),
        sa.Column("actual_volume", sa.Numeric(18, 4)),
        sa.Column("entry_source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("expected_amount", sa.Numeric(18, 4)),
        sa.Column("earned_amount", sa.Numeric(18, 4)),
        sa.Column("earned_at", sa.DateTime(timezone=True)),
        sa.Column("received_amount", sa.Numeric(18, 4)),
        sa.Column("received_reference", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False, server_default="on_track"),
        sa.Column("status_calculated_at", sa.DateTime(timezone=True)),
        sa.Column("entered_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("period_end > period_start", name="ck_rebate_period_end_after_start"),
        sa.UniqueConstraint("rebate_agreement_id", "period_start", "period_end", name="uq_rebate_period"),
    )
    op.create_index("ix_rebate_period_actuals_org", "rebate_period_actuals", ["organisation_id"])
    op.create_index("ix_rebate_period_actuals_agreement", "rebate_period_actuals", ["rebate_agreement_id"])
    op.create_index("ix_rebate_period_actuals_status", "rebate_period_actuals", ["status"])

    op.create_table(
        "rebate_alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("rebate_period_actual_id", sa.BigInteger(), sa.ForeignKey("rebate_period_actuals.id"), nullable=False),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("trigger_date", sa.Date(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rebate_period_actual_id", "alert_type", name="uq_rebate_alert_type"),
    )
    op.create_index("ix_rebate_alerts_org", "rebate_alerts", ["organisation_id"])

    # ADR-011 applied from day one for these tables: ENABLE + FORCE + grants together, not ENABLE
    # now and FORCE "later" the way 0001-0003 originally did it.
    for table in _RLS_TABLES:
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
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO procureiq_app;
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
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("rebate_alerts")
    op.drop_table("rebate_period_actuals")
    op.drop_table("rebate_agreements")
