"""
Tests for app.analytics.capital_investment - Phase 6, CIMA F-pillar. Pure Decimal logic, no DB.

[DEMO] throughout: models a R10,000,000 automated cold-storage facility upgrade (Year 0 outlay,
5 years of R2,800,000 net operational inflows) - no real capital project of this kind has been
proposed anywhere in this engagement; every figure is illustrative, chosen to be clean enough to
hand-verify, and independently computed via Python before being written into any assertion below
(IRR≈12.376%, NPV at that rate≈0 confirmed to 8 decimal places, discounted payback≈4.6467 years
at 10% WACC) - not guessed, not approximated.

IRR has a real mathematical hazard this module is built around, not despite: no closed-form
solution exists for multi-period cash flows, and Descartes' rule of signs means a cash flow
sequence with more than one sign change can have multiple mathematically valid IRRs. Returning
"a" root in that case would misrepresent which one is economically meaningful - calculate_irr
refuses (returns None) rather than guess.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.capital_investment import (
    apply_tax_shield_to_cash_flows,
    calculate_discounted_payback_period,
    calculate_irr,
    calculate_npv,
    evaluate_capital_investment,
    flag_speculative_residual_value,
)

DEMO_COLD_STORAGE_CASH_FLOWS = [
    Decimal(-10000000), Decimal(2800000), Decimal(2800000),
    Decimal(2800000), Decimal(2800000), Decimal(2800000),
]


class TestCalculateNpv(unittest.TestCase):
    def test_real_computed_npv_at_12_pct_wacc(self):
        # Independently verified: 93,373.3665660141607663473552686380674718867138693
        npv = calculate_npv(discount_rate=Decimal("0.12"), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)
        self.assertAlmostEqual(float(npv), 93373.37, places=1)

    def test_npv_at_8_pct_wacc_is_larger_since_lower_discount_rate_discounts_less(self):
        npv_12pct = calculate_npv(discount_rate=Decimal("0.12"), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)
        npv_8pct = calculate_npv(discount_rate=Decimal("0.08"), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)
        self.assertGreater(npv_8pct, npv_12pct)

    def test_missing_discount_rate_is_a_type_error_not_a_fabricated_zero_or_10pct_benchmark(self):
        # The explicit Phase 6 rule: WACC has no default, anywhere, ever.
        with self.assertRaises(TypeError):
            calculate_npv(cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)

    def test_zero_discount_rate_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_npv(discount_rate=Decimal(0), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)

    def test_negative_discount_rate_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_npv(discount_rate=Decimal("-0.05"), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)


class TestCalculateIrr(unittest.TestCase):
    def test_real_computed_irr_for_the_demo_cold_storage_project(self):
        irr = calculate_irr(DEMO_COLD_STORAGE_CASH_FLOWS)
        self.assertAlmostEqual(float(irr), 0.12376, places=4)

    def test_mathematical_symmetry_npv_at_the_computed_irr_is_zero(self):
        # The exact forensic requirement: an investment scenario yielding 0% NPV must correctly
        # match the IRR output - proven by feeding IRR's own output back into calculate_npv.
        #
        # Tolerance is RELATIVE to the investment's scale, not an absolute Rand amount, and that's
        # a deliberate, understood choice, not a loosened test: calculate_irr's returned rate is
        # rounded to 6 decimal places (round_rate) before being handed back, since reporting a
        # rate to 50 decimal places would be absurd. That rounding, compounded over R10,000,000
        # and 5 periods, produces a real, expected ~R10.21 NPV residual when the ROUNDED rate is
        # fed back in - confirmed directly: the raw, unrounded bisection result gives an NPV
        # residual of -8.19e-8, essentially exact. R10.21 against a R10,000,000 outlay is
        # 0.0001% - genuinely negligible at the scale of the investment, not a symmetry failure.
        irr = calculate_irr(DEMO_COLD_STORAGE_CASH_FLOWS)
        npv_at_irr = calculate_npv(discount_rate=irr, cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)
        initial_outlay = abs(DEMO_COLD_STORAGE_CASH_FLOWS[0])
        relative_residual = abs(npv_at_irr) / initial_outlay
        self.assertLess(relative_residual, Decimal("0.00001"))  # < 0.001% of the initial outlay

    def test_irregular_cash_flow_with_multiple_sign_changes_refuses_not_a_misleading_root(self):
        # [DEMO]: -1000, +3000, -2500 - two sign changes (Descartes' rule allows up to 2 real
        # roots here). Returning "a" root would misrepresent which is economically meaningful.
        irregular = [Decimal(-1000), Decimal(3000), Decimal(-2500)]
        self.assertIsNone(calculate_irr(irregular))

    def test_all_positive_cash_flows_have_no_real_irr_and_return_none(self):
        # No outlay at all - NPV never crosses zero for any rate, since there's nothing to
        # discount against. Not an error, not a fabricated 0% - None.
        all_positive = [Decimal(1000), Decimal(500), Decimal(500)]
        self.assertIsNone(calculate_irr(all_positive))

    def test_all_negative_cash_flows_have_no_real_irr_and_return_none(self):
        all_negative = [Decimal(-1000), Decimal(-500)]
        self.assertIsNone(calculate_irr(all_negative))


class TestCalculateDiscountedPaybackPeriod(unittest.TestCase):
    def test_real_computed_payback_at_10_pct_wacc(self):
        # Independently verified: 4.6467214285714285714285714285714285714285714285715
        payback = calculate_discounted_payback_period(
            discount_rate=Decimal("0.10"), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS,
        )
        self.assertAlmostEqual(float(payback), 4.6467, places=3)

    def test_project_that_never_recovers_its_outlay_returns_none_not_a_fabricated_period(self):
        # [DEMO]: a R10,000,000 outlay with inflows too small to ever recover it within the
        # given horizon - None, not a misleadingly large or absent number.
        never_recovers = [Decimal(-10000000), Decimal(500000), Decimal(500000)]
        payback = calculate_discounted_payback_period(discount_rate=Decimal("0.10"), cash_flows=never_recovers)
        self.assertIsNone(payback)

    def test_missing_discount_rate_is_a_type_error(self):
        with self.assertRaises(TypeError):
            calculate_discounted_payback_period(cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS)


class TestApplyTaxShieldToCashFlows(unittest.TestCase):
    def test_demo_tax_shield_increases_each_periods_net_cash_flow(self):
        # [DEMO]: R2,000,000/year wear-and-tear allowance, 28% tax rate -> R560,000/year real
        # cash benefit from reduced tax payable, added to the operational cash flow.
        operational = [Decimal(2800000)] * 5
        allowances = [Decimal(2000000)] * 5
        shielded = apply_tax_shield_to_cash_flows(
            net_operational_cash_flows=operational, capital_allowance_schedule=allowances,
            tax_rate=Decimal("0.28"),
        )
        self.assertEqual(shielded[0], Decimal("3360000.0000"))  # 2800000 + (2000000*0.28)

    def test_mismatched_schedule_lengths_are_refused_not_silently_truncated_or_padded(self):
        with self.assertRaises(ValueError):
            apply_tax_shield_to_cash_flows(
                net_operational_cash_flows=[Decimal(2800000)] * 5,
                capital_allowance_schedule=[Decimal(2000000)] * 3,  # deliberately mismatched
                tax_rate=Decimal("0.28"),
            )


class TestFlagSpeculativeResidualValue(unittest.TestCase):
    def test_demo_residual_at_exactly_20_pct_is_flagged_inclusive_boundary(self):
        # Inclusive boundary - same conservative posture as classify_expiry_risk/
        # classify_aging_buckets elsewhere in this codebase.
        result = flag_speculative_residual_value(
            residual_value=Decimal(2000000), initial_capital_outlay=Decimal(10000000),
        )
        self.assertTrue(result["is_speculative"])
        self.assertIsNotNone(result["warning"])

    def test_demo_residual_below_20_pct_is_not_flagged(self):
        result = flag_speculative_residual_value(
            residual_value=Decimal(1500000), initial_capital_outlay=Decimal(10000000),
        )
        self.assertFalse(result["is_speculative"])
        self.assertIsNone(result["warning"])

    def test_zero_initial_outlay_does_not_crash_returns_not_speculative(self):
        result = flag_speculative_residual_value(residual_value=Decimal(100), initial_capital_outlay=Decimal(0))
        self.assertFalse(result["is_speculative"])


class TestCapitalInvestmentStructuralIsolation(unittest.TestCase):
    def test_evaluation_result_has_no_field_that_could_be_mistaken_for_a_realized_operational_figure(self):
        # Chaos-audit-style structural guardrail, same pattern as
        # calculate_future_replacement_exposure's forbidden-keys check: a future capital
        # project's NPV/IRR must never be mistaken for realized COGS, inventory valuation, or
        # current operational MAC totals - checked directly on the result shape, not just
        # documented against.
        result = evaluate_capital_investment(
            discount_rate=Decimal("0.12"), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS,
            residual_value=Decimal(1000000),
        )
        forbidden_keys = {"cogs", "cost_of_goods_sold", "inventory_value", "net_margin", "dio", "dpo", "ccc", "mac_control_total"}
        self.assertEqual(set(result.keys()) & forbidden_keys, set())

    def test_evaluation_result_bundles_npv_irr_payback_and_residual_flag_together(self):
        result = evaluate_capital_investment(
            discount_rate=Decimal("0.12"), cash_flows=DEMO_COLD_STORAGE_CASH_FLOWS,
            residual_value=Decimal(1000000),
        )
        self.assertIn("npv", result)
        self.assertIn("irr", result)
        self.assertIn("discounted_payback_period", result)
        self.assertIn("residual_value_flag", result)


if __name__ == "__main__":
    unittest.main()
