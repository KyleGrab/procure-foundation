"""Phase 4b: purchase_transactions - append-only (ADR-006), RLS ENABLE+FORCE+grants from day one
(ADR-011), minimal fields (ADR-013 - not the full purchase_invoices/PO/GRN ledger, that's 4c).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_transactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("supplier_sku", sa.String(128)),
        sa.Column("description", sa.String(512)),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4)),
        sa.Column("reference", sa.String(128)),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("purchase_transactions.id")),
        sa.Column("source_file_storage_key", sa.String(512)),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_transactions_org", "purchase_transactions", ["organisation_id"])
    op.create_index("ix_purchase_transactions_supplier", "purchase_transactions", ["supplier_id"])
    op.create_index("ix_purchase_transactions_date", "purchase_transactions", ["transaction_date"])

    op.execute("ALTER TABLE purchase_transactions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE purchase_transactions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON purchase_transactions
        USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                -- INSERT and SELECT only, deliberately - append-only means the app role never
                -- needs UPDATE/DELETE on this table any more than it needs them on audit_logs.
                -- A "correction" is a new row referencing corrects_id, enforced by omission here
                -- exactly like migration 0001's audit_logs grant, not by application code alone.
                GRANT SELECT, INSERT ON purchase_transactions TO procureiq_app;
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
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON purchase_transactions")
    op.drop_table("purchase_transactions")
