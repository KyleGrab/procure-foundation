"""
Tests for app/analytics/inventory_calculations.py (Phase 5b, ADR-018). Pure - no DB, no
framework - same §2.1 boundary as every analytics module. Written before the implementation
exists, per this turn's test-first sequence.
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.analytics.inventory_calculations import (
    ExpiryRisk,
    SnapshotRow,
    calculate_days_since_last_movement,
    calculate_excess_stock_value,
    classify_expiry_risk,
    validate_snapshot_grain,
)


class TestValidateSnapshotGrain(unittest.TestCase):
    def test_no_violations_when_all_keys_unique(self):
        rows = [
            SnapshotRow("Chicken Breast 5kg", "SKU1", 1, date(2026, 1, 1), row_index=0),
            SnapshotRow("Chicken Breast 5kg", "SKU1", 2, date(2026, 1, 1), row_index=1),  # different location
        ]
        self.assertEqual(validate_snapshot_grain(rows), [])

    def test_duplicate_key_flagged_with_both_row_indices(self):
        rows = [
            SnapshotRow("Chicken Breast 5kg", "SKU1", 1, date(2026, 1, 1), row_index=0),
            SnapshotRow("Chicken Breast 5kg", "SKU1", 1, date(2026, 1, 1), row_index=5),
        ]
        violations = validate_snapshot_grain(rows)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].row_indices, [0, 5])

    def test_empty_input_returns_empty_list_not_error(self):
        self.assertEqual(validate_snapshot_grain([]), [])

    def test_different_snapshot_dates_are_not_a_violation(self):
        rows = [
            SnapshotRow("Chicken Breast 5kg", "SKU1", 1, date(2026, 1, 1), row_index=0),
            SnapshotRow("Chicken Breast 5kg", "SKU1", 1, date(2026, 2, 1), row_index=1),
        ]
        self.assertEqual(validate_snapshot_grain(rows), [])


class TestDaysSinceLastMovement(unittest.TestCase):
    def test_single_snapshot_returns_none(self):
        self.assertIsNone(
            calculate_days_since_last_movement([(date(2026, 1, 1), Decimal("100"))], as_of=date(2026, 2, 1))
        )

    def test_flat_quantity_returns_days_since_earliest_snapshot(self):
        # No decrease anywhere in the series - "no confirmed movement for at least this long".
        snapshots = [
            (date(2026, 1, 1), Decimal("100")),
            (date(2026, 1, 15), Decimal("100")),
            (date(2026, 2, 1), Decimal("100")),
        ]
        result = calculate_days_since_last_movement(snapshots, as_of=date(2026, 2, 1))
        self.assertEqual(result, 31)  # Jan 1 -> Feb 1

    def test_decrease_is_movement_measured_from_the_decrease_date(self):
        snapshots = [
            (date(2026, 1, 1), Decimal("100")),
            (date(2026, 1, 10), Decimal("80")),  # decrease - movement here
        ]
        result = calculate_days_since_last_movement(snapshots, as_of=date(2026, 1, 20))
        self.assertEqual(result, 10)  # Jan 10 -> Jan 20

    def test_restock_after_movement_does_not_count_as_movement(self):
        # The case that would be easy to get backwards: an increase (restock) after a real
        # decrease must NOT reset the "since" measurement to the restock date - only a decrease
        # counts as movement.
        snapshots = [
            (date(2026, 1, 1), Decimal("100")),
            (date(2026, 1, 10), Decimal("80")),   # decrease - the real, most recent movement
            (date(2026, 1, 25), Decimal("150")),  # restock - not movement
        ]
        result = calculate_days_since_last_movement(snapshots, as_of=date(2026, 2, 1))
        self.assertEqual(result, 22)  # Jan 10 -> Feb 1, NOT Jan 25 -> Feb 1


class TestExcessStockValue(unittest.TestCase):
    def test_calculates_correctly_when_both_inputs_present(self):
        result = calculate_excess_stock_value(
            quantity_on_hand=Decimal("500"), reorder_level=Decimal("200"), unit_cost=Decimal("15"),
        )
        self.assertEqual(result, Decimal("4500.0000"))  # (500-200)*15

    def test_none_when_reorder_level_missing(self):
        self.assertIsNone(
            calculate_excess_stock_value(quantity_on_hand=Decimal("500"), reorder_level=None, unit_cost=Decimal("15"))
        )

    def test_none_when_unit_cost_missing(self):
        self.assertIsNone(
            calculate_excess_stock_value(quantity_on_hand=Decimal("500"), reorder_level=Decimal("200"), unit_cost=None)
        )

    def test_quantity_below_reorder_level_gives_zero_not_negative(self):
        result = calculate_excess_stock_value(
            quantity_on_hand=Decimal("50"), reorder_level=Decimal("200"), unit_cost=Decimal("15"),
        )
        self.assertEqual(result, Decimal("0.0000"))


class TestExpiryRiskClassification(unittest.TestCase):
    def test_no_expiry_date_is_not_tracked(self):
        self.assertEqual(classify_expiry_risk(None, as_of=date(2026, 1, 1)), ExpiryRisk.NO_EXPIRY_TRACKED)

    def test_past_expiry_date_is_expired(self):
        self.assertEqual(
            classify_expiry_risk(date(2026, 1, 1), as_of=date(2026, 1, 15)), ExpiryRisk.EXPIRED
        )

    def test_within_warning_window_is_expiring_soon(self):
        self.assertEqual(
            classify_expiry_risk(date(2026, 1, 20), as_of=date(2026, 1, 1), warning_window_days=30),
            ExpiryRisk.EXPIRING_SOON,
        )

    def test_beyond_warning_window_is_healthy(self):
        self.assertEqual(
            classify_expiry_risk(date(2026, 6, 1), as_of=date(2026, 1, 1), warning_window_days=30),
            ExpiryRisk.HEALTHY,
        )

    def test_exact_boundary_at_warning_window_is_expiring_soon(self):
        # Exactly 30 days out with a 30-day window - the boundary case most likely to get an
        # off-by-one wrong.
        self.assertEqual(
            classify_expiry_risk(date(2026, 1, 31), as_of=date(2026, 1, 1), warning_window_days=30),
            ExpiryRisk.EXPIRING_SOON,
        )

    def test_configurable_warning_window_is_actually_applied(self):
        # Same 20-day gap: healthy with a 10-day window, expiring_soon with a 30-day window -
        # proves the parameter changes the outcome, not just accepted and ignored.
        expiry, as_of = date(2026, 1, 21), date(2026, 1, 1)
        self.assertEqual(classify_expiry_risk(expiry, as_of, warning_window_days=10), ExpiryRisk.HEALTHY)
        self.assertEqual(classify_expiry_risk(expiry, as_of, warning_window_days=30), ExpiryRisk.EXPIRING_SOON)


class TestDeterminism(unittest.TestCase):
    def test_module_never_calls_now_or_today(self):
        # A naive substring check on the raw source would also match this rule's own explanation
        # in the module's docstring ("never datetime.now() called...") - caught by actually
        # running this test, not assumed safe. AST-based instead: walks the real parsed code for
        # an Attribute access named 'now' or 'today' (covers datetime.now(), date.today(), etc.),
        # ignoring anything in a docstring or comment since those aren't part of the AST at all.
        import ast

        import app.analytics.inventory_calculations as module

        tree = ast.parse(open(module.__file__).read())
        forbidden_calls = [
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ("now", "today")
        ]
        self.assertEqual(forbidden_calls, [])


if __name__ == "__main__":
    unittest.main()
