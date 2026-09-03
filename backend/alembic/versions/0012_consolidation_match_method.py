"""Compliance finding 4: SupplierConsolidationFlag never stored match_method even though
scan_for_supplier_consolidation already computes it via score_pair - additive, no existing-row
impact (backfilled 'unknown' for rows created before this column existed, since the real method
truly isn't known for those - not fabricated as a guess).

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("supplier_consolidation_flags", sa.Column("match_method", sa.String(32)))
    op.execute("UPDATE supplier_consolidation_flags SET match_method = 'unknown' WHERE match_method IS NULL")
    op.alter_column("supplier_consolidation_flags", "match_method", nullable=False)


def downgrade() -> None:
    op.drop_column("supplier_consolidation_flags", "match_method")
