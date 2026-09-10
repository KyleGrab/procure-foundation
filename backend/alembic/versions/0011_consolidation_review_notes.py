"""Adds review_notes to supplier_consolidation_flags - additive, nullable, no existing-row impact.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("supplier_consolidation_flags", sa.Column("review_notes", sa.String(2048)))


def downgrade() -> None:
    op.drop_column("supplier_consolidation_flags", "review_notes")
