"""
Tests for app.analytics.treasury_engine - multi-currency FX exposure.

[DEMO] throughout: models a $100,000 USD bulk wheat import against a baseline ZAR/USD spot of
18.00, later devalued 10% to 19.80, with a [DEMO] FEC locked at 18.20 - no real FX transaction,
spot rate, or forward contract has ever been provided anywhere in this engagement. All figures
independently verified before being written into any assertion: unhedged unrealized variance =
R180,000.00 (adverse - ZAR weakened, so the USD liability costs more in ZAR), hedged gain via
the FEC = R160,000.00 (the FEC saved this much relative to what unhedged spot exposure would
have cost). Both computed and cross-checked in a separate shell before this file was written.

Late-rounding discipline applied deliberately, learned directly from a real bug two turns ago in
this same engagement (calculate_segregated_route_cost originally rounded an intermediate rate
before multiplying and leaked currency out of conservation) - the rate DIFFERENCE here is never
rounded before being multiplied by the transaction amount; only the final Rand result is rounded.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.treasury_engine import calculate_fx_transaction_exposure

DEMO_USD_AMOUNT = Decimal("100000")
DEMO_SPOT_ORIGINAL = Decimal("18.00")
DEMO_SPOT_DEVALUED = Decimal("19.80")
DEMO_FEC_RATE = Decimal("18.20")


class TestCalculateFxTransactionExposure(unittest.TestCase):
    def test_missing_transaction_date_spot_rate_is_a_type_error_not_a_fabricated_benchmark(self):
        with self.assertRaises(TypeError):
            calculate_fx_transaction_exposure(
                foreign_currency_amount=DEMO_USD_AMOUNT, reporting_date_spot_rate=DEMO_SPOT_DEVALUED,
            )

    def test_zero_transaction_date_spot_rate_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_fx_transaction_exposure(
                foreign_currency_amount=DEMO_USD_AMOUNT, transaction_date_spot_rate=Decimal("0"),
                reporting_date_spot_rate=DEMO_SPOT_DEVALUED,
            )

    def test_negative_spot_rate_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_fx_transaction_exposure(
                foreign_currency_amount=DEMO_USD_AMOUNT, transaction_date_spot_rate=Decimal("-18"),
                reporting_date_spot_rate=DEMO_SPOT_DEVALUED,
            )

    def test_demo_10pct_devaluation_produces_the_real_verified_unrealized_variance(self):
        result = calculate_fx_transaction_exposure(
            foreign_currency_amount=DEMO_USD_AMOUNT, transaction_date_spot_rate=DEMO_SPOT_ORIGINAL,
            reporting_date_spot_rate=DEMO_SPOT_DEVALUED,
        )
        self.assertEqual(result["unrealized_variance"], Decimal("180000.0000"))
        self.assertTrue(result["is_hedged"] is False)
        self.assertIsNone(result["hedging_gain_loss"])

    def test_fec_rate_present_computes_hedging_gain_not_unrealized_variance(self):
        # The core structural guard: when fec_contract_rate is provided, unrealized_variance
        # must be None, not a second, conflicting number for the same transaction - the FEC
        # neutralizes spot exposure, so only ONE risk figure is ever produced per transaction.
        result = calculate_fx_transaction_exposure(
            foreign_currency_amount=DEMO_USD_AMOUNT, transaction_date_spot_rate=DEMO_SPOT_ORIGINAL,
            reporting_date_spot_rate=DEMO_SPOT_DEVALUED, fec_contract_rate=DEMO_FEC_RATE,
        )
        self.assertEqual(result["hedging_gain_loss"], Decimal("160000.0000"))
        self.assertTrue(result["is_hedged"] is True)
        self.assertIsNone(result["unrealized_variance"])

    def test_late_rounding_full_precision_matches_the_independently_verified_figure_to_the_cent(self):
        # Directly proves the late-rounding claim rather than asserting it - a rate difference
        # that does NOT divide evenly would reveal early-rounding leakage immediately if present.
        result = calculate_fx_transaction_exposure(
            foreign_currency_amount=Decimal("33333.33"), transaction_date_spot_rate=Decimal("17.8347"),
            reporting_date_spot_rate=Decimal("18.9123"), fec_contract_rate=Decimal("18.0501"),
        )
        expected = (Decimal("18.9123") - Decimal("18.0501")) * Decimal("33333.33")
        self.assertEqual(result["hedging_gain_loss"], expected.quantize(Decimal("0.0001")))

    def test_result_has_no_field_that_could_be_mistaken_for_a_realized_operational_figure(self):
        # Same structural isolation pattern as calculate_future_replacement_exposure - a
        # treasury holding variance must never be mistaken for realized COGS, net margin, or a
        # product-level MAC total once this reaches a dashboard or ledger.
        result = calculate_fx_transaction_exposure(
            foreign_currency_amount=DEMO_USD_AMOUNT, transaction_date_spot_rate=DEMO_SPOT_ORIGINAL,
            reporting_date_spot_rate=DEMO_SPOT_DEVALUED,
        )
        forbidden_keys = {"cogs", "net_margin", "inventory_value", "mac_control_total", "dio", "dpo", "ccc"}
        self.assertEqual(set(result.keys()) & forbidden_keys, set())

    def test_zero_fec_rate_is_refused_same_as_a_zero_spot_rate(self):
        # An FEC rate, once provided, must be held to the identical no-fabricated-zero standard
        # as the mandatory spot rate - not a looser rule just because it's optional.
        with self.assertRaises(ValueError):
            calculate_fx_transaction_exposure(
                foreign_currency_amount=DEMO_USD_AMOUNT, transaction_date_spot_rate=DEMO_SPOT_ORIGINAL,
                reporting_date_spot_rate=DEMO_SPOT_DEVALUED, fec_contract_rate=Decimal("0"),
            )


if __name__ == "__main__":
    unittest.main()
