"""
Tests for app.analytics.revenue_waterfall - Gate A revenue layer (management-accounting control
philosophy: Net Net Margin must not compute until every line in this waterfall is source-complete).

Two lines are grounded in real, fresh-pulled TTM figures ending August 2026 (Gourmet Cape
Distributors' real Income Statement): settlement_discounts maps to the real "Less: Discount
allowed" line (R8,240,399.16), volume_growth_rebates maps to the real "Less: Rebates Paid" line
(R3,145,913.07). The real waterfall reconciles exactly: TTM Turnover R364,588,837.16 minus both
of those equals TTM Net Sales R353,202,524.93, confirmed by direct subtraction against the real
Income Statement before this file was written, not assumed.

The remaining four lines (credit_notes_issued, operational_claims_returns,
retro_pricing_adjustment, supplier_recoveries_allowances) have no real P&L figures anywhere in
this engagement - the real Credit Notes file has genuine reason codes but no Rand value column at
all (confirmed by opening it). Those four are explicitly [DEMO] wherever used below.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.revenue_waterfall import GrossToNetWaterfallInput, calculate_gross_to_net_waterfall


class TestGrossToNetWaterfall(unittest.TestCase):
    def test_real_gourmet_turnover_and_two_real_deduction_lines_reconcile_to_real_net_sales(self):
        # The two real lines, zero for the four lines with no real P&L equivalent - this isolates
        # exactly the real, verified subtraction (Turnover - Discount allowed - Rebates Paid).
        result = calculate_gross_to_net_waterfall(GrossToNetWaterfallInput(
            gross_sales=Decimal("364588837.16"),
            settlement_discounts=Decimal("8240399.16"),       # real: "Less: Discount allowed" TTM
            volume_growth_rebates=Decimal("3145913.07"),      # real: "Less: Rebates Paid" TTM
            credit_notes_issued=Decimal("0"), operational_claims_returns=Decimal("0"),
            retro_pricing_adjustment=Decimal("0"), supplier_recoveries_allowances=Decimal("0"),
        ))
        self.assertTrue(result["is_complete"])
        self.assertEqual(result["net_revenue"], Decimal("353202524.9300"))  # real TTM Net Sales, exact match

    def test_demo_full_seven_line_waterfall_with_all_lines_populated(self):
        # [DEMO] - the four non-real lines get illustrative figures here to exercise the full
        # chain shape; never presented as real deductions this business has actually recorded.
        result = calculate_gross_to_net_waterfall(GrossToNetWaterfallInput(
            gross_sales=Decimal("100000"),
            settlement_discounts=Decimal("2000"), volume_growth_rebates=Decimal("3000"),
            credit_notes_issued=Decimal("1500"), operational_claims_returns=Decimal("800"),
            retro_pricing_adjustment=Decimal("-200"),  # a downward retro-price correction
            supplier_recoveries_allowances=Decimal("600"),
        ))
        # 100000 - 2000 - 3000 - 1500 - 800 - 200 + 600 = 93100
        self.assertEqual(result["net_revenue"], Decimal("93100.0000"))

    def test_retro_pricing_can_be_positive_and_increases_net_revenue(self):
        # [DEMO]. An upward retro-price correction (a late price increase applied retroactively)
        # is a real, legitimate signed direction the field must support - not deduction-only.
        result = calculate_gross_to_net_waterfall(GrossToNetWaterfallInput(
            gross_sales=Decimal("100000"),
            settlement_discounts=Decimal("0"), volume_growth_rebates=Decimal("0"),
            credit_notes_issued=Decimal("0"), operational_claims_returns=Decimal("0"),
            retro_pricing_adjustment=Decimal("500"), supplier_recoveries_allowances=Decimal("0"),
        ))
        self.assertEqual(result["net_revenue"], Decimal("100500.0000"))

    def test_missing_single_line_marks_incomplete_and_refuses_a_fabricated_zero(self):
        # The core Gate A rule for this section: a None line is NOT treated as zero. is_complete
        # is False and net_revenue is None - a caller must not proceed to CTS/Net Net Margin.
        result = calculate_gross_to_net_waterfall(GrossToNetWaterfallInput(
            gross_sales=Decimal("100000"),
            settlement_discounts=Decimal("2000"), volume_growth_rebates=None,
            credit_notes_issued=Decimal("0"), operational_claims_returns=Decimal("0"),
            retro_pricing_adjustment=Decimal("0"), supplier_recoveries_allowances=Decimal("0"),
        ))
        self.assertFalse(result["is_complete"])
        self.assertIsNone(result["net_revenue"])
        self.assertEqual(result["missing_lines"], ["volume_growth_rebates"])

    def test_multiple_missing_lines_are_all_reported_together_not_just_the_first(self):
        result = calculate_gross_to_net_waterfall(GrossToNetWaterfallInput(
            gross_sales=Decimal("100000"),
            settlement_discounts=None, volume_growth_rebates=None,
            credit_notes_issued=Decimal("0"), operational_claims_returns=None,
            retro_pricing_adjustment=Decimal("0"), supplier_recoveries_allowances=Decimal("0"),
        ))
        self.assertFalse(result["is_complete"])
        self.assertEqual(
            set(result["missing_lines"]), {"settlement_discounts", "volume_growth_rebates", "operational_claims_returns"},
        )

    def test_gross_sales_itself_is_never_optional_type_enforced_at_the_dataclass_level(self):
        # gross_sales has no default and is not Decimal | None in the dataclass - this is
        # enforced structurally, not by a runtime check, so this test documents the guarantee
        # rather than exercising a branch: omitting it is a TypeError at construction time.
        with self.assertRaises(TypeError):
            GrossToNetWaterfallInput(
                settlement_discounts=Decimal("0"), volume_growth_rebates=Decimal("0"),
                credit_notes_issued=Decimal("0"), operational_claims_returns=Decimal("0"),
                retro_pricing_adjustment=Decimal("0"), supplier_recoveries_allowances=Decimal("0"),
            )


if __name__ == "__main__":
    unittest.main()
