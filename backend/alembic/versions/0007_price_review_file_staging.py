"""Closes a gap left open since Phase 2: price_review_files needed somewhere to hold the
confirmed column mapping and the resulting mapped+validated rows between the /mapping and
/match API calls (two separate requests). Found while doing a completeness pass over Phase 4's
work - api/v1/price_reviews.py:confirm_column_mapping had been left as a stub with the real logic
only described in a comment. Same staging-before-use shape as ContractExtraction (ADR-004),
applied to file-parsing instead of AI extraction.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_review_files", sa.Column("column_mapping", postgresql.JSONB()))
    op.add_column("price_review_files", sa.Column("staged_rows", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("price_review_files", "staged_rows")
    op.drop_column("price_review_files", "column_mapping")
