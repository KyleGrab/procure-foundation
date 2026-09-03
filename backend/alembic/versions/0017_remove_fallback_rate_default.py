"""Chaos Audit Domain 1: removes cost_allocation_rules.is_fallback_rate's DB-level
server_default=sa.false() (set in migration 0015). That default meant a row nobody explicitly
classified silently read as "matched, high confidence" - exactly the fabricated-zero/fabricated-
confidence pattern this whole engagement exists to close, compounding the same column's
ORM-level default=False (also removed, app/db/models/management_accounting.py). Column remains
NOT NULL - every existing real row was already given a real value at creation, so no data
migration or backfill is needed; only new INSERTs are affected, and they must now state a real
value explicitly.

Written, not executed - no live Postgres in this sandbox, unchanged all sprint.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cost_allocation_rules", "is_fallback_rate", server_default=None)


def downgrade() -> None:
    op.alter_column("cost_allocation_rules", "is_fallback_rate", server_default=sa.false())
