"""Covers spec Section 39's calculation-related required test cases: price increase/decrease/
unchanged, zero old price, annual impact, annualisation, margin impact, target price, cost
avoidance."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.price_review_calculations import (
    calculate_actual_cost_avoidance,
    calculate_annual_impact,
    calculate_annualized_quantity,
    calculate_gross_margin,
    calculate_percentage_change,
    calculate_potential_cost_avoidance,
    calculate_price_change,
    calculate_required_selling_price,
    classify_movement_type,
    classify_risk,
)
from app.analytics.price_review_summary import (
    PriceReviewLineForSummary,
    summarize,
    weighted_average_increase,
)


class TestPriceMovement(unittest.TestCase):
    def test_price_increase(self):
        change = calculate_price_change(Decimal(280), Decimal(305))
        pct = calculate_percentage_change(Decimal(280), Decimal(305))
        self.assertEqual(change, Decimal("25.0000"))
        self.assertAlmostEqual(float(pct), 0.089286, places=5)
        self.assertEqual(classify_movement_type(
            is_matched=True, is_new=False, is_discontinued=False, pack_changed=False,
            percentage_change=pct,
        ), "price_increase")

    def test_price_decrease(self):
        pct = calculate_percentage_change(Decimal(100), Decimal(90))
        self.assertLess(pct, 0)
        self.assertEqual(classify_movement_type(
            is_matched=True, is_new=False, is_discontinued=False, pack_changed=False,
            percentage_change=pct,
        ), "price_decrease")

    def test_unchanged_price(self):
        pct = calculate_percentage_change(Decimal(100), Decimal(100))
        self.assertEqual(pct, Decimal(0))
        self.assertEqual(classify_movement_type(
            is_matched=True, is_new=False, is_discontinued=False, pack_changed=False,
            percentage_change=pct,
        ), "no_change")

    def test_zero_old_price_returns_none_not_an_error_or_zero(self):
        # spec Section 39's explicit "zero old price" case - must not silently produce 0% or
        # blow up with a ZeroDivisionError deep in a report.
        pct = calculate_percentage_change(Decimal(0), Decimal(50))
        self.assertIsNone(pct)

    def test_new_and_discontinued_never_get_a_percentage_movement(self):
        # spec Section 11: "do not calculate percentage price movements for unmatched new or
        # discontinued products" - enforced structurally by classify_movement_type's ordering.
        self.assertEqual(classify_movement_type(
            is_matched=False, is_new=True, is_discontinued=False, pack_changed=False,
            percentage_change=Decimal("0.5"),
        ), "new_product")
        self.assertEqual(classify_movement_type(
            is_matched=False, is_new=False, is_discontinued=True, pack_changed=False,
            percentage_change=None,
        ), "discontinued")


class TestAnnualImpact(unittest.TestCase):
    def test_annual_impact_worked_example(self):
        # spec Section 14's exact worked example.
        change = calculate_price_change(Decimal(280), Decimal(305))
        impact = calculate_annual_impact(change, Decimal(5000))
        self.assertEqual(impact, Decimal("125000.0000"))

    def test_annualisation_confidence_tiers(self):
        annualized_full, confidence_full = calculate_annualized_quantity(Decimal(1000), Decimal(12))
        self.assertEqual(confidence_full, "high")
        self.assertEqual(annualized_full, Decimal("1000.0000"))

        annualized_partial, confidence_partial = calculate_annualized_quantity(Decimal(500), Decimal(6))
        self.assertEqual(confidence_partial, "medium")
        self.assertEqual(annualized_partial, Decimal("1000.0000"))

        annualized_low, confidence_low = calculate_annualized_quantity(Decimal(100), Decimal(3))
        self.assertEqual(confidence_low, "low")


class TestMarginImpact(unittest.TestCase):
    def test_margin_impact_worked_example(self):
        old_profit, old_margin_pct = calculate_gross_margin(Decimal(500), Decimal(350))
        new_profit, new_margin_pct = calculate_gross_margin(Decimal(500), Decimal(375))
        self.assertEqual(old_profit, Decimal("150.0000"))
        self.assertEqual(new_profit, Decimal("125.0000"))
        self.assertLess(new_margin_pct, old_margin_pct)


class TestRequiredSellingPrice(unittest.TestCase):
    def test_required_selling_price_for_target_margin(self):
        required = calculate_required_selling_price(Decimal(70), Decimal("0.30"))
        self.assertEqual(required, Decimal("100.0000"))


class TestCostAvoidance(unittest.TestCase):
    def test_target_price_and_potential_cost_avoidance(self):
        potential = calculate_potential_cost_avoidance(
            requested_new_price=Decimal(305), target_price=Decimal(290), annual_quantity=Decimal(5000)
        )
        self.assertEqual(potential, Decimal("75000.0000"))

    def test_actual_cost_avoidance_after_negotiation(self):
        actual = calculate_actual_cost_avoidance(
            requested_new_price=Decimal(305),
            final_negotiated_price=Decimal(292),
            annual_quantity=Decimal(5000),
        )
        self.assertEqual(actual, Decimal("65000.0000"))  # matches spec Section 84's own example


class TestRiskClassification(unittest.TestCase):
    def test_default_thresholds(self):
        self.assertEqual(classify_risk(Decimal("0.01")), "low")
        self.assertEqual(classify_risk(Decimal("0.04")), "medium")
        self.assertEqual(classify_risk(Decimal("0.08")), "high")
        self.assertEqual(classify_risk(Decimal("0.15")), "critical")
        self.assertEqual(classify_risk(None), "unclassified")


class TestSupplierSummary(unittest.TestCase):
    def test_weighted_average_not_a_naive_mean(self):
        # A tiny SKU with a huge percentage increase must not dominate a spend-weighted average.
        lines = [
            PriceReviewLineForSummary(
                movement_type="price_increase", percentage_change=Decimal("0.40"),
                annual_impact=Decimal(800), annual_quantity=Decimal(20), pack_changed=False,
                requires_review=False,
            ),
            PriceReviewLineForSummary(
                movement_type="price_increase", percentage_change=Decimal("0.03"),
                annual_impact=Decimal(300000), annual_quantity=Decimal(100000), pack_changed=False,
                requires_review=False,
            ),
        ]
        weighted = weighted_average_increase(lines)
        naive_mean = (Decimal("0.40") + Decimal("0.03")) / 2
        self.assertLess(weighted, naive_mean)
        self.assertAlmostEqual(float(weighted), 0.0301, places=3)

    def test_summarize_counts_categories_correctly(self):
        lines = [
            PriceReviewLineForSummary("price_increase", Decimal("0.05"), Decimal(100), Decimal(10), False, False),
            PriceReviewLineForSummary("price_decrease", Decimal("-0.02"), Decimal(-50), Decimal(10), False, False),
            PriceReviewLineForSummary("no_change", Decimal(0), Decimal(0), Decimal(10), False, False),
            PriceReviewLineForSummary("new_product", None, None, None, False, False),
            PriceReviewLineForSummary("discontinued", None, None, None, False, False),
            PriceReviewLineForSummary("review_required", None, None, None, False, True),
        ]
        summary = summarize(lines, total_previous_skus=5, total_new_skus=5)
        self.assertEqual(summary.increasing_skus, 1)
        self.assertEqual(summary.decreasing_skus, 1)
        self.assertEqual(summary.unchanged_skus, 1)
        self.assertEqual(summary.new_skus, 1)
        self.assertEqual(summary.discontinued_skus, 1)
        self.assertEqual(summary.products_requiring_manual_review, 1)


if __name__ == "__main__":
    unittest.main()


class TestDetermineComparisonBasis(unittest.TestCase):
    """Compliance finding 1 (docs/compliance-review-2026-08.md): a line where normalization
    succeeded on one side and failed on the other used to silently compare incompatible units."""

    def test_both_normalized_same_unit_is_normalized(self):
        from app.analytics.price_review_calculations import determine_comparison_basis
        self.assertEqual(
            determine_comparison_basis(Decimal(30), Decimal(33), "L", "L"), "normalized"
        )

    def test_both_none_is_raw(self):
        from app.analytics.price_review_calculations import determine_comparison_basis
        self.assertEqual(determine_comparison_basis(None, None, None, None), "raw")

    def test_one_side_normalized_other_not_is_unit_mismatch(self):
        # The exact bug this finding is about: old normalized, new fell back to raw (or vice versa).
        from app.analytics.price_review_calculations import determine_comparison_basis
        self.assertEqual(
            determine_comparison_basis(Decimal(30), None, "L", None), "unit_mismatch"
        )
        self.assertEqual(
            determine_comparison_basis(None, Decimal(45), None, "kg"), "unit_mismatch"
        )

    def test_both_normalized_different_units_is_unit_mismatch(self):
        # The second case found while implementing the fix: both "succeeded" but to genuinely
        # different measurement types (volume vs mass) - just as wrong as one side failing.
        from app.analytics.price_review_calculations import determine_comparison_basis
        self.assertEqual(
            determine_comparison_basis(Decimal(30), Decimal(45), "L", "kg"), "unit_mismatch"
        )
