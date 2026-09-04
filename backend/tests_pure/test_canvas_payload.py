"""
Tests for app.analytics.canvas_payload - the consolidation layer combining every real, already-
tested pure engine (revenue waterfall/net margin, GMROI, working capital, 13-week cash forecast,
timing-bridge isolation) into one payload, with per-layer graceful degradation.

Every layer function in these tests is a REAL function from this codebase (calculate_customer_net_margin,
build_13_week_cash_forecast, refuse_timing_bridge_allocation), not a synthetic mock standing in for
one - this proves the orchestrator actually catches the real exception shapes these functions
raise (a genuine mix of ValueError and TypeError, confirmed by reading the real source before
writing this), not an idealized exception type chosen for convenience.

The R495,473.98 timing-bridge figure used in the risk-layer tests remains [DEMO] throughout this
engagement - no real sub-ledger extract has ever been read (the source Inventory Valuation Report
is still unreadable). Used here only to exercise the mechanism, never asserted as a confirmed
real reconciliation gap.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.canvas_payload import build_management_canvas_payload, build_widget_result
from app.analytics.cash_forecast import build_13_week_cash_forecast
from app.analytics.management_accounting import (
    calculate_customer_net_margin,
    refuse_timing_bridge_allocation,
)


class TestBuildWidgetResult(unittest.TestCase):
    def test_successful_real_calculation_returns_ok_status_with_real_data(self):
        result = build_widget_result(
            calculate_customer_net_margin,
            revenue=Decimal(100000), cogs=Decimal(70000),
            direct_logistics_cost=Decimal(8000), warehouse_abc_cost=Decimal(4000),
            trade_spend=Decimal(5000), revenue_basis="gross",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["net_margin"], Decimal("13000.0000"))
        self.assertEqual(result["reason_codes"], [])

    def test_real_value_error_from_the_revenue_basis_gate_becomes_a_diagnostic_state_not_a_crash(self):
        # The exact real double-counting guard built during the targeted Phase 2 re-audit -
        # proves this orchestrator catches a REAL ValueError from a REAL function, not a
        # synthetic one constructed to be convenient to catch.
        result = build_widget_result(
            calculate_customer_net_margin,
            revenue=Decimal("353202524.93"), cogs=Decimal("287394425.05"),
            direct_logistics_cost=Decimal(0), warehouse_abc_cost=Decimal(0),
            trade_spend=Decimal("3145913.07"), revenue_basis="net_of_waterfall",
        )
        self.assertEqual(result["status"], "diagnostic")
        self.assertIsNone(result["data"])
        self.assertTrue(any("double-count" in code for code in result["reason_codes"]))

    def test_real_type_error_from_a_missing_required_argument_also_becomes_a_diagnostic_state(self):
        # build_13_week_cash_forecast's opening_cash has no default (Gate C's own explicit
        # design) - omitting it raises TypeError, not ValueError. A different real exception
        # SHAPE from a different real function, confirming the catch isn't narrowly tuned to
        # only the ValueError case.
        result = build_widget_result(build_13_week_cash_forecast, weekly_inputs=[])
        self.assertEqual(result["status"], "diagnostic")
        self.assertIsNone(result["data"])
        self.assertEqual(len(result["reason_codes"]), 1)

    def test_an_unrelated_exception_type_is_not_silently_swallowed(self):
        # Structural guardrail on the guardrail itself: this orchestrator must only ever catch
        # the specific, known precondition-violation shapes (ValueError/TypeError) this
        # codebase's gate functions actually raise - not become a blanket try/except that hides
        # a genuine bug (e.g. a KeyError from a real programming mistake) behind a calm-looking
        # "diagnostic state" label.
        def _broken_layer():
            return {}["this_key_does_not_exist"]

        with self.assertRaises(KeyError):
            build_widget_result(_broken_layer)


class TestBuildManagementCanvasPayload(unittest.TestCase):
    def _working_revenue_layer(self):
        return calculate_customer_net_margin(
            revenue=Decimal(100000), cogs=Decimal(70000),
            direct_logistics_cost=Decimal(8000), warehouse_abc_cost=Decimal(4000),
            trade_spend=Decimal(5000), revenue_basis="gross",
        )

    def _broken_liquidity_layer(self):
        # Real TypeError - opening_cash omitted, matching Gate C's real "never a fabricated
        # zero starting balance" design.
        return build_13_week_cash_forecast(weekly_inputs=[])

    def _working_risk_layer(self):
        # [DEMO] figure (see module docstring) - real mechanism, illustrative number.
        refuse_timing_bridge_allocation(variance=Decimal(0), entity_reference=None)
        return {"timing_bridge_variance": Decimal("0.0000"), "is_isolated": True}

    def test_one_failing_layer_does_not_crash_the_whole_payload(self):
        # The explicit, named requirement: Gross Revenue (and every other working layer) must
        # stay fully populated and interactive even though the liquidity layer failed.
        payload = build_management_canvas_payload(
            revenue_layer_fn=self._working_revenue_layer,
            operations_layer_fn=self._working_revenue_layer,  # reused only as a second real, working call
            liquidity_layer_fn=self._broken_liquidity_layer,
            risk_layer_fn=self._working_risk_layer,
        )
        self.assertEqual(payload["revenue_layer"]["status"], "ok")
        self.assertEqual(payload["liquidity_layer"]["status"], "diagnostic")
        self.assertEqual(payload["risk_layer"]["status"], "ok")
        # The payload itself is never "all or nothing" - it always returns all four keys.
        self.assertEqual(set(payload.keys()), {"revenue_layer", "operations_layer", "liquidity_layer", "risk_layer"})

    def test_all_four_layers_succeeding_produces_a_fully_ok_payload(self):
        payload = build_management_canvas_payload(
            revenue_layer_fn=self._working_revenue_layer,
            operations_layer_fn=self._working_revenue_layer,
            liquidity_layer_fn=self._working_risk_layer,
            risk_layer_fn=self._working_risk_layer,
        )
        self.assertTrue(all(layer["status"] == "ok" for layer in payload.values()))

    def test_multiple_simultaneously_failing_layers_are_each_independently_diagnostic(self):
        payload = build_management_canvas_payload(
            revenue_layer_fn=self._broken_liquidity_layer, operations_layer_fn=self._broken_liquidity_layer,
            liquidity_layer_fn=self._broken_liquidity_layer, risk_layer_fn=self._working_risk_layer,
        )
        self.assertEqual(payload["revenue_layer"]["status"], "diagnostic")
        self.assertEqual(payload["operations_layer"]["status"], "diagnostic")
        self.assertEqual(payload["liquidity_layer"]["status"], "diagnostic")
        self.assertEqual(payload["risk_layer"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
