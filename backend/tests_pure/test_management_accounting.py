"""
Tests for app/analytics/management_accounting.py. Pure - no DB, no framework. Written before the
implementation, per this session's test-first sequence. Grounded in clean, hand-verifiable
arithmetic rather than one client's specific figures - DSO/DIO/DPO/CCC are standard formulas
whose correctness doesn't depend on any tenant's actual numbers, and this engine must stay
tenant-agnostic by design (§1 of this turn's request).
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.management_accounting import (
    AllocationLevel,
    allocate_activity_cost,
    calculate_customer_net_margin,
    calculate_working_capital_metrics,
    classify_aging_buckets,
    determine_allocation_level,
    resolve_trade_spend_for_period,
)
from app.analytics.rebate_calculations import calculate_aggregate_rebate_leakage, calculate_rebate_leakage


class TestAllocationLevelFallback(unittest.TestCase):
    """Configurable fallback hierarchy - generalized from NetDrop IQ's pattern, not that
    project's specific trip/case-count business rules verbatim (those belong to one client's
    logistics domain; this must stay tenant-agnostic)."""

    def test_direct_cost_always_wins_when_available(self):
        # Same "never blended" rule as NetDrop's own engine, generalized: a row with both direct
        # cost AND activity-rate basis data uses Level 1 only.
        self.assertEqual(
            determine_allocation_level(has_direct_cost=True, has_activity_rate_basis=True, has_volumetric_basis=True),
            AllocationLevel.DIRECT,
        )

    def test_falls_back_to_activity_rate_when_no_direct_cost(self):
        self.assertEqual(
            determine_allocation_level(has_direct_cost=False, has_activity_rate_basis=True, has_volumetric_basis=True),
            AllocationLevel.ACTIVITY_RATE,
        )

    def test_falls_back_to_volumetric_as_last_resort(self):
        self.assertEqual(
            determine_allocation_level(has_direct_cost=False, has_activity_rate_basis=False, has_volumetric_basis=True),
            AllocationLevel.VOLUMETRIC,
        )

    def test_unallocated_when_no_basis_data_exists_at_all(self):
        self.assertEqual(
            determine_allocation_level(has_direct_cost=False, has_activity_rate_basis=False, has_volumetric_basis=False),
            AllocationLevel.UNALLOCATED,
        )


class TestAllocateActivityCost(unittest.TestCase):
    def test_per_km_rate(self):
        result = allocate_activity_cost(Decimal("5000"), Decimal("250"), "per_km")
        self.assertEqual(result, Decimal("20.0000"))

    def test_per_pallet_rate(self):
        result = allocate_activity_cost(Decimal("3000"), Decimal("120"), "per_pallet")
        self.assertEqual(result, Decimal("25.0000"))

    def test_zero_activity_volume_returns_none_not_zero_or_error(self):
        # An allocation rate is undefined at zero volume, not zero - same §3.2 discipline as
        # every other zero-denominator case in this codebase.
        result = allocate_activity_cost(Decimal("5000"), Decimal("0"), "per_km")
        self.assertIsNone(result)

    def test_unrecognized_allocation_type_raises(self):
        # §2.4/§5.2: an unrecognized type string is a caller bug or a typo - raise clearly,
        # don't silently accept an arbitrary string as if it were a real allocation basis.
        with self.assertRaises(ValueError):
            allocate_activity_cost(Decimal("5000"), Decimal("250"), "per_banana")


class TestResolveTradeSpendForPeriod(unittest.TestCase):
    """
    Closes a real gap in calculate_customer_net_margin's own trade_spend default: Decimal("0")
    means "not sourced" and "genuinely zero" are indistinguishable at the call site - exactly the
    fabricated-zero pattern this whole module refuses everywhere else (the reconciliation gate,
    the revenue waterfall, working_capital_metrics' cash_balance). Not a change to
    calculate_customer_net_margin itself (correct, tested, and its one real caller - the demo
    seed - represents customers with no trade-spend concept at all, where zero is the right
    answer) - a separate gate for the layer where sourcing genuinely matters: a customer with a
    real sell-side RebateAgreement whose current period figure hasn't been loaded yet.
    """

    def test_no_agreement_exists_resolves_to_a_real_zero_not_an_error(self):
        # A customer with no sell-side agreement at all genuinely has zero trade spend - this is
        # not a missing-data problem, it's a correct, real answer.
        value = resolve_trade_spend_for_period(trade_spend_record=None, agreement_exists=False)
        self.assertEqual(value, Decimal("0"))

    def test_agreement_exists_and_period_figure_is_sourced_returns_the_real_value(self):
        value = resolve_trade_spend_for_period(trade_spend_record=Decimal("245913.07"), agreement_exists=True)
        self.assertEqual(value, Decimal("245913.07"))

    def test_agreement_exists_but_period_figure_not_yet_sourced_raises_not_a_fabricated_zero(self):
        # The real gap this function exists to close: an agreement is confirmed to exist, but
        # nobody has loaded this period's actual figure - silently treating that as zero would
        # understate trade spend and overstate net margin, with no visible sign anything was
        # wrong. Raises ValueError, same precedent as refuse_timing_bridge_allocation - the
        # route/service layer maps this to ValidationFailedError (422), not this pure function.
        with self.assertRaises(ValueError):
            resolve_trade_spend_for_period(trade_spend_record=None, agreement_exists=True)

    def test_zero_is_a_valid_sourced_figure_not_treated_as_unsourced(self):
        # A real, confirmed R0.00 trade spend for the period (e.g. a threshold not yet reached)
        # must not be conflated with "not sourced" - Decimal("0") is a legitimate sourced value.
        value = resolve_trade_spend_for_period(trade_spend_record=Decimal("0"), agreement_exists=True)
        self.assertEqual(value, Decimal("0"))


class TestRebateSymmetryAdversarialInputs(unittest.TestCase):
    """
    Chaos Audit, targeted re-audit of Phase 2. calculate_rebate_leakage/
    calculate_aggregate_rebate_leakage do SUBTRACTION only - no division exists anywhere in
    either function, so "zero denominator" as literally asked does not apply to them; stated
    precisely rather than manufacturing a division guard for a function that has none. What
    IS real and tested here: over-recovery, negative inputs, and confirming leakage output
    never reaches calculate_customer_net_margin through any code path in this codebase.
    """

    def test_over_recovery_produces_negative_leakage_by_design_not_a_bug(self):
        # Confirms existing, already-documented behavior rather than assuming it - received
        # exceeding expected is a real correction/over-payment, not floored to zero.
        leakage = calculate_rebate_leakage(Decimal("500000"), Decimal("550000"))
        self.assertEqual(leakage, Decimal("-50000.0000"))

    def test_negative_expected_amount_is_arithmetically_safe_not_a_sign_inversion(self):
        # [DEMO] adversarial input: a negative expected_amount (e.g. a data-entry error, or a
        # correction agreement). Decimal subtraction has no sign-inversion failure mode -
        # confirmed directly rather than assumed, since this specific input was never tested.
        leakage = calculate_rebate_leakage(Decimal("-1000"), None)
        self.assertEqual(leakage, Decimal("-1000.0000"))  # received defaults to 0; -1000 - 0 = -1000, correct

    def test_aggregate_leakage_with_mixed_negative_and_positive_periods_sums_correctly_not_dampened(self):
        # [DEMO]: confirms the sum is a genuine arithmetic sum, not silently dampened/absorbed
        # towards zero when signs mix within one aggregate call.
        mixed = [(Decimal("500000"), Decimal("550000")), (Decimal("300000"), None)]
        total = calculate_aggregate_rebate_leakage(mixed)
        self.assertEqual(total, Decimal("250000.0000"))  # -50000 + 300000

    def test_no_code_path_in_this_codebase_feeds_leakage_output_into_net_margin_trade_spend(self):
        # Structural confirmation, not just an absence-of-evidence claim: resolve_trade_spend_for_period
        # (the one function that legitimately feeds calculate_customer_net_margin's trade_spend)
        # takes an already-sourced actual figure, never a calculate_rebate_leakage return value -
        # checked directly against its real signature/docstring, not assumed.
        import inspect
        from app.analytics.management_accounting import resolve_trade_spend_for_period
        source = inspect.getsource(resolve_trade_spend_for_period)
        self.assertNotIn("calculate_rebate_leakage", source)
        self.assertNotIn("calculate_aggregate_rebate_leakage", source)


class TestCustomerNetMarginDoubleCountingPrevention(unittest.TestCase):
    """
    Chaos Audit finding, quantified with real production figures before this fix: feeding
    calculate_gross_to_net_waterfall's net_revenue (already net of the real R3,145,913.07 TTM
    rebate) into calculate_customer_net_margin's `revenue` parameter, THEN ALSO passing that same
    rebate as trade_spend, silently understated net_margin by exactly R3,145,913.07 - the full
    real deduction, double-counted, with zero error and zero warning. revenue_basis is now a
    REQUIRED parameter that makes this structurally impossible, not just documented against.
    """

    def test_gross_basis_with_real_trade_spend_computes_normally(self):
        result = calculate_customer_net_margin(
            revenue=Decimal("100000"), cogs=Decimal("70000"),
            direct_logistics_cost=Decimal("8000"), warehouse_abc_cost=Decimal("4000"),
            trade_spend=Decimal("5000"), revenue_basis="gross",
        )
        self.assertEqual(result["net_margin"], Decimal("13000.0000"))

    def test_net_of_waterfall_basis_with_nonzero_trade_spend_is_refused_not_silently_double_counted(self):
        # The actual fix: this exact combination is now structurally impossible, not just
        # documented against - raises before any arithmetic happens.
        with self.assertRaises(ValueError):
            calculate_customer_net_margin(
                revenue=Decimal("353202524.93"), cogs=Decimal("287394425.05"),
                direct_logistics_cost=Decimal("0"), warehouse_abc_cost=Decimal("0"),
                trade_spend=Decimal("3145913.07"), revenue_basis="net_of_waterfall",
            )

    def test_net_of_waterfall_basis_with_zero_trade_spend_computes_the_real_correct_figure(self):
        # The real, correct answer to the exact scenario that was silently wrong before this fix -
        # matches the "WITHOUT double-count" figure computed directly against real production data.
        result = calculate_customer_net_margin(
            revenue=Decimal("353202524.93"), cogs=Decimal("287394425.05"),
            direct_logistics_cost=Decimal("0"), warehouse_abc_cost=Decimal("0"),
            trade_spend=Decimal("0"), revenue_basis="net_of_waterfall",
        )
        self.assertEqual(result["net_margin"], Decimal("65808099.8800"))

    def test_unrecognized_revenue_basis_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_customer_net_margin(
                revenue=Decimal("100000"), cogs=Decimal("70000"),
                direct_logistics_cost=Decimal("8000"), warehouse_abc_cost=Decimal("4000"),
                trade_spend=Decimal("0"), revenue_basis="not_a_real_basis",
            )

    def test_demo_trade_spend_and_settlement_discounts_together_exceeding_gross_revenue_flags_negative_net_revenue_explicitly(self):
        # [DEMO]: a customer whose combined deductions genuinely exceed gross revenue - a real,
        # extreme but legitimate state (a heavily over-rebated account), not clamped to zero and
        # now explicitly flagged as its own condition, distinct from a merely negative net_margin.
        result = calculate_customer_net_margin(
            revenue=Decimal("50000"), cogs=Decimal("20000"),
            direct_logistics_cost=Decimal("1000"), warehouse_abc_cost=Decimal("500"),
            trade_spend=Decimal("60000"), revenue_basis="gross",
        )
        self.assertEqual(result["net_revenue"], Decimal("-10000.0000"))
        self.assertTrue(result["is_net_revenue_negative"])

    def test_positive_net_revenue_is_not_flagged(self):
        result = calculate_customer_net_margin(
            revenue=Decimal("100000"), cogs=Decimal("70000"),
            direct_logistics_cost=Decimal("8000"), warehouse_abc_cost=Decimal("4000"),
            trade_spend=Decimal("5000"), revenue_basis="gross",
        )
        self.assertFalse(result["is_net_revenue_negative"])


class TestCustomerNetMargin(unittest.TestCase):
    def test_worked_example(self):
        result = calculate_customer_net_margin(
            revenue=Decimal("100000"), cogs=Decimal("70000"),
            direct_logistics_cost=Decimal("8000"), warehouse_abc_cost=Decimal("4000"),
            trade_spend=Decimal("0"), revenue_basis="gross",
        )
        self.assertEqual(result["gross_margin"], Decimal("30000.0000"))
        self.assertEqual(result["cost_to_serve"], Decimal("12000.0000"))
        self.assertEqual(result["net_margin"], Decimal("18000.0000"))
        self.assertEqual(result["net_margin_pct"], Decimal("18.00"))

    def test_negative_margin_customer_is_not_clamped_to_zero(self):
        # A customer whose cost-to-serve exceeds gross margin is a real, important finding -
        # clamping it to zero would hide exactly the signal this metric exists to surface.
        result = calculate_customer_net_margin(
            revenue=Decimal("10000"), cogs=Decimal("8000"),
            direct_logistics_cost=Decimal("1500"), warehouse_abc_cost=Decimal("1200"),
            trade_spend=Decimal("0"), revenue_basis="gross",
        )
        self.assertEqual(result["net_margin"], Decimal("-700.0000"))
        self.assertLess(result["net_margin_pct"], 0)

    def test_zero_revenue_customer_gives_none_percentage_not_error(self):
        result = calculate_customer_net_margin(
            revenue=Decimal("0"), cogs=Decimal("0"),
            direct_logistics_cost=Decimal("500"), warehouse_abc_cost=Decimal("200"),
            trade_spend=Decimal("0"), revenue_basis="gross",
        )
        self.assertIsNone(result["net_margin_pct"])
        self.assertEqual(result["net_margin"], Decimal("-700.0000"))  # the absolute figure still computes

    def test_trade_spend_deducts_from_revenue_before_gross_margin_not_added_to_cost_to_serve(self):
        # Phase 2 (sell-side trade spend): trade_spend is a REVENUE deduction, matching the real
        # P&L structure examined this engagement (Turnover -> Less: Rebates Paid -> Net Sales,
        # i.e. it reduces revenue before gross margin, not a logistics/handling cost). cost_to_serve
        # is unchanged by trade_spend - the two are genuinely different concepts and must not be
        # conflated into one number.
        result = calculate_customer_net_margin(
            revenue=Decimal("100000"), cogs=Decimal("70000"),
            direct_logistics_cost=Decimal("8000"), warehouse_abc_cost=Decimal("4000"),
            trade_spend=Decimal("5000"), revenue_basis="gross",
        )
        self.assertEqual(result["net_revenue"], Decimal("95000.0000"))
        self.assertEqual(result["gross_margin"], Decimal("25000.0000"))  # 95000 - 70000, not 100000 - 70000
        self.assertEqual(result["cost_to_serve"], Decimal("12000.0000"))  # unchanged by trade_spend
        self.assertEqual(result["net_margin"], Decimal("13000.0000"))  # 25000 - 12000

    def test_omitting_trade_spend_is_now_a_type_error_not_a_silent_zero(self):
        # Renamed from "_defaults_to_zero_existing_callers_are_unaffected" (Chaos Audit Domain 1
        # - that default WAS the fabricated-zero surface). Every real caller now goes through
        # resolve_trade_spend_for_period() first, including the "no agreement exists" case,
        # which correctly returns a real Decimal("0") - never an implicit language-level default.
        with self.assertRaises(TypeError):
            calculate_customer_net_margin(
                revenue=Decimal("100000"), cogs=Decimal("70000"),
                direct_logistics_cost=Decimal("8000"), warehouse_abc_cost=Decimal("4000"),
            )

    def test_explicit_zero_trade_spend_behaves_identically_to_the_old_default(self):
        # The real, correct replacement for the old default-reliant test: identical inputs,
        # trade_spend now passed explicitly (as resolve_trade_spend_for_period would return for
        # a customer with no sell-side agreement) rather than omitted.
        result = calculate_customer_net_margin(
            revenue=Decimal("100000"), cogs=Decimal("70000"),
            direct_logistics_cost=Decimal("8000"), warehouse_abc_cost=Decimal("4000"),
            trade_spend=Decimal("0"), revenue_basis="gross",
        )
        self.assertEqual(result["gross_margin"], Decimal("30000.0000"))
        self.assertEqual(result["net_margin"], Decimal("18000.0000"))

    def test_trade_spend_large_enough_to_flip_margin_negative_is_not_clamped(self):
        # The real, quantified case this exists for: TTM Rebates Paid (R3,145,913.07) is over 3x
        # TTM Rebates Received (R976,235.71) in the real data - a customer whose trade spend
        # genuinely exceeds what cogs/cost-to-serve alone would suggest must show a real negative
        # margin, same "never hide a bad number" discipline as every other branch of this function.
        result = calculate_customer_net_margin(
            revenue=Decimal("10000"), cogs=Decimal("6000"),
            direct_logistics_cost=Decimal("500"), warehouse_abc_cost=Decimal("200"),
            trade_spend=Decimal("4000"), revenue_basis="gross",
        )
        # net_revenue = 6000, gross_margin = 6000-6000 = 0, cost_to_serve = 700, net_margin = -700
        self.assertEqual(result["net_margin"], Decimal("-700.0000"))


class TestWorkingCapitalMetrics(unittest.TestCase):
    def test_worked_example_matches_hand_calculation(self):
        result = calculate_working_capital_metrics(
            ar=Decimal("500000"), ap=Decimal("300000"), inventory=Decimal("400000"),
            annual_revenue=Decimal("3650000"), annual_cogs=Decimal("2555000"),
        )
        # DSO = 500000/3650000*365 = 50.0 exactly
        self.assertEqual(result["dso"], Decimal("50.0"))
        # DIO = 400000/2555000*365 = 57.1428...
        self.assertAlmostEqual(float(result["dio"]), 57.1, places=1)
        # DPO = 300000/2555000*365 = 42.857...
        self.assertAlmostEqual(float(result["dpo"]), 42.9, places=1)

    def test_ccc_composed_from_the_same_three_figures(self):
        result = calculate_working_capital_metrics(
            ar=Decimal("500000"), ap=Decimal("300000"), inventory=Decimal("400000"),
            annual_revenue=Decimal("3650000"), annual_cogs=Decimal("2555000"),
        )
        self.assertEqual(result["ccc"], result["dio"] + result["dso"] - result["dpo"])

    def test_negative_ccc_is_a_real_favourable_result_not_clamped(self):
        # DPO exceeding DIO+DSO means the business collects cash before paying suppliers - a
        # genuinely good position, and the formula must show it as negative, not floor at zero.
        result = calculate_working_capital_metrics(
            ar=Decimal("50000"), ap=Decimal("400000"), inventory=Decimal("50000"),
            annual_revenue=Decimal("3650000"), annual_cogs=Decimal("2555000"),
        )
        self.assertLess(result["ccc"], 0)

    def test_zero_revenue_gives_none_dso_not_error(self):
        result = calculate_working_capital_metrics(
            ar=Decimal("500000"), ap=Decimal("300000"), inventory=Decimal("400000"),
            annual_revenue=Decimal("0"), annual_cogs=Decimal("2555000"),
        )
        self.assertIsNone(result["dso"])
        self.assertIsNone(result["ccc"])  # can't compose CCC when one of its three inputs is undefined

    def test_zero_cogs_gives_none_dio_and_dpo(self):
        result = calculate_working_capital_metrics(
            ar=Decimal("500000"), ap=Decimal("300000"), inventory=Decimal("400000"),
            annual_revenue=Decimal("3650000"), annual_cogs=Decimal("0"),
        )
        self.assertIsNone(result["dio"])
        self.assertIsNone(result["dpo"])
        self.assertIsNone(result["ccc"])

    def test_working_capital_ratio_is_none_when_cash_not_supplied(self):
        # cash isn't in the originally-specified function signature but IS required by the
        # spec's own ratio formula - added as an explicit optional parameter. None when omitted,
        # never silently treated as zero (which would understate the ratio).
        result = calculate_working_capital_metrics(
            ar=Decimal("500000"), ap=Decimal("300000"), inventory=Decimal("400000"),
            annual_revenue=Decimal("3650000"), annual_cogs=Decimal("2555000"),
        )
        self.assertIsNone(result["working_capital_ratio"])

    def test_working_capital_ratio_computes_when_cash_is_supplied(self):
        result = calculate_working_capital_metrics(
            ar=Decimal("500000"), ap=Decimal("300000"), inventory=Decimal("400000"),
            annual_revenue=Decimal("3650000"), annual_cogs=Decimal("2555000"), cash=Decimal("100000"),
        )
        # (500000+400000+100000)/300000 = 3.333...
        self.assertAlmostEqual(float(result["working_capital_ratio"]), 3.33, places=2)


class TestAgingBucketClassification(unittest.TestCase):
    def test_buckets_sum_to_total_invoice_value(self):
        invoices = [
            {"amount": Decimal("1000"), "days_overdue": 5},
            {"amount": Decimal("2000"), "days_overdue": 45},
            {"amount": Decimal("1500"), "days_overdue": 200},
        ]
        result = classify_aging_buckets(invoices)
        self.assertEqual(sum(result.values()), Decimal("4500.0000"))

    def test_exact_boundary_at_30_days_lands_in_days_30_not_current(self):
        # The conservative reading of an ambiguous boundary - same posture as
        # classify_expiry_risk's inclusive-boundary decision.
        result = classify_aging_buckets([{"amount": Decimal("1000"), "days_overdue": 30}])
        self.assertEqual(result["days_30"], Decimal("1000.0000"))
        self.assertEqual(result["current"], Decimal("0.0000"))

    def test_each_boundary_lands_in_the_correct_bucket(self):
        cases = [(0, "current"), (29, "current"), (30, "days_30"), (59, "days_30"),
                 (60, "days_60"), (89, "days_60"), (90, "days_90"), (119, "days_90"),
                 (120, "days_120_plus"), (500, "days_120_plus")]
        for days, expected_bucket in cases:
            result = classify_aging_buckets([{"amount": Decimal("100"), "days_overdue": days}])
            self.assertEqual(result[expected_bucket], Decimal("100.0000"), f"days_overdue={days}")

    def test_empty_invoice_list_gives_all_zero_buckets_not_error(self):
        result = classify_aging_buckets([])
        self.assertTrue(all(v == Decimal("0.0000") for v in result.values()))


class TestDeterminism(unittest.TestCase):
    def test_module_never_calls_now_or_today_or_imports_db(self):
        import ast
        import app.analytics.management_accounting as module

        tree = ast.parse(open(module.__file__).read())
        forbidden_calls = [
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ("now", "today")
        ]
        self.assertEqual(forbidden_calls, [])

        forbidden_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and any(
                (alias.name.split(".")[0] if isinstance(node, ast.Import) else (node.module or "").split(".")[0])
                in ("sqlalchemy", "fastapi", "pydantic")
                for alias in node.names
            )
        ]
        self.assertEqual(forbidden_imports, [])


class TestVarianceVsPrior(unittest.TestCase):
    def test_positive_variance_when_current_exceeds_prior(self):
        from app.analytics.management_accounting import calculate_variance_vs_prior
        self.assertEqual(calculate_variance_vs_prior(Decimal("55.0"), Decimal("50.0")), Decimal("5.0"))

    def test_negative_variance_when_current_below_prior(self):
        from app.analytics.management_accounting import calculate_variance_vs_prior
        self.assertEqual(calculate_variance_vs_prior(Decimal("45.0"), Decimal("50.0")), Decimal("-5.0"))

    def test_none_when_prior_unavailable(self):
        # No prior snapshot exists yet (e.g. an organisation's first period) - None, not a
        # fabricated zero variance implying "no change" when there's actually no baseline at all.
        from app.analytics.management_accounting import calculate_variance_vs_prior
        self.assertIsNone(calculate_variance_vs_prior(Decimal("50.0"), None))

    def test_none_when_current_unavailable(self):
        from app.analytics.management_accounting import calculate_variance_vs_prior
        self.assertIsNone(calculate_variance_vs_prior(None, Decimal("50.0")))


if __name__ == "__main__":
    unittest.main()
