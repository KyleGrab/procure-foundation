"""Covers expected/leakage/tier-progress calculations, the 85%-within-30-days threshold alert
rule, period-close timing, status classification, and transaction aggregation (Phase 4a + 4b)."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.analytics.rebate_calculations import (
    RebateBand,
    RebateStatus,
    RebateType,
    aggregate_transactions_for_period,
    calculate_aggregate_rebate_leakage,
    calculate_expected_rebate,
    calculate_progress_to_next_tier,
    calculate_rebate_leakage,
    classify_rebate_status,
    is_period_due_for_close,
    is_threshold_alert_due,
)


class TestExpectedRebate(unittest.TestCase):
    def test_flat_percentage(self):
        result = calculate_expected_rebate(
            Decimal(1000000), RebateType.FIXED_PERCENTAGE, flat_rate_pct=Decimal("0.03")
        )
        self.assertEqual(result, Decimal("30000.0000"))

    def test_flat_percentage_without_rate_raises(self):
        with self.assertRaises(ValueError):
            calculate_expected_rebate(Decimal(1000000), RebateType.FIXED_PERCENTAGE)

    def test_tiered_applies_highest_reached_band(self):
        bands = [
            RebateBand(Decimal(0), Decimal("0.01")),
            RebateBand(Decimal(1000000), Decimal("0.025")),
            RebateBand(Decimal(5000000), Decimal("0.04")),
        ]
        result = calculate_expected_rebate(
            Decimal(2500000), RebateType.TIERED, bands=bands
        )
        self.assertEqual(result, Decimal("62500.0000"))  # 2.5% band, not 1% or 4%

    def test_tiered_below_first_threshold_returns_zero_not_error(self):
        bands = [RebateBand(Decimal(1000000), Decimal("0.02"))]
        result = calculate_expected_rebate(Decimal(500000), RebateType.TIERED, bands=bands)
        self.assertEqual(result, Decimal("0.0000"))

    def test_fixed_amount(self):
        result = calculate_expected_rebate(
            Decimal(999999), RebateType.FIXED_AMOUNT, fixed_amount=Decimal(50000)
        )
        self.assertEqual(result, Decimal("50000.0000"))


class TestProgressToNextTier(unittest.TestCase):
    def setUp(self):
        self.bands = [
            RebateBand(Decimal(0), Decimal("0.01")),
            RebateBand(Decimal(1000000), Decimal("0.025")),
            RebateBand(Decimal(5000000), Decimal("0.04")),
        ]

    def test_progress_toward_middle_tier(self):
        next_threshold, remaining = calculate_progress_to_next_tier(Decimal(800000), self.bands)
        self.assertEqual(next_threshold, Decimal(1000000))
        self.assertEqual(remaining, Decimal("200000.0000"))

    def test_no_higher_tier_at_top_band(self):
        next_threshold, remaining = calculate_progress_to_next_tier(Decimal(6000000), self.bands)
        self.assertIsNone(next_threshold)
        self.assertIsNone(remaining)

    def test_empty_bands_rejected(self):
        with self.assertRaises(ValueError):
            calculate_progress_to_next_tier(Decimal(100), [])


class TestRebateLeakage(unittest.TestCase):
    def test_leakage_when_nothing_received(self):
        # Nothing received yet - the full expected amount is at-risk, never assumed collected.
        leakage = calculate_rebate_leakage(Decimal(50000), None)
        self.assertEqual(leakage, Decimal("50000.0000"))

    def test_leakage_when_partially_received(self):
        leakage = calculate_rebate_leakage(Decimal(50000), Decimal(38000))
        self.assertEqual(leakage, Decimal("12000.0000"))

    def test_no_leakage_when_fully_received(self):
        leakage = calculate_rebate_leakage(Decimal(50000), Decimal(50000))
        self.assertEqual(leakage, Decimal("0.0000"))

    def test_function_is_already_direction_agnostic_supplier_and_customer_use_the_same_call(self):
        # Phase 2 (sell-side trade spend widening): calculate_rebate_leakage/
        # calculate_aggregate_rebate_leakage take generic (expected, received) Decimal pairs -
        # they never had a supplier/customer concept baked into the signature or the math, so
        # they need zero code changes to work for both directions. This test locks that in
        # explicitly rather than leaving it an unstated assumption: a supplier buy-side agreement
        # (expected rebate income, what's actually been received) and a customer sell-side
        # agreement (expected trade spend payable, what's actually been paid out) are the exact
        # same call shape, same function, same formula - only what the caller labels the two
        # numbers differs, and that label lives on RebateAgreement, not in this pure function.
        supplier_leakage = calculate_rebate_leakage(Decimal("976235.71"), Decimal(900000))
        customer_leakage = calculate_rebate_leakage(Decimal("3145913.07"), Decimal(2900000))
        self.assertEqual(supplier_leakage, Decimal("76235.7100"))
        self.assertEqual(customer_leakage, Decimal("245913.0700"))

    def test_aggregate_leakage_mixing_supplier_and_customer_period_pairs_sums_correctly(self):
        # A portfolio-wide leakage figure spanning BOTH directions in one call - real once
        # RebateAgreement supports both; calculate_aggregate_rebate_leakage already just sums
        # whatever (expected, received) pairs it's given, regardless of which side they came from.
        mixed_periods = [
            (Decimal("976235.71"), Decimal(900000)),   # supplier, buy-side
            (Decimal("3145913.07"), Decimal(2900000)),  # customer, sell-side
        ]
        total = calculate_aggregate_rebate_leakage(mixed_periods)
        self.assertEqual(total, Decimal("322148.7800"))  # 76235.71 + 245913.07


class TestThresholdAlert(unittest.TestCase):
    """The confirmed product rule: 85% of the next tier AND within 30 days of period close -
    both conditions, not either alone."""

    def setUp(self):
        self.bands = [RebateBand(Decimal(1000000), Decimal("0.025"))]
        self.period_end = date(2026, 12, 31)

    def test_fires_when_both_conditions_met(self):
        # 85% of R1,000,000 = R850,000. Spend at exactly that, 20 days before close.
        due = is_threshold_alert_due(
            Decimal(850000), self.bands, date(2026, 12, 11), self.period_end
        )
        self.assertTrue(due)

    def test_does_not_fire_when_spend_high_but_far_from_period_close(self):
        # 90% of the way there, but 200 days before close - not yet urgent.
        due = is_threshold_alert_due(
            Decimal(900000), self.bands, date(2026, 6, 1), self.period_end
        )
        self.assertFalse(due)

    def test_does_not_fire_when_close_to_period_end_but_spend_too_low(self):
        due = is_threshold_alert_due(
            Decimal(400000), self.bands, date(2026, 12, 15), self.period_end
        )
        self.assertFalse(due)

    def test_does_not_fire_after_period_has_already_closed(self):
        due = is_threshold_alert_due(
            Decimal(900000), self.bands, date(2027, 1, 5), self.period_end
        )
        self.assertFalse(due)

    def test_does_not_fire_when_already_at_top_tier(self):
        due = is_threshold_alert_due(
            Decimal(5000000), self.bands, date(2026, 12, 20), self.period_end
        )
        self.assertFalse(due)


class TestPeriodClose(unittest.TestCase):
    def test_not_due_before_period_end(self):
        self.assertFalse(is_period_due_for_close(date(2026, 12, 31), date(2026, 12, 1)))

    def test_due_on_period_end(self):
        self.assertTrue(is_period_due_for_close(date(2026, 12, 31), date(2026, 12, 31)))

    def test_due_after_period_end(self):
        self.assertTrue(is_period_due_for_close(date(2026, 12, 31), date(2027, 1, 15)))


class TestRebateStatusClassification(unittest.TestCase):
    def test_reconciled_when_received_matches_expected(self):
        status = classify_rebate_status(
            Decimal(50000), Decimal(50000), period_closed=True, threshold_alert_due=False
        )
        self.assertEqual(status, RebateStatus.RECONCILED)

    def test_leakage_detected_when_received_short(self):
        status = classify_rebate_status(
            Decimal(50000), Decimal(40000), period_closed=True, threshold_alert_due=False
        )
        self.assertEqual(status, RebateStatus.LEAKAGE_DETECTED)

    def test_awaiting_payment_when_closed_but_nothing_received(self):
        status = classify_rebate_status(
            Decimal(50000), None, period_closed=True, threshold_alert_due=False
        )
        self.assertEqual(status, RebateStatus.PERIOD_CLOSED_AWAITING_PAYMENT)

    def test_threshold_approaching_when_open_and_alert_due(self):
        status = classify_rebate_status(
            Decimal(50000), None, period_closed=False, threshold_alert_due=True
        )
        self.assertEqual(status, RebateStatus.THRESHOLD_APPROACHING)

    def test_on_track_otherwise(self):
        status = classify_rebate_status(
            Decimal(50000), None, period_closed=False, threshold_alert_due=False
        )
        self.assertEqual(status, RebateStatus.ON_TRACK)


class TestTransactionAggregation(unittest.TestCase):
    def test_sums_only_transactions_within_period(self):
        transactions = [
            (Decimal(10000), Decimal(50), date(2026, 1, 15)),   # in period
            (Decimal(15000), Decimal(75), date(2026, 3, 20)),   # in period
            (Decimal(99999), Decimal(1), date(2025, 12, 31)),   # before period - excluded
            (Decimal(88888), Decimal(1), date(2026, 4, 1)),     # after period - excluded
        ]
        result = aggregate_transactions_for_period(
            transactions, date(2026, 1, 1), date(2026, 3, 31)
        )
        self.assertEqual(result.total_spend, Decimal("25000.0000"))
        self.assertEqual(result.total_volume, Decimal(125))
        self.assertEqual(result.transaction_count, 2)

    def test_boundary_dates_are_inclusive(self):
        transactions = [
            (Decimal(100), Decimal(1), date(2026, 1, 1)),    # exactly period_start
            (Decimal(200), Decimal(2), date(2026, 3, 31)),   # exactly period_end
        ]
        result = aggregate_transactions_for_period(
            transactions, date(2026, 1, 1), date(2026, 3, 31)
        )
        self.assertEqual(result.transaction_count, 2)

    def test_empty_transaction_list_returns_zeroes(self):
        result = aggregate_transactions_for_period([], date(2026, 1, 1), date(2026, 3, 31))
        self.assertEqual(result.total_spend, Decimal("0.0000"))
        self.assertEqual(result.transaction_count, 0)


if __name__ == "__main__":
    unittest.main()
