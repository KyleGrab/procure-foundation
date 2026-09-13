"""Multi-currency treasury risk module: fx_transaction_snapshots, append-only (ADR-006). Stores
real FX exposure inputs (foreign_currency_amount, both spot rates, optional FEC rate) and the
computed, mutually-exclusive result (unrealized_variance XOR hedging_gain_loss - enforced by a
CHECK constraint, not just by the pure function that computed the row). customer_id is
String(128), not a FK - no customers table exists in this schema. supplier_id is a real integer
FK to suppliers.id.

Written, not executed - no live Postgres in this sandbox, unchanged all sprint.

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_transaction_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("reporting_date", sa.Date(), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id")),
        sa.Column("customer_id", sa.String(128)),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("foreign_currency_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("transaction_date_spot_rate", sa.Numeric(12, 6), nullable=False),
        sa.Column("reporting_date_spot_rate", sa.Numeric(12, 6), nullable=False),
        sa.Column("fec_contract_rate", sa.Numeric(12, 6)),
        sa.Column("is_hedged", sa.Boolean(), nullable=False),
        sa.Column("unrealized_variance", sa.Numeric(18, 4)),
        sa.Column("hedging_gain_loss", sa.Numeric(18, 4)),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("fx_transaction_snapshots.id")),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_fx_transaction_snapshots_mutually_exclusive_variance",
        "fx_transaction_snapshots",
        "(is_hedged = true AND hedging_gain_loss IS NOT NULL AND unrealized_variance IS NULL) OR "
        "(is_hedged = false AND unrealized_variance IS NOT NULL AND hedging_gain_loss IS NULL)",
    )
    op.create_index("ix_fx_transaction_snapshots_org", "fx_transaction_snapshots", ["organisation_id"])
    op.create_index("ix_fx_transaction_snapshots_date", "fx_transaction_snapshots", ["transaction_date"])
    op.create_index("ix_fx_transaction_snapshots_customer", "fx_transaction_snapshots", ["customer_id"])

    op.execute("ALTER TABLE fx_transaction_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fx_transaction_snapshots FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON fx_transaction_snapshots
        USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                GRANT SELECT, INSERT ON fx_transaction_snapshots TO procureiq_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON fx_transaction_snapshots")
    op.drop_table("fx_transaction_snapshots")
