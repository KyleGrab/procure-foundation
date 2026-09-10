"""Phase 2 (CIMA review, sell-side trade spend): widens rebate_agreements to represent both
buy-side (rebates earned FROM a supplier) and sell-side (trade spend paid TO a customer)
relationships. Real, quantified reason: TTM Rebates Paid (R3,145,913.07) is over 3x TTM Rebates
Received (R976,235.71) in this engagement's real data, and only the smaller, buy-side direction
had a schema home before this change.

supplier_id becomes nullable; customer_id is a new nullable String column (NOT a foreign key -
no customers table exists in this schema, confirmed before this migration was written -
CostToServeLedger.customer_id already established this exact free-text precedent for the
identical real-world concept). A CHECK constraint enforces at least one of the two is set. No
existing row violates this (every current row has a real supplier_id), so no data migration or
backfill is needed alongside the DDL.

Written, not executed - no live Postgres in this sandbox, unchanged all sprint.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("rebate_agreements", "supplier_id", nullable=True)
    op.add_column("rebate_agreements", sa.Column("customer_id", sa.String(128)))
    op.add_column(
        "rebate_agreements",
        sa.Column("direction", sa.String(16), nullable=False, server_default="buy_side"),
    )
    op.create_check_constraint(
        "ck_rebate_agreements_supplier_or_customer",
        "rebate_agreements",
        "supplier_id IS NOT NULL OR customer_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_rebate_agreements_supplier_or_customer", "rebate_agreements", type_="check")
    op.drop_column("rebate_agreements", "direction")
    op.drop_column("rebate_agreements", "customer_id")
    # supplier_id reverts to NOT NULL only if no sell-side rows exist - left nullable on
    # downgrade rather than risk a downgrade failing/crashing against real data that violates
    # the stricter constraint; matches this codebase's existing posture of downgrades being a
    # schema-safety net, not a guaranteed full reversal once real data has flowed through.
