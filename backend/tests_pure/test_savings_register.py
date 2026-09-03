"""Covers the five savings types staying distinct (never blended), and the savings waterfall
showing per-stage totals, not cumulative ones."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.savings_register import (
    BaselineMethodology,
    SavingsType,
    calculate_cost_avoidance,
    calculate_efficiency_saving,
    calculate_hard_saving,
    calculate_margin_protection,
    calculate_savings_waterfall,
    calculate_working_capital_release,
)


class TestHardSaving(unittest.TestCase):
    def test_worked_example_from_spec(self):
        # spec Section 35's exact worked example: R100->R95, 20,000 units -> R100,000.
        result = calculate_hard_saving(
            Decimal("100"), Decimal("95"), Decimal("20000"),
            BaselineMethodology.PRIOR_SUPPLIER_PRICE,
        )
        self.assertEqual(result.amount, Decimal("100000.0000"))
        self.assertEqual(result.savings_type, SavingsType.HARD_SAVING)
        self.assertFalse(result.is_one_time)
        self.assertEqual(result.baseline_methodology, BaselineMethodology.PRIOR_SUPPLIER_PRICE)


class TestCostAvoidance(unittest.TestCase):
    def test_matches_phase2_cost_avoidance_formula(self):
        # Same figures as Phase 2's actual-cost-avoidance worked example (spec Section 84).
        result = calculate_cost_avoidance(Decimal("305"), Decimal("292"), Decimal("5000"))
        self.assertEqual(result.amount, Decimal("65000.0000"))
        self.assertIsNone(result.baseline_methodology)  # no prior-price baseline for this type


class TestWorkingCapital(unittest.TestCase):
    def test_is_flagged_as_one_time(self):
        result = calculate_working_capital_release(Decimal("50000"), 30, 60)
        self.assertTrue(result.is_one_time)
        self.assertEqual(result.amount, Decimal("1500000.0000"))  # 50000 * 30 extra days

    def test_shortened_terms_gives_negative_release(self):
        # Shortening payment terms is a working-capital cost, not a release - the sign must
        # reflect that, not be silently clamped to zero.
        result = calculate_working_capital_release(Decimal("50000"), 60, 30)
        self.assertLess(result.amount, 0)


class TestMarginProtection(unittest.TestCase):
    def test_margin_protection_calculation(self):
        result = calculate_margin_protection(Decimal("0.03"), Decimal("2000000"))
        self.assertEqual(result.amount, Decimal("60000.0000"))
        self.assertEqual(result.savings_type, SavingsType.MARGIN_PROTECTION)


class TestEfficiencySaving(unittest.TestCase):
    def test_efficiency_saving_calculation(self):
        result = calculate_efficiency_saving(Decimal("200"), Decimal("350"))
        self.assertEqual(result.amount, Decimal("70000.0000"))


class TestSavingsWaterfall(unittest.TestCase):
    def test_each_opportunity_contributes_to_exactly_one_stage(self):
        opportunities = [
            ("identified", Decimal("100000"), False),
            ("identified", Decimal("50000"), False),
            ("validated", Decimal("80000"), False),
            ("approved", Decimal("60000"), False),
            ("implementation", Decimal("40000"), False),
            ("realised", Decimal("30000"), False),
        ]
        totals = calculate_savings_waterfall(opportunities)
        self.assertEqual(totals.identified, Decimal("150000.0000"))
        self.assertEqual(totals.validated, Decimal("80000.0000"))
        self.assertEqual(totals.approved, Decimal("60000.0000"))
        self.assertEqual(totals.implementation, Decimal("40000.0000"))
        self.assertEqual(totals.realised, Decimal("30000.0000"))

    def test_unknown_status_is_silently_excluded_not_erroring(self):
        # 'rejected'/'expired' opportunities (spec Section 35's other two statuses) don't belong
        # in any waterfall stage total - excluded, not counted as zero-value noise or an error.
        opportunities = [("rejected", Decimal("100000"), False), ("identified", Decimal("50000"), False)]
        totals = calculate_savings_waterfall(opportunities)
        self.assertEqual(totals.identified, Decimal("50000.0000"))

    def test_empty_opportunity_list_gives_all_zero_totals(self):
        totals = calculate_savings_waterfall([])
        self.assertEqual(totals.identified, Decimal("0.0000"))
        self.assertEqual(totals.realised, Decimal("0.0000"))


if __name__ == "__main__":
    unittest.main()
