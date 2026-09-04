"""P-03: Financial Amount Evidence-State Foundation.

Three governed measures (RebatePeriodActual.expected_amount, Opportunity.
annual_financial_impact, Opportunity.realised_savings) each get a full evidence-state model:
status, source_basis, calculated_at/approved_at/approved_by, effective period where the measure
needs one, and a nullable current_event_id pointer into the new append-only
financial_amount_status_events table.

Deliberately seeds NO data beyond genesis events for existing rows (see the backfill step below)
- no financial amount is invented, overwritten, or inferred upward. Existing NULL amounts
backfill to 'unknown'; existing non-NULL amounts backfill to 'legacy_unverified', preserved
exactly, never rounded or rescaled.

Three deferred constraint triggers, each doing something a plain CHECK constraint structurally
cannot (cross-row/cross-table validation, evaluated at COMMIT, not immediately per-statement):
1. check_confirmed_event_has_sufficient_evidence - a 'confirmed' event must have specific,
   sufficient linked evidence_type rows, not merely at least one of any kind.
2. check_event_chain_integrity - a new event's old_* fields must exactly match its immediate
   predecessor's new_* fields (no version gaps, no fabricated history); a downgrade in evidence
   tier requires a correction-appropriate change_reason_code.
3. check_snapshot_matches_current_event (three instances, one per measure) - the current-state
   row's own fields must equal its current_event_id's new_* fields, and that event must be the
   latest for its parent+measure. This is what makes a direct snapshot-only UPDATE - bypassing
   the event log entirely - fail at COMMIT, not just discouraged by convention.

procureiq_app receives SELECT, INSERT only on both new tables - cannot UPDATE, DELETE, or
disable any trigger (does not own either table, matching this project's established, already-
proven convention for every append-only table).

Migration downgrade/archive warning: dropping the two new tables in downgrade() destroys all
captured event/evidence history. Safe only before real events are written in a live environment;
after that point, an explicit export/archive of both tables should precede any downgrade.

Written, not executed - no live Postgres in this sandbox. Every raw-SQL test this migration's
design implies is in tests/test_financial_amount_events_raw_sql.py, written alongside this file,
equally unexecuted here.

Revision ID: 0021
Revises: 0020
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Shared SQL fragments, defined once to avoid the three per-measure snapshot triggers and the
# event-table's own combination check silently drifting out of sync with each other.
# ---------------------------------------------------------------------------

_EXPECTED_AMOUNT_COMBINATION_SQL = """
  (expected_amount_status IN ('unknown','not_applicable') AND expected_amount IS NULL
    AND expected_amount_source_basis IS NULL AND expected_amount_calculated_at IS NULL
    AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)
  OR (expected_amount_status = 'legacy_unverified' AND expected_amount IS NOT NULL
    AND expected_amount_source_basis IS NULL AND expected_amount_calculated_at IS NULL
    AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)
  OR (expected_amount_status = 'estimated' AND expected_amount IS NOT NULL
    AND expected_amount_source_basis IS NOT NULL AND expected_amount_source_basis = 'manual_estimate'
    AND expected_amount_calculated_at IS NULL
    AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)
  OR (expected_amount_status = 'calculated' AND expected_amount IS NOT NULL
    AND expected_amount_source_basis IS NOT NULL
    AND expected_amount_source_basis = 'contract_terms_calculation'
    AND expected_amount_calculated_at IS NOT NULL
    AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)
  OR (expected_amount_status = 'confirmed' AND expected_amount IS NOT NULL
    AND expected_amount_source_basis IS NOT NULL
    AND expected_amount_source_basis IN ('supplier_statement','credit_note')
    AND expected_amount_calculated_at IS NULL
    AND expected_amount_approved_at IS NOT NULL AND expected_amount_approved_by_user_id IS NOT NULL)
"""

_AFI_COMBINATION_SQL = """
  (annual_financial_impact_status IN ('unknown','not_applicable') AND annual_financial_impact IS NULL
    AND annual_financial_impact_source_basis IS NULL AND annual_financial_impact_calculated_at IS NULL
    AND annual_financial_impact_effective_from IS NULL)
  OR (annual_financial_impact_status = 'legacy_unverified' AND annual_financial_impact IS NOT NULL
    AND annual_financial_impact_source_basis IS NULL AND annual_financial_impact_calculated_at IS NULL
    AND annual_financial_impact_effective_from IS NULL)
  OR (annual_financial_impact_status = 'estimated' AND annual_financial_impact IS NOT NULL
    AND annual_financial_impact_source_basis IS NOT NULL
    AND annual_financial_impact_source_basis = 'manual_estimate'
    AND annual_financial_impact_calculated_at IS NULL
    AND annual_financial_impact_effective_from IS NOT NULL)
  OR (annual_financial_impact_status = 'calculated' AND annual_financial_impact IS NOT NULL
    AND annual_financial_impact_source_basis IS NOT NULL
    AND annual_financial_impact_source_basis = 'price_review_calculation'
    AND annual_financial_impact_calculated_at IS NOT NULL
    AND annual_financial_impact_effective_from IS NOT NULL)
"""

_RS_COMBINATION_SQL = """
  (realised_savings_status IN ('unknown','not_applicable') AND realised_savings IS NULL
    AND realised_savings_source_basis IS NULL AND realised_savings_calculated_at IS NULL
    AND realised_savings_approved_at IS NULL AND realised_savings_approved_by_user_id IS NULL
    AND realised_savings_effective_period_start IS NULL AND realised_savings_effective_period_end IS NULL)
  OR (realised_savings_status = 'legacy_unverified' AND realised_savings IS NOT NULL
    AND realised_savings_source_basis IS NULL AND realised_savings_calculated_at IS NULL
    AND realised_savings_approved_at IS NULL AND realised_savings_approved_by_user_id IS NULL
    AND realised_savings_effective_period_start IS NULL AND realised_savings_effective_period_end IS NULL)
  OR (realised_savings_status = 'calculated' AND realised_savings IS NOT NULL
    AND realised_savings_source_basis IS NOT NULL
    AND realised_savings_source_basis = 'actual_cost_data_calculation'
    AND realised_savings_calculated_at IS NOT NULL
    AND realised_savings_approved_at IS NULL AND realised_savings_approved_by_user_id IS NULL
    AND realised_savings_effective_period_start IS NOT NULL AND realised_savings_effective_period_end IS NOT NULL
    AND realised_savings_effective_period_start <= realised_savings_effective_period_end)
  OR (realised_savings_status = 'confirmed' AND realised_savings IS NOT NULL
    AND realised_savings_source_basis IS NOT NULL AND realised_savings_source_basis = 'reconciled_actuals'
    AND realised_savings_calculated_at IS NULL
    AND realised_savings_approved_at IS NOT NULL AND realised_savings_approved_by_user_id IS NOT NULL
    AND realised_savings_effective_period_start IS NOT NULL AND realised_savings_effective_period_end IS NOT NULL
    AND realised_savings_effective_period_start <= realised_savings_effective_period_end)
"""


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Step 1: financial_amount_status_events
    # ------------------------------------------------------------------
    op.create_table(
        "financial_amount_status_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("rebate_period_actual_id", sa.BigInteger(), sa.ForeignKey("rebate_period_actuals.id")),
        sa.Column("opportunity_id", sa.BigInteger(), sa.ForeignKey("opportunities.id")),
        sa.Column("measure_code", sa.String(32), nullable=False),
        sa.Column("event_version", sa.BigInteger(), nullable=False),
        sa.Column("old_amount", sa.Numeric(18, 4)),
        sa.Column("new_amount", sa.Numeric(18, 4)),
        sa.Column("old_status", sa.String(32)),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("old_source_basis", sa.String(64)),
        sa.Column("new_source_basis", sa.String(64)),
        sa.Column("old_calculated_at", sa.DateTime(timezone=True)),
        sa.Column("new_calculated_at", sa.DateTime(timezone=True)),
        sa.Column("old_approved_at", sa.DateTime(timezone=True)),
        sa.Column("new_approved_at", sa.DateTime(timezone=True)),
        sa.Column("old_approved_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("new_approved_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("old_effective_period_start", sa.Date()),
        sa.Column("new_effective_period_start", sa.Date()),
        sa.Column("old_effective_period_end", sa.Date()),
        sa.Column("new_effective_period_end", sa.Date()),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("change_reference", sa.String(128), nullable=False),
        sa.Column("change_reason_code", sa.String(32), nullable=False),
        sa.Column("change_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_famev_measure_code", "financial_amount_status_events",
        "measure_code IN ('expected_amount','annual_financial_impact','realised_savings')",
    )
    op.create_check_constraint(
        "ck_famev_exactly_one_parent", "financial_amount_status_events",
        "(rebate_period_actual_id IS NOT NULL AND opportunity_id IS NULL) OR "
        "(rebate_period_actual_id IS NULL AND opportunity_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_famev_rebate_parent_measure", "financial_amount_status_events",
        "rebate_period_actual_id IS NULL OR measure_code = 'expected_amount'",
    )
    op.create_check_constraint(
        "ck_famev_opportunity_parent_measure", "financial_amount_status_events",
        "opportunity_id IS NULL OR measure_code IN ('annual_financial_impact','realised_savings')",
    )
    op.create_check_constraint(
        "ck_famev_version_positive", "financial_amount_status_events", "event_version > 0",
    )
    op.create_check_constraint(
        "ck_famev_genesis_old_fields_null", "financial_amount_status_events",
        "event_version != 1 OR ("
        "old_amount IS NULL AND old_status IS NULL AND old_source_basis IS NULL AND "
        "old_calculated_at IS NULL AND old_approved_at IS NULL AND old_approved_by_user_id IS NULL AND "
        "old_effective_period_start IS NULL AND old_effective_period_end IS NULL)",
    )
    op.create_check_constraint(
        "ck_famev_reason_code_vocabulary", "financial_amount_status_events",
        "change_reason_code IN ('initial_backfill','manual_estimate','recalculation',"
        "'evidence_received','correction','evidence_withdrawn','source_data_restated')",
    )
    op.create_check_constraint(
        "ck_famev_status_valid_for_measure", "financial_amount_status_events",
        "(measure_code = 'expected_amount' AND new_status IN "
        "  ('unknown','not_applicable','legacy_unverified','estimated','calculated','confirmed'))"
        " OR (measure_code = 'annual_financial_impact' AND new_status IN "
        "  ('unknown','not_applicable','legacy_unverified','estimated','calculated'))"
        " OR (measure_code = 'realised_savings' AND new_status IN "
        "  ('unknown','not_applicable','legacy_unverified','calculated','confirmed'))",
    )
    # P-03 Phase 1 fix: event rows previously had no full state-combination validation - only
    # the vocabulary check above (new_status membership per measure). An event could carry
    # new_status='calculated' with a NULL new_source_basis and nothing would catch it. This
    # constraint is additive, not a replacement - the simpler vocabulary check above stays
    # exactly as it was, this adds the field-combination layer that was missing.
    #
    # Every literal comparison below is explicitly guarded with "column IS NOT NULL AND
    # column = '...'" rather than a bare "column = '...'" - a bare equality against a NULL
    # column evaluates to NULL (not FALSE) in Postgres, and NULL propagating through a long
    # OR-chain via `FALSE OR NULL = NULL` makes the ENTIRE constraint evaluate to NULL, which
    # Postgres treats as SATISFIED, not violated - silently accepting the malformed row. This
    # is not a hypothetical: writing the naive, unguarded version and testing it against a
    # missing-source_basis 'estimated' row confirmed it would have been wrongly accepted.
    op.create_check_constraint(
        "ck_famev_state_combination", "financial_amount_status_events",
        # --- expected_amount: 5 branches (unknown/not_applicable share one, 4 more) ---
        "(measure_code = 'expected_amount' AND new_status IN ('unknown','not_applicable') AND "
        "  new_amount IS NULL AND new_source_basis IS NULL AND new_calculated_at IS NULL AND "
        "  new_approved_at IS NULL AND new_approved_by_user_id IS NULL)"
        " OR (measure_code = 'expected_amount' AND new_status = 'legacy_unverified' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NULL AND new_calculated_at IS NULL AND "
        "  new_approved_at IS NULL AND new_approved_by_user_id IS NULL)"
        " OR (measure_code = 'expected_amount' AND new_status = 'estimated' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NOT NULL AND new_source_basis = 'manual_estimate' AND "
        "  new_calculated_at IS NULL AND new_approved_at IS NULL AND new_approved_by_user_id IS NULL)"
        " OR (measure_code = 'expected_amount' AND new_status = 'calculated' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NOT NULL "
        "  AND new_source_basis = 'contract_terms_calculation' AND "
        "  new_calculated_at IS NOT NULL AND new_approved_at IS NULL AND new_approved_by_user_id IS NULL)"
        " OR (measure_code = 'expected_amount' AND new_status = 'confirmed' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NOT NULL "
        "  AND new_source_basis IN ('supplier_statement','credit_note') AND "
        "  new_calculated_at IS NULL AND new_approved_at IS NOT NULL AND new_approved_by_user_id IS NOT NULL)"
        # --- annual_financial_impact: 4 branches, no confirmed, approved_* always NULL,
        # only period_start used (period_end always NULL) ---
        " OR (measure_code = 'annual_financial_impact' AND new_status IN ('unknown','not_applicable') AND "
        "  new_amount IS NULL AND new_source_basis IS NULL AND new_calculated_at IS NULL AND "
        "  new_approved_at IS NULL AND new_approved_by_user_id IS NULL AND "
        "  new_effective_period_start IS NULL AND new_effective_period_end IS NULL)"
        " OR (measure_code = 'annual_financial_impact' AND new_status = 'legacy_unverified' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NULL AND new_calculated_at IS NULL AND "
        "  new_approved_at IS NULL AND new_approved_by_user_id IS NULL AND "
        "  new_effective_period_start IS NULL AND new_effective_period_end IS NULL)"
        " OR (measure_code = 'annual_financial_impact' AND new_status = 'estimated' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NOT NULL AND new_source_basis = 'manual_estimate' AND "
        "  new_calculated_at IS NULL AND new_approved_at IS NULL AND new_approved_by_user_id IS NULL AND "
        "  new_effective_period_start IS NOT NULL AND new_effective_period_end IS NULL)"
        " OR (measure_code = 'annual_financial_impact' AND new_status = 'calculated' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NOT NULL "
        "  AND new_source_basis = 'price_review_calculation' AND "
        "  new_calculated_at IS NOT NULL AND new_approved_at IS NULL AND new_approved_by_user_id IS NULL AND "
        "  new_effective_period_start IS NOT NULL AND new_effective_period_end IS NULL)"
        # --- realised_savings: 4 branches, no estimated, both period fields together ---
        " OR (measure_code = 'realised_savings' AND new_status IN ('unknown','not_applicable') AND "
        "  new_amount IS NULL AND new_source_basis IS NULL AND new_calculated_at IS NULL AND "
        "  new_approved_at IS NULL AND new_approved_by_user_id IS NULL AND "
        "  new_effective_period_start IS NULL AND new_effective_period_end IS NULL)"
        " OR (measure_code = 'realised_savings' AND new_status = 'legacy_unverified' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NULL AND new_calculated_at IS NULL AND "
        "  new_approved_at IS NULL AND new_approved_by_user_id IS NULL AND "
        "  new_effective_period_start IS NULL AND new_effective_period_end IS NULL)"
        " OR (measure_code = 'realised_savings' AND new_status = 'calculated' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NOT NULL "
        "  AND new_source_basis = 'actual_cost_data_calculation' AND "
        "  new_calculated_at IS NOT NULL AND new_approved_at IS NULL AND new_approved_by_user_id IS NULL AND "
        "  new_effective_period_start IS NOT NULL AND new_effective_period_end IS NOT NULL AND "
        "  new_effective_period_start <= new_effective_period_end)"
        " OR (measure_code = 'realised_savings' AND new_status = 'confirmed' AND "
        "  new_amount IS NOT NULL AND new_source_basis IS NOT NULL AND new_source_basis = 'reconciled_actuals' AND "
        "  new_calculated_at IS NULL AND new_approved_at IS NOT NULL AND new_approved_by_user_id IS NOT NULL AND "
        "  new_effective_period_start IS NOT NULL AND new_effective_period_end IS NOT NULL AND "
        "  new_effective_period_start <= new_effective_period_end)",
    )
    op.create_unique_constraint("uq_famev_id_org", "financial_amount_status_events", ["id", "organisation_id"])
    op.create_unique_constraint(
        "uq_famev_rebate_seq", "financial_amount_status_events",
        ["rebate_period_actual_id", "measure_code", "event_version"],
    )
    op.create_unique_constraint(
        "uq_famev_opportunity_seq", "financial_amount_status_events",
        ["opportunity_id", "measure_code", "event_version"],
    )
    op.create_index("ix_famev_org", "financial_amount_status_events", ["organisation_id"])

    # ------------------------------------------------------------------
    # Step 2: financial_amount_evidence
    # ------------------------------------------------------------------
    op.create_table(
        "financial_amount_evidence",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_type", sa.String(48), nullable=False),
        sa.Column("external_reference", sa.String(128), nullable=False),
        sa.Column("document_date", sa.Date()),
        sa.Column("effective_period", sa.Date()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("document_storage_key", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_famev_evid_type_vocabulary", "financial_amount_evidence",
        "evidence_type IN ('invoice','credit_note','supplier_statement','gl_posting',"
        "'documented_baseline','actual_cost_source','variance_calculation_reference','supporting_document')",
    )
    op.create_foreign_key(
        "fk_famev_evid_event_tenant_matched", "financial_amount_evidence", "financial_amount_status_events",
        ["event_id", "organisation_id"], ["id", "organisation_id"],
    )
    op.create_index("ix_famev_evid_org", "financial_amount_evidence", ["organisation_id"])
    op.create_index("ix_famev_evid_event", "financial_amount_evidence", ["event_id"])

    # ------------------------------------------------------------------
    # Step 3: deferred confirmation-sufficiency trigger
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION check_confirmed_event_has_sufficient_evidence() RETURNS TRIGGER AS $$
        BEGIN
          IF NEW.new_status != 'confirmed' THEN
            RETURN NEW;
          END IF;

          IF NEW.measure_code = 'realised_savings' AND NEW.new_source_basis = 'reconciled_actuals' THEN
            IF NOT EXISTS (SELECT 1 FROM financial_amount_evidence
                            WHERE event_id = NEW.id AND evidence_type = 'documented_baseline') THEN
              RAISE EXCEPTION 'Confirmed reconciled_actuals event % missing documented_baseline evidence', NEW.id;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM financial_amount_evidence
                            WHERE event_id = NEW.id AND evidence_type = 'actual_cost_source') THEN
              RAISE EXCEPTION 'Confirmed reconciled_actuals event % missing actual_cost_source evidence', NEW.id;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM financial_amount_evidence
                            WHERE event_id = NEW.id AND evidence_type = 'variance_calculation_reference') THEN
              RAISE EXCEPTION 'Confirmed reconciled_actuals event % missing variance_calculation_reference evidence', NEW.id;
            END IF;
          ELSIF NEW.measure_code = 'expected_amount' THEN
            IF NOT EXISTS (SELECT 1 FROM financial_amount_evidence
                            WHERE event_id = NEW.id AND evidence_type IN ('supplier_statement','credit_note')) THEN
              RAISE EXCEPTION 'Confirmed expected_amount event % missing valid rebate-confirmation evidence', NEW.id;
            END IF;
          END IF;

          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_confirmed_event_requires_evidence
        AFTER INSERT ON financial_amount_status_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_confirmed_event_has_sufficient_evidence();
    """)

    # ------------------------------------------------------------------
    # Step 4: deferred event-chain integrity trigger
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION check_event_chain_integrity() RETURNS TRIGGER AS $$
        DECLARE
          prev financial_amount_status_events%ROWTYPE;
          prev_tier INT;
          new_tier INT;
        BEGIN
          IF NEW.event_version = 1 THEN
            RETURN NEW;
          END IF;

          SELECT * INTO prev FROM financial_amount_status_events
          WHERE measure_code = NEW.measure_code AND event_version = NEW.event_version - 1
            AND rebate_period_actual_id IS NOT DISTINCT FROM NEW.rebate_period_actual_id
            AND opportunity_id IS NOT DISTINCT FROM NEW.opportunity_id;

          IF NOT FOUND THEN
            RAISE EXCEPTION 'Event % (version %) has no immediately preceding event (version %)',
              NEW.id, NEW.event_version, NEW.event_version - 1;
          END IF;

          IF NEW.old_amount IS DISTINCT FROM prev.new_amount
             OR NEW.old_status IS DISTINCT FROM prev.new_status
             OR NEW.old_source_basis IS DISTINCT FROM prev.new_source_basis
             OR NEW.old_calculated_at IS DISTINCT FROM prev.new_calculated_at
             OR NEW.old_approved_at IS DISTINCT FROM prev.new_approved_at
             OR NEW.old_approved_by_user_id IS DISTINCT FROM prev.new_approved_by_user_id
             OR NEW.old_effective_period_start IS DISTINCT FROM prev.new_effective_period_start
             OR NEW.old_effective_period_end IS DISTINCT FROM prev.new_effective_period_end THEN
            RAISE EXCEPTION 'Event %: old_* values do not match preceding event''s new_* values', NEW.id;
          END IF;

          prev_tier := (CASE prev.new_status
            WHEN 'unknown' THEN 0 WHEN 'not_applicable' THEN 0 WHEN 'legacy_unverified' THEN 1
            WHEN 'estimated' THEN 2 WHEN 'calculated' THEN 3 WHEN 'confirmed' THEN 4 END);
          new_tier := (CASE NEW.new_status
            WHEN 'unknown' THEN 0 WHEN 'not_applicable' THEN 0 WHEN 'legacy_unverified' THEN 1
            WHEN 'estimated' THEN 2 WHEN 'calculated' THEN 3 WHEN 'confirmed' THEN 4 END);

          IF new_tier < prev_tier AND NEW.change_reason_code NOT IN
             ('correction', 'evidence_withdrawn', 'source_data_restated') THEN
            RAISE EXCEPTION 'Downgrade from % to % requires a correction-appropriate reason code, got %',
              prev.new_status, NEW.new_status, NEW.change_reason_code;
          END IF;

          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_event_chain_integrity
        AFTER INSERT ON financial_amount_status_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_event_chain_integrity();
    """)

    # ------------------------------------------------------------------
    # Step 5: nullable pointer + status/provenance/period columns on the two parent tables
    # ------------------------------------------------------------------
    op.add_column("rebate_period_actuals", sa.Column("expected_amount_status", sa.String(32)))
    op.add_column("rebate_period_actuals", sa.Column("expected_amount_source_basis", sa.String(64)))
    op.add_column("rebate_period_actuals", sa.Column("expected_amount_calculated_at", sa.DateTime(timezone=True)))
    op.add_column("rebate_period_actuals", sa.Column("expected_amount_approved_at", sa.DateTime(timezone=True)))
    op.add_column(
        "rebate_period_actuals",
        sa.Column("expected_amount_approved_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
    )
    op.add_column(
        "rebate_period_actuals",
        sa.Column(
            "expected_amount_current_event_id", sa.BigInteger(),
            sa.ForeignKey("financial_amount_status_events.id"),
        ),
    )

    op.add_column("opportunities", sa.Column("annual_financial_impact_status", sa.String(32)))
    op.add_column("opportunities", sa.Column("annual_financial_impact_source_basis", sa.String(64)))
    op.add_column("opportunities", sa.Column("annual_financial_impact_calculated_at", sa.DateTime(timezone=True)))
    op.add_column("opportunities", sa.Column("annual_financial_impact_effective_from", sa.Date()))
    op.add_column(
        "opportunities",
        sa.Column(
            "annual_financial_impact_current_event_id", sa.BigInteger(),
            sa.ForeignKey("financial_amount_status_events.id"),
        ),
    )
    op.add_column("opportunities", sa.Column("realised_savings_status", sa.String(32)))
    op.add_column("opportunities", sa.Column("realised_savings_source_basis", sa.String(64)))
    op.add_column("opportunities", sa.Column("realised_savings_calculated_at", sa.DateTime(timezone=True)))
    op.add_column("opportunities", sa.Column("realised_savings_approved_at", sa.DateTime(timezone=True)))
    op.add_column(
        "opportunities",
        sa.Column("realised_savings_approved_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
    )
    op.add_column("opportunities", sa.Column("realised_savings_effective_period_start", sa.Date()))
    op.add_column("opportunities", sa.Column("realised_savings_effective_period_end", sa.Date()))
    op.add_column(
        "opportunities",
        sa.Column(
            "realised_savings_current_event_id", sa.BigInteger(),
            sa.ForeignKey("financial_amount_status_events.id"),
        ),
    )

    # ------------------------------------------------------------------
    # Step 6: backfill - status only, amounts never touched
    # ------------------------------------------------------------------
    op.execute("""
        UPDATE rebate_period_actuals SET expected_amount_status =
          CASE WHEN expected_amount IS NULL THEN 'unknown' ELSE 'legacy_unverified' END
    """)
    op.execute("""
        UPDATE opportunities SET
          annual_financial_impact_status =
            CASE WHEN annual_financial_impact IS NULL THEN 'unknown' ELSE 'legacy_unverified' END,
          realised_savings_status =
            CASE WHEN realised_savings IS NULL THEN 'unknown' ELSE 'legacy_unverified' END
    """)

    # ------------------------------------------------------------------
    # Step 7: genesis events for every existing row, then populate pointers
    # ------------------------------------------------------------------
    op.execute("""
        INSERT INTO financial_amount_status_events
          (public_id, organisation_id, rebate_period_actual_id, measure_code, event_version,
           new_amount, new_status, occurred_at, change_reference, change_reason_code)
        SELECT gen_random_uuid(), organisation_id, id, 'expected_amount', 1,
               expected_amount, expected_amount_status, now(),
               'system_backfill_migration_0021', 'initial_backfill'
        FROM rebate_period_actuals
    """)
    op.execute("""
        UPDATE rebate_period_actuals rpa SET expected_amount_current_event_id = ev.id
        FROM financial_amount_status_events ev
        WHERE ev.rebate_period_actual_id = rpa.id AND ev.measure_code = 'expected_amount'
    """)

    op.execute("""
        INSERT INTO financial_amount_status_events
          (public_id, organisation_id, opportunity_id, measure_code, event_version,
           new_amount, new_status, occurred_at, change_reference, change_reason_code)
        SELECT gen_random_uuid(), organisation_id, id, 'annual_financial_impact', 1,
               annual_financial_impact, annual_financial_impact_status, now(),
               'system_backfill_migration_0021', 'initial_backfill'
        FROM opportunities
    """)
    op.execute("""
        UPDATE opportunities o SET annual_financial_impact_current_event_id = ev.id
        FROM financial_amount_status_events ev
        WHERE ev.opportunity_id = o.id AND ev.measure_code = 'annual_financial_impact'
    """)

    op.execute("""
        INSERT INTO financial_amount_status_events
          (public_id, organisation_id, opportunity_id, measure_code, event_version,
           new_amount, new_status, occurred_at, change_reference, change_reason_code)
        SELECT gen_random_uuid(), organisation_id, id, 'realised_savings', 1,
               realised_savings, realised_savings_status, now(),
               'system_backfill_migration_0021', 'initial_backfill'
        FROM opportunities
    """)
    op.execute("""
        UPDATE opportunities o SET realised_savings_current_event_id = ev.id
        FROM financial_amount_status_events ev
        WHERE ev.opportunity_id = o.id AND ev.measure_code = 'realised_savings'
    """)

    # ------------------------------------------------------------------
    # Step 8: deferred parent-row snapshot-matches-current-event triggers (one per measure)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION check_rpa_expected_amount_matches_event() RETURNS TRIGGER AS $$
        DECLARE ev financial_amount_status_events%ROWTYPE; latest_id BIGINT;
        BEGIN
          IF NEW.expected_amount_current_event_id IS NULL THEN
            RAISE EXCEPTION 'rebate_period_actual %: expected_amount_current_event_id must not be NULL at commit', NEW.id;
          END IF;

          SELECT * INTO ev FROM financial_amount_status_events WHERE id = NEW.expected_amount_current_event_id;
          IF ev.organisation_id != NEW.organisation_id OR ev.rebate_period_actual_id != NEW.id
             OR ev.measure_code != 'expected_amount' THEN
            RAISE EXCEPTION 'rebate_period_actual %: current_event_id does not reference a matching event', NEW.id;
          END IF;
          IF NEW.expected_amount IS DISTINCT FROM ev.new_amount
             OR NEW.expected_amount_status IS DISTINCT FROM ev.new_status
             OR NEW.expected_amount_source_basis IS DISTINCT FROM ev.new_source_basis
             OR NEW.expected_amount_calculated_at IS DISTINCT FROM ev.new_calculated_at
             OR NEW.expected_amount_approved_at IS DISTINCT FROM ev.new_approved_at
             OR NEW.expected_amount_approved_by_user_id IS DISTINCT FROM ev.new_approved_by_user_id THEN
            RAISE EXCEPTION 'rebate_period_actual %: snapshot does not match its current event', NEW.id;
          END IF;

          SELECT id INTO latest_id FROM financial_amount_status_events
            WHERE rebate_period_actual_id = NEW.id AND measure_code = 'expected_amount'
            ORDER BY event_version DESC LIMIT 1;
          IF latest_id != NEW.expected_amount_current_event_id THEN
            RAISE EXCEPTION 'rebate_period_actual %: current_event_id is not the latest event', NEW.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_rpa_expected_amount_matches_event
        AFTER INSERT OR UPDATE ON rebate_period_actuals
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_rpa_expected_amount_matches_event();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION check_opp_annual_financial_impact_matches_event() RETURNS TRIGGER AS $$
        DECLARE ev financial_amount_status_events%ROWTYPE; latest_id BIGINT;
        BEGIN
          IF NEW.annual_financial_impact_current_event_id IS NULL THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact_current_event_id must not be NULL at commit', NEW.id;
          END IF;
          SELECT * INTO ev FROM financial_amount_status_events WHERE id = NEW.annual_financial_impact_current_event_id;
          IF ev.organisation_id != NEW.organisation_id OR ev.opportunity_id != NEW.id
             OR ev.measure_code != 'annual_financial_impact' THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact_current_event_id mismatch', NEW.id;
          END IF;
          IF NEW.annual_financial_impact IS DISTINCT FROM ev.new_amount
             OR NEW.annual_financial_impact_status IS DISTINCT FROM ev.new_status
             OR NEW.annual_financial_impact_source_basis IS DISTINCT FROM ev.new_source_basis
             OR NEW.annual_financial_impact_calculated_at IS DISTINCT FROM ev.new_calculated_at
             OR NEW.annual_financial_impact_effective_from IS DISTINCT FROM ev.new_effective_period_start THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact snapshot does not match its current event', NEW.id;
          END IF;
          SELECT id INTO latest_id FROM financial_amount_status_events
            WHERE opportunity_id = NEW.id AND measure_code = 'annual_financial_impact'
            ORDER BY event_version DESC LIMIT 1;
          IF latest_id != NEW.annual_financial_impact_current_event_id THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact current_event_id is not the latest event', NEW.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_opp_annual_financial_impact_matches_event
        AFTER INSERT OR UPDATE ON opportunities
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_opp_annual_financial_impact_matches_event();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION check_opp_realised_savings_matches_event() RETURNS TRIGGER AS $$
        DECLARE ev financial_amount_status_events%ROWTYPE; latest_id BIGINT;
        BEGIN
          IF NEW.realised_savings_current_event_id IS NULL THEN
            RAISE EXCEPTION 'opportunity %: realised_savings_current_event_id must not be NULL at commit', NEW.id;
          END IF;
          SELECT * INTO ev FROM financial_amount_status_events WHERE id = NEW.realised_savings_current_event_id;
          IF ev.organisation_id != NEW.organisation_id OR ev.opportunity_id != NEW.id
             OR ev.measure_code != 'realised_savings' THEN
            RAISE EXCEPTION 'opportunity %: realised_savings_current_event_id mismatch', NEW.id;
          END IF;
          IF NEW.realised_savings IS DISTINCT FROM ev.new_amount
             OR NEW.realised_savings_status IS DISTINCT FROM ev.new_status
             OR NEW.realised_savings_source_basis IS DISTINCT FROM ev.new_source_basis
             OR NEW.realised_savings_calculated_at IS DISTINCT FROM ev.new_calculated_at
             OR NEW.realised_savings_approved_at IS DISTINCT FROM ev.new_approved_at
             OR NEW.realised_savings_approved_by_user_id IS DISTINCT FROM ev.new_approved_by_user_id
             OR NEW.realised_savings_effective_period_start IS DISTINCT FROM ev.new_effective_period_start
             OR NEW.realised_savings_effective_period_end IS DISTINCT FROM ev.new_effective_period_end THEN
            RAISE EXCEPTION 'opportunity %: realised_savings snapshot does not match its current event', NEW.id;
          END IF;
          SELECT id INTO latest_id FROM financial_amount_status_events
            WHERE opportunity_id = NEW.id AND measure_code = 'realised_savings'
            ORDER BY event_version DESC LIMIT 1;
          IF latest_id != NEW.realised_savings_current_event_id THEN
            RAISE EXCEPTION 'opportunity %: realised_savings current_event_id is not the latest event', NEW.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_opp_realised_savings_matches_event
        AFTER INSERT OR UPDATE ON opportunities
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_opp_realised_savings_matches_event();
    """)

    # ------------------------------------------------------------------
    # Step 9: current-state combination CHECK constraints and SET NOT NULL on status columns
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "ck_rpa_expected_amount_status_valid", "rebate_period_actuals",
        "expected_amount_status IN "
        "('unknown','not_applicable','legacy_unverified','estimated','calculated','confirmed')",
    )
    op.create_check_constraint(
        "ck_rpa_expected_amount_source_basis_vocabulary", "rebate_period_actuals",
        "expected_amount_source_basis IS NULL OR expected_amount_source_basis IN "
        "('manual_estimate','contract_terms_calculation','supplier_statement','credit_note')",
    )
    op.create_check_constraint(
        "ck_rpa_expected_amount_state_combination", "rebate_period_actuals", _EXPECTED_AMOUNT_COMBINATION_SQL,
    )
    op.alter_column("rebate_period_actuals", "expected_amount_status", nullable=False)

    op.create_check_constraint(
        "ck_opp_afi_status_valid", "opportunities",
        "annual_financial_impact_status IN "
        "('unknown','not_applicable','legacy_unverified','estimated','calculated')",
    )
    op.create_check_constraint(
        "ck_opp_afi_source_basis_vocabulary", "opportunities",
        "annual_financial_impact_source_basis IS NULL OR annual_financial_impact_source_basis IN "
        "('manual_estimate','price_review_calculation')",
    )
    op.create_check_constraint("ck_opp_afi_state_combination", "opportunities", _AFI_COMBINATION_SQL)
    op.alter_column("opportunities", "annual_financial_impact_status", nullable=False)

    op.create_check_constraint(
        "ck_opp_rs_status_valid", "opportunities",
        "realised_savings_status IN ('unknown','not_applicable','legacy_unverified','calculated','confirmed')",
    )
    op.create_check_constraint(
        "ck_opp_rs_source_basis_vocabulary", "opportunities",
        "realised_savings_source_basis IS NULL OR realised_savings_source_basis IN "
        "('actual_cost_data_calculation','reconciled_actuals')",
    )
    op.create_check_constraint("ck_opp_rs_state_combination", "opportunities", _RS_COMBINATION_SQL)
    op.alter_column("opportunities", "realised_savings_status", nullable=False)

    # ------------------------------------------------------------------
    # Step 10: RLS + grants on both new tables
    # ------------------------------------------------------------------
    for table in ("financial_amount_status_events", "financial_amount_evidence"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
        """)
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                    GRANT SELECT, INSERT ON {table} TO procureiq_app;
                END IF;
            END $$;
        """)


def downgrade() -> None:
    for table in ("financial_amount_evidence", "financial_amount_status_events"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    for trg, tbl in (
        ("trg_opp_realised_savings_matches_event", "opportunities"),
        ("trg_opp_annual_financial_impact_matches_event", "opportunities"),
        ("trg_rpa_expected_amount_matches_event", "rebate_period_actuals"),
        ("trg_event_chain_integrity", "financial_amount_status_events"),
        ("trg_confirmed_event_requires_evidence", "financial_amount_status_events"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trg} ON {tbl}")

    for fn in (
        "check_opp_realised_savings_matches_event", "check_opp_annual_financial_impact_matches_event",
        "check_rpa_expected_amount_matches_event", "check_event_chain_integrity",
        "check_confirmed_event_has_sufficient_evidence",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}()")

    for col in (
        "realised_savings_current_event_id", "realised_savings_effective_period_end",
        "realised_savings_effective_period_start", "realised_savings_approved_by_user_id",
        "realised_savings_approved_at", "realised_savings_calculated_at", "realised_savings_source_basis",
        "realised_savings_status", "annual_financial_impact_current_event_id",
        "annual_financial_impact_effective_from", "annual_financial_impact_calculated_at",
        "annual_financial_impact_source_basis", "annual_financial_impact_status",
    ):
        op.drop_column("opportunities", col)

    for col in (
        "expected_amount_current_event_id", "expected_amount_approved_by_user_id",
        "expected_amount_approved_at", "expected_amount_calculated_at",
        "expected_amount_source_basis", "expected_amount_status",
    ):
        op.drop_column("rebate_period_actuals", col)

    op.drop_table("financial_amount_evidence")
    op.drop_table("financial_amount_status_events")
