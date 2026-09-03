"""Compliance finding 1 (docs/compliance-review-2026-08.md): adds comparison_basis so a
unit-mismatched price comparison is a visible, queryable fact, not a silent one.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_review_lines", sa.Column("comparison_basis", sa.String(16)))


def downgrade() -> None:
    op.drop_column("price_review_lines", "comparison_basis")
