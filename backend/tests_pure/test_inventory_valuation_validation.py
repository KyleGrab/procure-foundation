"""
Tests for app.ingestion.inventory_valuation_mapping / inventory_valuation_validation. Written
before the implementation, per this sprint's test-first sequence. Zero DB/network dependencies -
pure string/Decimal handling only.

Real Gourmet-shaped header names (stock_code, mac_unit_cost, etc.) are used for the mapping
tests, since these are genuine column-name conventions from the real, uploaded Crystal Reports
export - not invented. Boundary/malformed-row cases use synthetic rows explicitly prefixed
[DEMO], per this sprint's own rule that mock data must be clearly identifiable as such.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.ingestion.inventory_valuation_mapping import (
    suggest_inventory_valuation_mapping,
)
from app.ingestion.inventory_valuation_validation import validate_inventory_valuation_rows
from app.ingestion.validation import IssueSeverity


class TestInventoryValuationMapping(unittest.TestCase):
    def test_maps_onto_the_existing_inventory_snapshot_canonical_fields_not_new_ones(self):
        # The whole point of this module: Gourmet's vocabulary resolves to the SAME canonical
        # fields app.ingestion.inventory_mapping already defines (Phase 5b) - not a parallel,
        # disconnected field set that would never actually connect to InventorySnapshot.
        # suggest_mapping returns {canonical_field: source_column}, not the reverse.
        mapping = suggest_inventory_valuation_mapping(
            ["Stock Code", "Description", "Qty On Hand", "MAC Unit Cost", "Total Valuation"]
        )
        self.assertEqual(mapping["supplier_sku"], "Stock Code")
        self.assertEqual(mapping["unit_cost"], "MAC Unit Cost")
        self.assertEqual(mapping["quantity_on_hand"], "Qty On Hand")

    def test_total_valuation_maps_to_its_own_validation_only_field(self):
        # total_valuation is deliberately NOT one of InventorySnapshot's real columns - it exists
        # only to cross-check quantity_on_hand * unit_cost, never to be persisted as a third,
        # independently-drifting figure.
        mapping = suggest_inventory_valuation_mapping(["Total Valuation"])
        self.assertEqual(mapping["total_valuation"], "Total Valuation")

    def test_real_gourmet_header_variants_all_resolve(self):
        for header, expected_canonical in [
            ("stock_code", "supplier_sku"), ("item_code", "supplier_sku"), ("sku", "supplier_sku"),
            ("stock_description", "description"), ("closing_stock", "quantity_on_hand"),
            ("qoh", "quantity_on_hand"), ("moving_avg_cost", "unit_cost"), ("avg_cost", "unit_cost"),
            ("asset_value", "total_valuation"), ("total_cost", "total_valuation"),
        ]:
            with self.subTest(header=header):
                mapping = suggest_inventory_valuation_mapping([header])
                self.assertEqual(mapping[expected_canonical], header)


class TestInventoryValuationRowValidation(unittest.TestCase):
    def _valid_row(self, **overrides):
        row = {
            "supplier_sku": "SKU004", "description": "BEEF MINCE 1KG",
            "quantity_on_hand": "124", "unit_cost": "137.73", "total_valuation": "R17,079.14",
        }
        row.update(overrides)
        return row

    def test_valid_row_with_currency_symbols_and_commas_is_accepted(self):
        results = validate_inventory_valuation_rows([self._valid_row()])
        self.assertTrue(results[0]["is_valid"])

    def test_currency_symbols_and_commas_are_stripped_from_every_numeric_field(self):
        results = validate_inventory_valuation_rows(
            [self._valid_row(unit_cost="R 137.73", total_valuation="R17,079.14")]
        )
        self.assertEqual(results[0]["parsed"]["unit_cost"], Decimal("137.73"))
        self.assertEqual(results[0]["parsed"]["total_valuation"], Decimal("17079.14"))

    def test_dollar_sign_is_also_stripped_not_just_rand(self):
        results = validate_inventory_valuation_rows([self._valid_row(unit_cost="$137.73")])
        self.assertEqual(results[0]["parsed"]["unit_cost"], Decimal("137.73"))

    def test_malformed_numeric_string_is_an_error(self):
        results = validate_inventory_valuation_rows([self._valid_row(unit_cost="not-a-number")])
        issues = [i for i in results[0]["issues"] if i.field == "unit_cost"]
        self.assertEqual(issues[0].severity, IssueSeverity.ERROR)
        self.assertFalse(results[0]["is_valid"])

    def test_negative_quantity_on_hand_is_a_warning_not_an_error(self):
        # Per this phase's own spec: flagged, not rejected - a real (if unusual) back-order/
        # adjustment state, same posture as working_capital_validation's negative AR/AP handling.
        results = validate_inventory_valuation_rows([self._valid_row(quantity_on_hand="-5")])
        issues = [i for i in results[0]["issues"] if i.field == "quantity_on_hand"]
        self.assertEqual(issues[0].severity, IssueSeverity.WARNING)
        self.assertTrue(results[0]["is_valid"])  # a warning never blocks ingestion

    def test_total_valuation_matching_quantity_times_unit_cost_within_tolerance_is_clean(self):
        # 124 * 137.73 = 17078.52, vs stated 17079.14 - a 0.62 difference, which is OUTSIDE the
        # R0.01 tolerance, so this specific worked example should actually warn (see next test).
        # This test instead uses an exact match to confirm the clean case has zero cross-check issues.
        results = validate_inventory_valuation_rows(
            [self._valid_row(quantity_on_hand="100", unit_cost="10.00", total_valuation="1000.00")]
        )
        cross_check_issues = [i for i in results[0]["issues"] if i.field == "total_valuation"]
        self.assertEqual(cross_check_issues, [])

    def test_total_valuation_outside_tolerance_is_a_warning_not_an_error(self):
        # A source-data inconsistency worth flagging for review, but not a reason to reject an
        # otherwise-usable row - the core fields (sku, quantity, unit_cost) are still correct
        # even if the source's own pre-computed total column disagrees slightly.
        results = validate_inventory_valuation_rows(
            [self._valid_row(quantity_on_hand="100", unit_cost="10.00", total_valuation="1050.00")]
        )
        issues = [i for i in results[0]["issues"] if i.field == "total_valuation"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, IssueSeverity.WARNING)
        self.assertTrue(results[0]["is_valid"])

    def test_total_valuation_within_one_cent_tolerance_is_not_flagged(self):
        results = validate_inventory_valuation_rows(
            [self._valid_row(quantity_on_hand="100", unit_cost="10.00", total_valuation="1000.01")]
        )
        issues = [i for i in results[0]["issues"] if i.field == "total_valuation"]
        self.assertEqual(issues, [])

    def test_missing_total_valuation_skips_the_cross_check_not_an_error(self):
        # total_valuation is a cross-check field, not a required one - some source formats won't
        # have it at all, and that's fine.
        row = self._valid_row()
        del row["total_valuation"]
        results = validate_inventory_valuation_rows([row])
        self.assertTrue(results[0]["is_valid"])

    def test_demo_missing_required_column_is_an_explicit_error_not_a_silent_skip(self):
        demo_row = {"description": "[DEMO] Row missing supplier_sku entirely"}
        results = validate_inventory_valuation_rows([demo_row])
        self.assertFalse(results[0]["is_valid"])
        issues = [i for i in results[0]["issues"] if i.field == "supplier_sku"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, IssueSeverity.ERROR)

    def test_demo_empty_row_list_returns_empty_list_not_error(self):
        self.assertEqual(validate_inventory_valuation_rows([]), [])

    def test_demo_completely_malformed_row_reports_every_missing_field_not_just_the_first(self):
        demo_row = {"description": "[DEMO] Every required field absent"}
        results = validate_inventory_valuation_rows([demo_row])
        error_fields = {i.field for i in results[0]["issues"] if i.severity == IssueSeverity.ERROR}
        self.assertEqual(error_fields, {"supplier_sku", "quantity_on_hand", "unit_cost"})

    def test_multiple_rows_each_retain_their_own_field_row_number_and_issues_without_bleed(self):
        # BACKEND-RUFF-B023-REVIEW-R1: _parse_required_decimal is a closure defined fresh inside
        # the row loop, over `row`/`issues`/`idx` - flagged by Ruff's B023 (function does not
        # bind loop variable) even though it's always called within the same iteration that
        # defines it. This is the multi-row proof that no gap in the previous single-row-only
        # test suite could have caught: three distinct rows, each with its own defect (or none),
        # in one call - proving row 1's missing quantity_on_hand never leaks into row 2's issues,
        # row 2's malformed unit_cost never leaks into row 1's or row 3's, and every issue is
        # tagged with its OWN row's row_number, not a stale or shared one.
        results = validate_inventory_valuation_rows([
            self._valid_row(quantity_on_hand=""),  # [DEMO] row 1: missing quantity_on_hand
            self._valid_row(unit_cost="not-a-number"),  # [DEMO] row 2: malformed unit_cost
            # [DEMO] row 3: fully valid, including a total_valuation that exactly matches
            # quantity_on_hand * unit_cost (124 * 137.73 = 17078.52) - genuinely issue-free,
            # not just error-free, so this row is an unambiguous "nothing to report" control.
            self._valid_row(total_valuation="17078.52"),
        ])
        self.assertEqual(len(results), 3)

        row_1, row_2, row_3 = results
        self.assertEqual(row_1["row_number"], 1)
        self.assertEqual(row_2["row_number"], 2)
        self.assertEqual(row_3["row_number"], 3)

        self.assertFalse(row_1["is_valid"])
        self.assertEqual(len(row_1["issues"]), 1)
        self.assertEqual(row_1["issues"][0].row_number, 1)
        self.assertEqual(row_1["issues"][0].field, "quantity_on_hand")
        self.assertEqual(row_1["issues"][0].severity, IssueSeverity.ERROR)

        self.assertFalse(row_2["is_valid"])
        self.assertEqual(len(row_2["issues"]), 1)
        self.assertEqual(row_2["issues"][0].row_number, 2)
        self.assertEqual(row_2["issues"][0].field, "unit_cost")
        self.assertEqual(row_2["issues"][0].severity, IssueSeverity.ERROR)

        self.assertTrue(row_3["is_valid"])
        self.assertEqual(row_3["issues"], [])

        # No cross-iteration bleed: row 1 never sees row 2's field, row 2 never sees row 1's.
        self.assertNotIn("unit_cost", {i.field for i in row_1["issues"]})
        self.assertNotIn("quantity_on_hand", {i.field for i in row_2["issues"]})


if __name__ == "__main__":
    unittest.main()
