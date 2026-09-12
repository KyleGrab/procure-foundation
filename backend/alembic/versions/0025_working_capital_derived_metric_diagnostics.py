"""WC-DERIVED-METRIC-DIAGNOSTICS-R1: adds working_capital_snapshots.derived_metric_diagnostics
(nullable JSONB, no server default, no backfill).

Closes the gap WORKING-CAPITAL-PRECISION-R1's investigation found: an extreme but genuinely
calculated DSO/DIO/DPO/CCC (a non-degenerate numerator against a near-zero denominator) can
exceed Numeric(9,1)'s storage boundary (precision 9, scale 1 - at most 8 integer digits, so the
largest magnitude that column can actually hold is 99999999.9) and previously surfaced as a raw,
unhandled asyncpg.exceptions.NumericValueOutOfRangeError at commit instead of a diagnosed null.

Contract for the new column (app.services.working_capital_service is the only writer):
- NULL:  legacy snapshot - diagnostics were not evaluated/persisted at ingestion time. Unknown,
         not "no issues."
- []:    newly evaluated snapshot - no derived-metric diagnostic applies.
- [...]: newly evaluated snapshot - one or more stable, lower_snake_case diagnostic codes apply
         (e.g. "dso_out_of_range", "ccc_unavailable_dso_out_of_range").

Schema-only ALTER TABLE ADD COLUMN, no default and no data rewrite - existing rows are left
exactly as they are (NULL), same reasoning as migration 0015's cost_allocation_rules columns:
RLS policies apply at the table level and are unaffected by adding a column; no new policy
needed. Does not touch numeric precision, raw-fact columns, period locks, or any other schema.

Revision ID: 0025
Revises: 0024
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "working_capital_snapshots",
        sa.Column("derived_metric_diagnostics", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("working_capital_snapshots", "derived_metric_diagnostics")
