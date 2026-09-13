"""Phase 1 deep-dive (management accounting): extends cost_allocation_rules with the fields that
close two real, named gaps - the fallback-rate distinction (real data:
Gourmet_Foods_Cost_to_Serve_July2026.xlsx's 30_TRUCK_PROFITABILITY sheet, where an averaged
fallback rate applied uniformly regardless of real weight produced a computed R288,373/month
cross-subsidy across a real 17-truck fleet) and rate staleness (the fuel-shock blind spot - a
manually-set rate with no effective-date tracking has no mechanism to flag when it's drifted from
reality). Schema-only ALTER TABLE ADD COLUMN - RLS policies apply at the table level and are
unaffected by adding columns; no new policy needed. Written, not executed - no live Postgres in
this sandbox, unchanged all sprint.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cost_allocation_rules", sa.Column("allocation_basis", sa.String(32)))
    op.add_column(
        "cost_allocation_rules",
        sa.Column("is_fallback_rate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("cost_allocation_rules", sa.Column("matched_entity_reference", sa.String(128)))
    op.add_column("cost_allocation_rules", sa.Column("rate_effective_date", sa.Date()))
    op.add_column("cost_allocation_rules", sa.Column("rate_source", sa.String(32)))
    op.add_column("cost_allocation_rules", sa.Column("temperature_zone", sa.String(16)))


def downgrade() -> None:
    op.drop_column("cost_allocation_rules", "temperature_zone")
    op.drop_column("cost_allocation_rules", "rate_source")
    op.drop_column("cost_allocation_rules", "rate_effective_date")
    op.drop_column("cost_allocation_rules", "matched_entity_reference")
    op.drop_column("cost_allocation_rules", "is_fallback_rate")
    op.drop_column("cost_allocation_rules", "allocation_basis")
