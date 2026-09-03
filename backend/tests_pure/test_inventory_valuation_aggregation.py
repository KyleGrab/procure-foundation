"""
Tests for app.analytics.inventory_valuation_aggregation - the two genuinely pure pieces of this
phase's request (aggregate asset valuation, audit context shape), extracted out of what would
otherwise be DB-orchestration code so they can be real, executed tests rather than
written-not-run ones. Zero DB/network dependencies.
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.analytics.inventory_valuation_aggregation import (
    build_reconciliation_audit_context,
    calculate_batch_asset_valuation,
)


class TestCalculateBatchAssetValuation(unittest.TestCase):
    def test_sums_quantity_times_unit_cost_across_records(self):
        records = [
            {"quantity_on_hand": Decimal("124"), "unit_cost": Decimal("137.73")},
            {"quantity_on_hand": Decimal("674"), "unit_cost": Decimal("4.79")},
        ]
        # 124*137.73=17078.52, 674*4.79=3228.46 -> 20306.98
        self.assertEqual(calculate_batch_asset_valuation(records), Decimal("20306.98"))

    def test_never_sums_the_per_row_total_valuation_field_even_if_present(self):
        # total_valuation is a cross-check field only (inventory_valuation_validation.py's own
        # docstring) - the aggregate must always be recomputed from quantity*unit_cost, never
        # trust a possibly-inconsistent per-row total as the source of truth for the batch sum.
        records = [{"quantity_on_hand": Decimal("100"), "unit_cost": Decimal("10"), "total_valuation": Decimal("999999")}]
        self.assertEqual(calculate_batch_asset_valuation(records), Decimal("1000"))

    def test_empty_batch_returns_zero_not_error(self):
        self.assertEqual(calculate_batch_asset_valuation([]), Decimal("0"))

    def test_record_missing_unit_cost_is_excluded_not_treated_as_zero(self):
        # A record that failed validation (no unit_cost) contributing a silent $0 to the
        # aggregate would understate the batch total without any signal that something's missing -
        # excluded rows should never have been passed in as "validated_records" in the first
        # place, but this function defends against that anyway rather than silently miscounting.
        records = [
            {"quantity_on_hand": Decimal("100"), "unit_cost": Decimal("10")},
            {"quantity_on_hand": Decimal("50")},  # no unit_cost
        ]
        self.assertEqual(calculate_batch_asset_valuation(records), Decimal("1000"))


class TestBuildReconciliationAuditContext(unittest.TestCase):
    def test_context_shape_has_every_expected_field(self):
        context = build_reconciliation_audit_context(
            record_count=250, total_asset_valuation=Decimal("21895070.82"),
            snapshot_date=date(2026, 8, 26), file_hash="abc123",
        )
        self.assertEqual(context["record_count"], 250)
        self.assertEqual(context["total_asset_valuation"], "21895070.82")  # Decimal -> str for JSON safety
        self.assertEqual(context["snapshot_date"], "2026-08-26")
        self.assertEqual(context["file_hash"], "abc123")

    def test_file_hash_is_optional_and_omitted_not_null_when_absent(self):
        context = build_reconciliation_audit_context(
            record_count=1, total_asset_valuation=Decimal("100"), snapshot_date=date(2026, 8, 26), file_hash=None,
        )
        self.assertNotIn("file_hash", context)


if __name__ == "__main__":
    unittest.main()
