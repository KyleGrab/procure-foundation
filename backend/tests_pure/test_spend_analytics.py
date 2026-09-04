"""Covers spend aggregation, ABC classification, Pareto contributors, and price consistency
detection (spec Section 23, distinct from Phase 4c's PPV)."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.analytics.spend_analytics import (
    ABCClass,
    PriceObservation,
    aggregate_spend,
    calculate_abc_classification,
    calculate_month_over_month_trend,
    calculate_pareto_contributors,
    calculate_price_consistency,
)


class TestAggregateSpend(unittest.TestCase):
    def test_sums_by_key_and_sorts_highest_first(self):
        rows = [
            ("SUP1", "Supplier A", Decimal(50000)),
            ("SUP2", "Supplier B", Decimal(200000)),
            ("SUP1", "Supplier A", Decimal(30000)),
        ]
        items = aggregate_spend(rows)
        self.assertEqual(items[0].key, "SUP2")
        self.assertEqual(items[0].amount, Decimal("200000.0000"))
        self.assertEqual(items[1].key, "SUP1")
        self.assertEqual(items[1].amount, Decimal("80000.0000"))


class TestABCClassification(unittest.TestCase):
    def test_classic_80_15_5_split(self):
        # Classic ABC example: a few big items make up 80% of spend.
        items = aggregate_spend([
            ("A", "Item A", Decimal(800000)),
            ("B", "Item B", Decimal(150000)),
            ("C", "Item C", Decimal(50000)),
        ])
        results = calculate_abc_classification(items)
        self.assertEqual(results[0].classification, ABCClass.A)  # 80% cumulative
        self.assertEqual(results[1].classification, ABCClass.B)  # 95% cumulative
        self.assertEqual(results[2].classification, ABCClass.C)  # 100% cumulative

    def test_zero_total_spend_returns_all_c_not_error(self):
        items = aggregate_spend([("A", "Item A", Decimal(0))])
        results = calculate_abc_classification(items)
        self.assertEqual(results[0].classification, ABCClass.C)

    def test_configurable_thresholds(self):
        # With the default a_threshold (0.80), item A's 60% cumulative is well inside the A band.
        # With a strict custom a_threshold (0.50), the same item's 60% cumulative now exceeds it,
        # demonstrating the parameter is actually applied, not just accepted and ignored.
        items = aggregate_spend([
            ("A", "Item A", Decimal(600000)),
            ("B", "Item B", Decimal(400000)),
        ])
        default_results = calculate_abc_classification(items)
        self.assertEqual(default_results[0].classification, ABCClass.A)

        strict_results = calculate_abc_classification(items, a_threshold_pct=Decimal("0.50"))
        self.assertEqual(strict_results[0].classification, ABCClass.B)  # 60% > 50% A-ceiling now


class TestParetoContributors(unittest.TestCase):
    def test_identifies_minimum_contributors_to_reach_target(self):
        items = aggregate_spend([
            ("A", "Item A", Decimal(500000)),
            ("B", "Item B", Decimal(300000)),
            ("C", "Item C", Decimal(100000)),
            ("D", "Item D", Decimal(100000)),
        ])
        result = calculate_pareto_contributors(items, target_pct=Decimal("0.80"))
        # A+B = 800000/1000000 = 80% - exactly two items needed.
        self.assertEqual(result.contributor_count, 2)
        self.assertEqual(result.total_item_count, 4)
        self.assertGreaterEqual(result.cumulative_pct_covered, Decimal("0.80"))

    def test_zero_spend_returns_no_contributors(self):
        items = aggregate_spend([("A", "Item A", Decimal(0))])
        result = calculate_pareto_contributors(items)
        self.assertEqual(result.contributor_count, 0)


class TestPriceConsistency(unittest.TestCase):
    def test_significant_variance_flagged(self):
        observations = [
            PriceObservation(Decimal(100), date(2026, 1, 5), "Store A"),
            PriceObservation(Decimal(115), date(2026, 2, 10), "Store B"),
        ]
        result = calculate_price_consistency(observations)
        self.assertEqual(result.spread, Decimal("15.0000"))
        self.assertEqual(result.spread_pct, Decimal("0.15"))
        self.assertTrue(result.is_significant)  # 15% > default 5% threshold

    def test_small_variance_not_flagged(self):
        observations = [
            PriceObservation(Decimal("100.00"), date(2026, 1, 5)),
            PriceObservation(Decimal("101.00"), date(2026, 2, 10)),
        ]
        result = calculate_price_consistency(observations)
        self.assertFalse(result.is_significant)  # 1% < default 5% threshold

    def test_configurable_significance_threshold(self):
        observations = [
            PriceObservation(Decimal(100), date(2026, 1, 5)),
            PriceObservation(Decimal(102), date(2026, 2, 10)),
        ]
        result = calculate_price_consistency(observations, significance_threshold_pct=Decimal("0.01"))
        self.assertTrue(result.is_significant)  # 2% > 1% custom threshold

    def test_empty_observations_rejected(self):
        with self.assertRaises(ValueError):
            calculate_price_consistency([])

    def test_single_observation_has_zero_spread(self):
        observations = [PriceObservation(Decimal(100), date(2026, 1, 5))]
        result = calculate_price_consistency(observations)
        self.assertEqual(result.spread, Decimal("0.0000"))
        self.assertFalse(result.is_significant)


class TestMonthOverMonthTrend(unittest.TestCase):
    def test_first_point_has_no_change_pct(self):
        points = calculate_month_over_month_trend([("2026-01", Decimal(100000))])
        self.assertIsNone(points[0].change_pct)

    def test_increase_and_decrease_calculated_correctly(self):
        points = calculate_month_over_month_trend([
            ("2026-01", Decimal(100000)),
            ("2026-02", Decimal(110000)),  # +10%
            ("2026-03", Decimal(99000)),   # -10% vs Feb
        ])
        self.assertEqual(points[1].change_pct, Decimal("0.10"))
        self.assertEqual(points[2].change_pct, Decimal("-0.10"))

    def test_zero_prior_month_gives_none_not_error(self):
        points = calculate_month_over_month_trend([
            ("2026-01", Decimal(0)), ("2026-02", Decimal(50000)),
        ])
        self.assertIsNone(points[1].change_pct)

    def test_empty_series_returns_empty_list(self):
        self.assertEqual(calculate_month_over_month_trend([]), [])


if __name__ == "__main__":
    unittest.main()
