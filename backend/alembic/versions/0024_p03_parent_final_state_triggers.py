"""P03-CORE-R1: validate the CURRENT parent row at commit, not the historical trigger-event image.

Migration 0021's three deferred parent-state constraint triggers - check_rpa_expected_amount_
matches_event, check_opp_annual_financial_impact_matches_event, check_opp_realised_savings_
matches_event - are `AFTER INSERT OR UPDATE ... DEFERRABLE INITIALLY DEFERRED ... FOR EACH ROW`,
and their functions validate the trigger's `NEW` record directly.

That is a real defect, not a test artifact - empirically reproduced against this migration's own
schema, independent of any ORM/fixture/pytest, with a plain psycopg script and explicit
prerequisite rows:

    BEGIN;
    INSERT INTO rebate_period_actuals (..., expected_amount_current_event_id) VALUES (..., NULL);
    INSERT INTO financial_amount_status_events (...) VALUES (...) RETURNING id;   -- genesis event
    UPDATE rebate_period_actuals SET expected_amount_current_event_id = <event id> WHERE id = ...;
    COMMIT;

fails with "expected_amount_current_event_id must not be NULL at commit", even though the row's
final, committed-in-this-transaction state has a valid, correctly-set pointer. Postgres queues one
deferred trigger firing per triggering *statement*, each carrying the row image as of that
statement - the initial INSERT (with a NULL pointer, unavoidable: the event needs this row's id,
and this row's pointer needs the event's id - see RebatePeriodActual's docstring) queues its own
firing with NEW.expected_amount_current_event_id = NULL, and that firing executes at commit
regardless of the later UPDATE's own (correct) firing. The same reproduction, same result, applies
to Opportunity's annual_financial_impact and realised_savings pointers.

This is exactly the intended lifecycle (RebatePeriodActual's own docstring: "resolved by inserting
this row with a NULL pointer, then the genesis event, then updating the pointer - all in one
transaction, checked only at COMMIT") and exactly what app/services/rebate_service.py's
record_period_actual()/_write_expected_amount_event() and
app/services/opportunity_service.py's create_opportunity()/_write_opportunity_measure_event() both
do - so this is a production defect blocking the real service paths, not merely a test-fixture
shortcoming. (A second, independent production defect in those same two service functions -
genesis events not writing NULL old_* fields - is fixed alongside this migration in the same
P03-CORE-R1 commit; see ck_famev_genesis_old_fields_null and this migration's sibling service
changes. Neither fix alone makes the real service paths succeed.)

Fix: each function now looks up the CURRENT, final persisted parent row (SELECT ... WHERE id =
NEW.id) instead of trusting NEW, and validates that. Within one transaction, a later statement
always sees the effects of earlier statements in the same transaction (ordinary read-your-own-
writes visibility) - by the time these deferred triggers actually run (just before commit), the
row reflects every write this transaction made to it, including the pointer UPDATE. Semantics,
messages, and every existing check (mismatch, snapshot equality, latest-event) are otherwise
unchanged. If the row no longer exists (deleted later in the same transaction, before commit)
there is no surviving parent row to validate an invariant on, so the trigger returns without
raising - a genuinely dead row triggers no false failure, and there is no evidence any command in
this codebase hard-deletes rebate_period_actuals/opportunities rows (both are business records
created once via the service layer above, never destructively removed).
"""
from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION check_rpa_expected_amount_matches_event() RETURNS TRIGGER AS $$
        DECLARE current_row rebate_period_actuals%ROWTYPE; ev financial_amount_status_events%ROWTYPE; latest_id BIGINT;
        BEGIN
          SELECT * INTO current_row FROM rebate_period_actuals WHERE id = NEW.id;
          IF NOT FOUND THEN
            RETURN NEW;
          END IF;

          IF current_row.expected_amount_current_event_id IS NULL THEN
            RAISE EXCEPTION 'rebate_period_actual %: expected_amount_current_event_id must not be NULL at commit', current_row.id;
          END IF;

          SELECT * INTO ev FROM financial_amount_status_events WHERE id = current_row.expected_amount_current_event_id;
          IF ev.organisation_id != current_row.organisation_id OR ev.rebate_period_actual_id != current_row.id
             OR ev.measure_code != 'expected_amount' THEN
            RAISE EXCEPTION 'rebate_period_actual %: current_event_id does not reference a matching event', current_row.id;
          END IF;
          IF current_row.expected_amount IS DISTINCT FROM ev.new_amount
             OR current_row.expected_amount_status IS DISTINCT FROM ev.new_status
             OR current_row.expected_amount_source_basis IS DISTINCT FROM ev.new_source_basis
             OR current_row.expected_amount_calculated_at IS DISTINCT FROM ev.new_calculated_at
             OR current_row.expected_amount_approved_at IS DISTINCT FROM ev.new_approved_at
             OR current_row.expected_amount_approved_by_user_id IS DISTINCT FROM ev.new_approved_by_user_id THEN
            RAISE EXCEPTION 'rebate_period_actual %: snapshot does not match its current event', current_row.id;
          END IF;

          SELECT id INTO latest_id FROM financial_amount_status_events
            WHERE rebate_period_actual_id = current_row.id AND measure_code = 'expected_amount'
            ORDER BY event_version DESC LIMIT 1;
          IF latest_id != current_row.expected_amount_current_event_id THEN
            RAISE EXCEPTION 'rebate_period_actual %: current_event_id is not the latest event', current_row.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION check_opp_annual_financial_impact_matches_event() RETURNS TRIGGER AS $$
        DECLARE current_row opportunities%ROWTYPE; ev financial_amount_status_events%ROWTYPE; latest_id BIGINT;
        BEGIN
          SELECT * INTO current_row FROM opportunities WHERE id = NEW.id;
          IF NOT FOUND THEN
            RETURN NEW;
          END IF;

          IF current_row.annual_financial_impact_current_event_id IS NULL THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact_current_event_id must not be NULL at commit', current_row.id;
          END IF;
          SELECT * INTO ev FROM financial_amount_status_events WHERE id = current_row.annual_financial_impact_current_event_id;
          IF ev.organisation_id != current_row.organisation_id OR ev.opportunity_id != current_row.id
             OR ev.measure_code != 'annual_financial_impact' THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact_current_event_id mismatch', current_row.id;
          END IF;
          IF current_row.annual_financial_impact IS DISTINCT FROM ev.new_amount
             OR current_row.annual_financial_impact_status IS DISTINCT FROM ev.new_status
             OR current_row.annual_financial_impact_source_basis IS DISTINCT FROM ev.new_source_basis
             OR current_row.annual_financial_impact_calculated_at IS DISTINCT FROM ev.new_calculated_at
             OR current_row.annual_financial_impact_effective_from IS DISTINCT FROM ev.new_effective_period_start THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact snapshot does not match its current event', current_row.id;
          END IF;
          SELECT id INTO latest_id FROM financial_amount_status_events
            WHERE opportunity_id = current_row.id AND measure_code = 'annual_financial_impact'
            ORDER BY event_version DESC LIMIT 1;
          IF latest_id != current_row.annual_financial_impact_current_event_id THEN
            RAISE EXCEPTION 'opportunity %: annual_financial_impact current_event_id is not the latest event', current_row.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION check_opp_realised_savings_matches_event() RETURNS TRIGGER AS $$
        DECLARE current_row opportunities%ROWTYPE; ev financial_amount_status_events%ROWTYPE; latest_id BIGINT;
        BEGIN
          SELECT * INTO current_row FROM opportunities WHERE id = NEW.id;
          IF NOT FOUND THEN
            RETURN NEW;
          END IF;

          IF current_row.realised_savings_current_event_id IS NULL THEN
            RAISE EXCEPTION 'opportunity %: realised_savings_current_event_id must not be NULL at commit', current_row.id;
          END IF;
          SELECT * INTO ev FROM financial_amount_status_events WHERE id = current_row.realised_savings_current_event_id;
          IF ev.organisation_id != current_row.organisation_id OR ev.opportunity_id != current_row.id
             OR ev.measure_code != 'realised_savings' THEN
            RAISE EXCEPTION 'opportunity %: realised_savings_current_event_id mismatch', current_row.id;
          END IF;
          IF current_row.realised_savings IS DISTINCT FROM ev.new_amount
             OR current_row.realised_savings_status IS DISTINCT FROM ev.new_status
             OR current_row.realised_savings_source_basis IS DISTINCT FROM ev.new_source_basis
             OR current_row.realised_savings_calculated_at IS DISTINCT FROM ev.new_calculated_at
             OR current_row.realised_savings_approved_at IS DISTINCT FROM ev.new_approved_at
             OR current_row.realised_savings_approved_by_user_id IS DISTINCT FROM ev.new_approved_by_user_id
             OR current_row.realised_savings_effective_period_start IS DISTINCT FROM ev.new_effective_period_start
             OR current_row.realised_savings_effective_period_end IS DISTINCT FROM ev.new_effective_period_end THEN
            RAISE EXCEPTION 'opportunity %: realised_savings snapshot does not match its current event', current_row.id;
          END IF;
          SELECT id INTO latest_id FROM financial_amount_status_events
            WHERE opportunity_id = current_row.id AND measure_code = 'realised_savings'
            ORDER BY event_version DESC LIMIT 1;
          IF latest_id != current_row.realised_savings_current_event_id THEN
            RAISE EXCEPTION 'opportunity %: realised_savings current_event_id is not the latest event', current_row.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
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
