"""
Tests for Gate C: markdown-adjusted GMROI (app.analytics.management_accounting) and the 13-week
rolling cash model (app.analytics.cash_forecast). Real anchor: R21,895,070.82, the same reconciled
MAC control total used throughout this engagement. Everything dispute/unapplied-cash/GRNI-related
is [DEMO] - no real monetary figure for any of these exists anywhere in this engagement; only the
real GoodsReceipt table's existence (confirmed before writing this) grounds GRNI as a genuine,
traceable concept, not its actual Rand value here.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.cash_forecast import (
    build_13_week_cash_forecast,
    calculate_weekly_cash_position,
    resolve_weekly_cash_receipts,
    resolve_weekly_supplier_payments,
)
from app.analytics.management_accounting import calculate_markdown_adjusted_gmroi


class TestMarkdownAdjustedGmroi(unittest.TestCase):
    def test_real_control_total_with_demo_at_risk_inventory_reduces_gmroi_below_the_unadjusted_figure(self):
        # Real: average_inventory_value anchored to R21,895,070.82. [DEMO]: at_risk_inventory_value
        # and markdown_pct - no real expiry-lot data exists anywhere in this engagement.
        unadjusted = calculate_markdown_adjusted_gmroi(
            gross_margin=Decimal("65808099.88"), average_inventory_value=Decimal("21895070.82"),
            at_risk_inventory_value=Decimal(0), markdown_pct=Decimal("0.5"),
        )
        adjusted = calculate_markdown_adjusted_gmroi(
            gross_margin=Decimal("65808099.88"), average_inventory_value=Decimal("21895070.82"),
            at_risk_inventory_value=Decimal(500000), markdown_pct=Decimal("0.5"),  # [DEMO]
        )
        self.assertLess(adjusted, unadjusted)

    def test_zero_at_risk_inventory_gives_the_same_result_as_the_unadjusted_calculate_gmroi(self):
        # Confirms this function REUSES calculate_gmroi rather than reimplementing the division -
        # zero markdown impact must reduce to byte-identical output.
        from app.analytics.management_accounting import calculate_gmroi
        via_markdown_fn = calculate_markdown_adjusted_gmroi(
            gross_margin=Decimal("65808099.88"), average_inventory_value=Decimal("21895070.82"),
            at_risk_inventory_value=Decimal(0), markdown_pct=Decimal("0.5"),
        )
        via_original_fn = calculate_gmroi(
            gross_margin=Decimal("65808099.88"), average_inventory_value=Decimal("21895070.82"),
        )
        self.assertEqual(via_markdown_fn, via_original_fn)

    def test_zero_average_inventory_still_returns_none_not_a_divide_by_zero_error(self):
        # The underlying calculate_gmroi's own zero-denominator guard must still apply - this
        # function doesn't bypass it.
        result = calculate_markdown_adjusted_gmroi(
            gross_margin=Decimal(100000), average_inventory_value=Decimal(0),
            at_risk_inventory_value=Decimal(50000), markdown_pct=Decimal("0.5"),
        )
        self.assertIsNone(result)


class TestResolveWeeklyCashReceiptsAndPayments(unittest.TestCase):
    def test_demo_disputed_amount_reduces_receipts_unapplied_cash_increases_it(self):
        # [DEMO] throughout - no real dispute/unapplied-cash figures exist anywhere.
        result = resolve_weekly_cash_receipts(
            contractual_dso_expected_receipts=Decimal(500000),
            disputed_amount=Decimal(40000), unapplied_cash=Decimal(15000),
        )
        self.assertEqual(result, Decimal("475000.0000"))  # 500000 - 40000 + 15000

    def test_demo_grni_adds_to_expected_payments_not_subtracts(self):
        # GRNI is a real, additional forward obligation (goods physically received, not yet
        # invoiced) that a contractual-DPO-only schedule would miss entirely - added, never
        # subtracted, since it's real future outflow, not an offset.
        result = resolve_weekly_supplier_payments(
            contractual_dpo_expected_payments=Decimal(300000), grni_amount=Decimal(60000),  # [DEMO]
        )
        self.assertEqual(result, Decimal("360000.0000"))


class TestWeeklyCashPosition(unittest.TestCase):
    def test_demo_positive_week_is_not_flagged_as_overdraft(self):
        result = calculate_weekly_cash_position(
            starting_cash=Decimal(1000000), resolved_cash_receipts=Decimal(475000),
            forced_supplier_payments=Decimal(360000), gate_b_operational_cost_pools=Decimal(50000),
        )
        self.assertEqual(result["ending_cash"], Decimal("1065000.0000"))
        self.assertFalse(result["is_overdraft"])

    def test_demo_week_that_drops_below_zero_is_explicitly_flagged_as_overdraft(self):
        # The "stark liquidity risk indicator" named explicitly in this request - is_overdraft is
        # a first-class, queryable field, not something inferred from a bare negative number.
        result = calculate_weekly_cash_position(
            starting_cash=Decimal(100000), resolved_cash_receipts=Decimal(50000),
            forced_supplier_payments=Decimal(120000), gate_b_operational_cost_pools=Decimal(50000),
        )
        self.assertEqual(result["ending_cash"], Decimal("-20000.0000"))
        self.assertTrue(result["is_overdraft"])


class TestThirteenWeekCashForecast(unittest.TestCase):
    def _demo_week(self, receipts="200000", payments="150000", cost_pools="30000"):
        return {
            "resolved_cash_receipts": Decimal(receipts), "forced_supplier_payments": Decimal(payments),
            "gate_b_operational_cost_pools": Decimal(cost_pools),
        }

    def test_demo_all_13_weeks_present_and_resolved_produces_a_complete_forecast(self):
        weeks = [self._demo_week() for _ in range(13)]
        forecast = build_13_week_cash_forecast(opening_cash=Decimal(1000000), weekly_inputs=weeks)
        self.assertTrue(forecast["is_complete"])
        self.assertEqual(len(forecast["weeks"]), 13)

    def test_fewer_than_13_weeks_locks_the_whole_model_not_a_partial_result(self):
        weeks = [self._demo_week() for _ in range(10)]
        forecast = build_13_week_cash_forecast(opening_cash=Decimal(1000000), weekly_inputs=weeks)
        self.assertFalse(forecast["is_complete"])
        self.assertIsNone(forecast["weeks"])

    def test_a_single_missing_input_in_one_of_13_weeks_locks_the_entire_forecast(self):
        # The explicit Gate C requirement: one missing input anywhere must never produce a
        # forecast that's "complete except for week 7" - the whole 13-week model locks.
        weeks = [self._demo_week() for _ in range(13)]
        weeks[6]["gate_b_operational_cost_pools"] = None  # week 7 (0-indexed 6) missing
        forecast = build_13_week_cash_forecast(opening_cash=Decimal(1000000), weekly_inputs=weeks)
        self.assertFalse(forecast["is_complete"])
        self.assertIn("week 7", forecast["error"])

    def test_missing_opening_cash_is_a_type_error_not_a_silent_zero_starting_balance(self):
        # Point 3's explicit named example: the current bank ledger balance missing must lock
        # the model, not default to a fabricated zero starting position.
        weeks = [self._demo_week() for _ in range(13)]
        with self.assertRaises(TypeError):
            build_13_week_cash_forecast(weekly_inputs=weeks)

    def test_demo_first_overdraft_week_is_correctly_identified_as_week_3(self):
        # Directly answers this request's own two-test ask: a shift in dispute volume (modelled
        # here as a lower resolved_cash_receipts figure feeding week 3) changes the detected
        # overdraft boundary - confirmed by construction, not asserted.
        weeks = [self._demo_week() for _ in range(13)]
        weeks[2] = self._demo_week(receipts="20000")  # [DEMO] week 3: a real dispute spike would
        # look exactly like this - real receipts collapse below what forced payments require.
        forecast = build_13_week_cash_forecast(opening_cash=Decimal(50000), weekly_inputs=weeks)
        self.assertEqual(forecast["first_overdraft_week"], 3)

    def test_demo_resolving_the_dispute_before_week_3_removes_the_overdraft_entirely(self):
        # The second of the two requested tests: proves the forecast is genuinely sensitive to a
        # dispute-volume shift, not just capable of flagging one fixed scenario - the SAME week 3
        # with normal (dispute-resolved) receipts produces no overdraft at all.
        weeks = [self._demo_week() for _ in range(13)]
        forecast = build_13_week_cash_forecast(opening_cash=Decimal(50000), weekly_inputs=weeks)
        self.assertIsNone(forecast["first_overdraft_week"])


if __name__ == "__main__":
    unittest.main()
