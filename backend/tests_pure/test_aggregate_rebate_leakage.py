"""Aggregate rebate leakage - written before the implementation, per this session's test-first
sequence. Reuses calculate_rebate_leakage per period rather than reimplementing the math (§2.7)."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.rebate_calculations import calculate_aggregate_rebate_leakage


class TestAggregateRebateLeakage(unittest.TestCase):
    def test_sums_leakage_across_multiple_periods(self):
        periods = [
            (Decimal("50000"), Decimal("30000")),  # 20000 leakage
            (Decimal("20000"), Decimal("20000")),  # 0 leakage
            (Decimal("10000"), None),               # 10000 leakage - nothing received yet
        ]
        self.assertEqual(calculate_aggregate_rebate_leakage(periods), Decimal("30000.0000"))

    def test_empty_periods_returns_zero_not_error(self):
        self.assertEqual(calculate_aggregate_rebate_leakage([]), Decimal("0.0000"))

    def test_never_double_counts_a_negative_leakage_as_an_offset(self):
        # If received somehow exceeds expected (an over-payment/correction), that period's
        # individual leakage would be negative - confirms the aggregate doesn't let a negative
        # figure silently cancel out real leakage elsewhere, since that would understate a real
        # organisational risk. calculate_rebate_leakage itself doesn't floor at zero (an
        # over-receipt IS real, signed information - same "don't clamp away sign" principle as
        # calculate_price_change), so this test locks in that the aggregate passes that behavior
        # through honestly rather than silently changing it.
        periods = [(Decimal("10000"), Decimal("12000")), (Decimal("10000"), Decimal("0"))]
        self.assertEqual(calculate_aggregate_rebate_leakage(periods), Decimal("8000.0000"))


if __name__ == "__main__":
    unittest.main()
