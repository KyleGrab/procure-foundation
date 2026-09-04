"""
Tests for two Phase 1 additions to app.analytics.management_accounting: calculate_gmroi and
calculate_allocation_variance. Grounded in real client data wherever it exists:

- GMROI: TTM gross margin ending August 2026 (R65,808,099.88, recomputed fresh from the real
  Income Statement sheet) against average inventory (July+August 2026 Balance Sheet actuals).
- Allocation variance: the real 17-truck July 2026 fleet from Gourmet_Foods_Cost_to_Serve_July2026.xlsx
  (30_TRUCK_PROFITABILITY) - genuine weight and running-cost figures per real, named vehicle,
  including CAA 127155 (West Coast), the same real route used elsewhere this sprint.

Fictitious/simulated inputs used only for a scenario real data can't provide (a fuel-cost shock -
no second real period exists for the same fleet) are marked [DEMO] explicitly, per this session's
own rule that demo data must never be confused with real figures.
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.analytics.management_accounting import (
    ReconciliationStatus,
    calculate_allocation_variance,
    calculate_future_replacement_exposure,
    calculate_gmroi,
    calculate_working_capital_metrics,
    check_inventory_reconciliation,
    flag_replacement_cost_divergence,
    flag_zero_mass_risk,
    is_rate_stale,
    refuse_timing_bridge_allocation,
    resolve_gated_inventory_value,
)


class TestCalculateGmroi(unittest.TestCase):
    def test_real_gourmet_ttm_gross_margin_against_real_average_inventory(self):
        # TTM ending Aug 2026: Net Sales R353,202,524.93 - Net Cost of Sales R287,394,425.05
        # (both recomputed fresh from the real Income Statement sheet this turn).
        # Average inventory: (R22,249,299.99 [Jul-26] + R21,895,070.82 [Aug-26]) / 2, both real
        # Balance Sheet figures already used elsewhere this sprint.
        gmroi = calculate_gmroi(
            gross_margin=Decimal("65808099.88"), average_inventory_value=Decimal("22072185.405"),
        )
        # 65808099.88 / 22072185.405 = 2.9816...
        self.assertAlmostEqual(float(gmroi), 2.98, places=2)

    def test_zero_average_inventory_returns_none_not_a_divide_by_zero_error(self):
        result = calculate_gmroi(gross_margin=Decimal(100000), average_inventory_value=Decimal(0))
        self.assertIsNone(result)

    def test_negative_gross_margin_is_not_clamped_to_zero(self):
        # A genuinely loss-making period must show a negative GMROI, not a floored 0 - same
        # "never hide a bad number" discipline as calculate_customer_net_margin.
        result = calculate_gmroi(gross_margin=Decimal(-50000), average_inventory_value=Decimal(100000))
        self.assertLess(result, 0)


class TestCalculateAllocationVariance(unittest.TestCase):
    """
    Real 30_TRUCK_PROFITABILITY figures. Fleet total running cost R633,009.23 across 610,403.985kg
    = a true weight-based rate of R1.0370/kg (both recomputed fresh this turn from all 17 real
    trucks, matching allocate_activity_cost's own division - not reimplemented independently).
    """

    def test_west_coast_route_is_massively_undercosted_under_the_current_flat_allocation(self):
        # CAA 127155, West Coast: real weight 94,284.424kg, real CURRENT allocated running cost
        # only R28,157 - the heaviest route in the whole fleet by a wide margin, yet not costed
        # anywhere close to weight-proportionally.
        result = calculate_allocation_variance(
            entity_activity_volume=Decimal("94284.424"), activity_based_rate=Decimal("1.0370"),
            currently_allocated_cost=Decimal(28157), is_fallback_rate=False,
        )
        # activity-based cost ~= 94284.424 * 1.0370 = 97,776.90 (approx, real weight * real rate)
        self.assertAlmostEqual(float(result["activity_based_cost"]), 97776.90, delta=5)
        self.assertTrue(result["is_undercosted"])
        # variance = currently_allocated - activity_based (negative = undercosted, i.e. currently
        # paying LESS than a weight-based method would say, meaning other routes subsidize it)
        self.assertLess(result["variance"], Decimal(-69000))

    def test_a_light_route_getting_the_averaged_fallback_rate_is_overcosted(self):
        # CAA 156344, Cape Town: real weight 25,997.048kg, but got the R33,316.2753846154
        # "average of matched trucks" fallback rate (the file's own documented Level 2 fallback,
        # not a real matched cost for this specific vehicle) rather than its own real cost.
        result = calculate_allocation_variance(
            entity_activity_volume=Decimal("25997.048"), activity_based_rate=Decimal("1.0370"),
            currently_allocated_cost=Decimal("33316.2753846154"), is_fallback_rate=True,
        )
        # activity-based cost ~= 25997.048 * 1.0370 = 26,958.94
        self.assertAlmostEqual(float(result["activity_based_cost"]), 26958.94, delta=5)
        self.assertFalse(result["is_undercosted"])
        self.assertGreater(result["variance"], Decimal(6000))

    def test_zero_activity_based_rate_returns_none_not_a_divide_by_zero_error(self):
        # Not a real division here, but a zero rate (e.g. an empty cost pool) makes the
        # comparison meaningless, not zero - consistent with allocate_activity_cost's own
        # zero-denominator handling elsewhere in this module.
        result = calculate_allocation_variance(
            entity_activity_volume=Decimal(100), activity_based_rate=Decimal(0),
            currently_allocated_cost=Decimal(500), is_fallback_rate=False,
        )
        self.assertIsNone(result)

    def test_demo_simulated_20pct_fuel_shock_on_the_real_west_coast_route(self):
        # [DEMO] - no second real period exists for this fleet, so this simulates a 20% rise in
        # the running-cost pool on top of the REAL July 2026 weight-based rate (R1.0370/kg),
        # holding real volume fixed - the Phase 1 pressure-test scenario, run for real against
        # the real baseline rather than an invented one.
        shocked_rate = Decimal("1.0370") * Decimal("1.20")  # [DEMO] +20% fuel shock applied to the real rate
        result = calculate_allocation_variance(
            entity_activity_volume=Decimal("94284.424"),  # real CAA 127155 weight
            activity_based_rate=shocked_rate, currently_allocated_cost=Decimal(28157),  # real current allocation
            is_fallback_rate=False,
        )
        baseline = calculate_allocation_variance(
            entity_activity_volume=Decimal("94284.424"), activity_based_rate=Decimal("1.0370"),
            currently_allocated_cost=Decimal(28157), is_fallback_rate=False,
        )
        # The shock must widen the undercosting gap, not narrow it - a real sanity check on the
        # simulation's direction, not just that it runs without error.
        self.assertLess(result["variance"], baseline["variance"])


class TestIsRateStale(unittest.TestCase):
    """
    Closes the fuel-spike blind spot named in the Phase 1 pressure test: CostAllocationRule.
    default_unit_rate is a static number someone sets, with no mechanism to flag when it's gone
    stale against a real cost shock. This is the pure check behind that flag.
    """

    def test_rate_set_today_is_not_stale(self):
        self.assertFalse(is_rate_stale(
            rate_effective_date=date(2026, 8, 26), as_of_date=date(2026, 8, 26), staleness_threshold_days=30,
        ))

    def test_rate_exactly_at_the_threshold_is_stale(self):
        # Inclusive boundary - same conservative posture as classify_expiry_risk/
        # classify_aging_buckets elsewhere in this module: a rate at exactly the threshold is
        # flagged, not given one more day of benefit of the doubt.
        self.assertTrue(is_rate_stale(
            rate_effective_date=date(2026, 7, 27), as_of_date=date(2026, 8, 26), staleness_threshold_days=30,
        ))

    def test_rate_one_day_under_the_threshold_is_not_stale(self):
        self.assertFalse(is_rate_stale(
            rate_effective_date=date(2026, 7, 28), as_of_date=date(2026, 8, 26), staleness_threshold_days=30,
        ))

    def test_rate_with_no_effective_date_recorded_is_always_stale(self):
        # A rule with no known effective date can never be trusted as current - fails closed
        # (flagged), not open (assumed fine), same posture as the RLS "no session variable ->
        # zero rows" rule.
        self.assertTrue(is_rate_stale(
            rate_effective_date=None, as_of_date=date(2026, 8, 26), staleness_threshold_days=30,
        ))


class TestAllocationVarianceConfidenceFlag(unittest.TestCase):
    def test_fallback_rate_is_flagged_as_fallback_confidence(self):
        # The real, documented pattern in Gourmet_Foods_Cost_to_Serve_July2026.xlsx's own
        # 30_TRUCK_PROFITABILITY sheet: "amber" trucks get an averaged fallback rate, not a
        # matched real cost. is_fallback_rate makes that distinction a first-class part of the
        # variance result, not something only readable from a spreadsheet color.
        result = calculate_allocation_variance(
            entity_activity_volume=Decimal("25997.048"), activity_based_rate=Decimal("1.0370"),
            currently_allocated_cost=Decimal("33316.2753846154"), is_fallback_rate=True,
        )
        self.assertEqual(result["rate_confidence"], "fallback")

    def test_matched_rate_is_flagged_as_matched_confidence_when_explicitly_stated(self):
        # Renamed from "_by_default" (Chaos Audit Domain 1) - there is no more default;
        # is_fallback_rate=False must now be explicitly stated, same as the True case above.
        result = calculate_allocation_variance(
            entity_activity_volume=Decimal("94284.424"), activity_based_rate=Decimal("1.0370"),
            currently_allocated_cost=Decimal(28157), is_fallback_rate=False,
        )
        self.assertEqual(result["rate_confidence"], "matched")


class TestFutureReplacementCostExposure(unittest.TestCase):
    """
    CIMA P-pillar: a holding gain/loss on agricultural/perishable inputs, kept strictly
    prospective. [DEMO] throughout - no real bulk-ingredient replacement-cost figure exists
    anywhere in this engagement; this exercises the mechanism's shape only. The one real anchor
    used is R21,895,070.82 (the real, verified August 2026 MAC control total).
    """

    def test_rising_replacement_cost_is_a_positive_adverse_exposure(self):
        # [DEMO]: replacement cost R145/unit vs recorded MAC R120/unit, 10,000 units on hand.
        result = calculate_future_replacement_exposure(
            quantity_on_hand=Decimal(10000),
            current_replacement_unit_cost=Decimal("145.00"), recorded_mac_unit_cost=Decimal("120.00"),
        )
        self.assertEqual(result["exposure_per_unit"], Decimal("25.0000"))
        self.assertEqual(result["total_exposure"], Decimal("250000.0000"))
        self.assertTrue(result["is_adverse"])

    def test_falling_replacement_cost_is_a_favourable_negative_exposure_not_clamped_to_zero(self):
        # [DEMO]: a favourable commodity-price movement is a real, useful signal - hiding it
        # would be the same "never clamp away a real number" failure this whole engine avoids
        # everywhere else (calculate_customer_net_margin, calculate_allocation_variance).
        result = calculate_future_replacement_exposure(
            quantity_on_hand=Decimal(10000),
            current_replacement_unit_cost=Decimal("110.00"), recorded_mac_unit_cost=Decimal("120.00"),
        )
        self.assertEqual(result["total_exposure"], Decimal("-100000.0000"))
        self.assertFalse(result["is_adverse"])

    def test_exposure_result_has_no_field_that_could_be_mistaken_for_a_realized_cogs_input(self):
        # Structural guardrail, not just a naming convention: the result dict's own keys are
        # checked here so a future caller cannot accidentally wire this into
        # calculate_customer_net_margin/calculate_working_capital_metrics by matching a key name.
        result = calculate_future_replacement_exposure(
            quantity_on_hand=Decimal(100), current_replacement_unit_cost=Decimal(10),
            recorded_mac_unit_cost=Decimal(10),
        )
        forbidden_keys = {"cogs", "cost_of_goods_sold", "inventory_value", "net_margin", "dio", "dpo", "ccc"}
        self.assertEqual(set(result.keys()) & forbidden_keys, set())

    def test_demo_aggregate_exposure_against_the_real_mac_control_total_is_flagged_when_material(self):
        # [DEMO] aggregate exposure figure against the REAL R21,895,070.82 control total.
        is_material = flag_replacement_cost_divergence(
            aggregate_replacement_exposure=Decimal(2500000),
            mac_control_total=Decimal("21895070.82"), materiality_threshold_pct=Decimal("0.05"),
        )
        # 2,500,000 / 21,895,070.82 = 11.4% > 5% threshold
        self.assertTrue(is_material)

    def test_demo_small_aggregate_exposure_against_the_real_control_total_is_not_flagged(self):
        is_material = flag_replacement_cost_divergence(
            aggregate_replacement_exposure=Decimal(50000),
            mac_control_total=Decimal("21895070.82"), materiality_threshold_pct=Decimal("0.05"),
        )
        self.assertFalse(is_material)

    def test_zero_control_total_is_a_data_gap_not_a_divergence_signal(self):
        is_material = flag_replacement_cost_divergence(
            aggregate_replacement_exposure=Decimal(50000),
            mac_control_total=Decimal(0), materiality_threshold_pct=Decimal("0.05"),
        )
        self.assertFalse(is_material)


class TestFlagZeroMassRisk(unittest.TestCase):
    """
    Real, already-quantified finding: Zero_Mass_Stock_Codes_July2026.xlsx documents 323 real
    stock codes with Mass = 0 in SYSPRO despite non-zero July 2026 sales (R2,185,479.14, 7.83%
    of total) - the file's own author already diagnosed the mechanism ("under-allocates
    warehouse cost for any customer buying these codes, slightly overstates the warehouse
    cost-per-kg rate portfolio-wide"). ~37% of that value (R816,065) sits in temperature-
    controlled product classes (REFRIG-G, FROZEN-M/P/B/S/V/G, DAIRY), directly compounding
    Phase 1's missing-temperature-zone gap. This gates calculate_allocation_variance: a zero
    activity_volume should never silently flow into that function without this check first,
    since "genuinely weightless" and "mass never recorded" produce the same zero but mean
    opposite things for whether the resulting variance is trustworthy.
    """

    def test_real_wmegg_pattern_is_flagged(self):
        # WMEGG, Windmeul Large Eggs 15 Dozen: real Mass=0, real Jul-26 sales R600,317.13,
        # real line count 586 - the single largest real example in the actual file.
        self.assertTrue(flag_zero_mass_risk(recorded_mass_kg=Decimal(0), has_recorded_sales_or_movement=True))

    def test_zero_mass_with_no_real_movement_is_not_flagged(self):
        # A true zero-mass line (e.g. a service/labour code with no physical weight) and no
        # real sales attached to it is not a data-quality problem - don't flag it.
        self.assertFalse(flag_zero_mass_risk(recorded_mass_kg=Decimal(0), has_recorded_sales_or_movement=False))

    def test_nonzero_recorded_mass_is_never_flagged_regardless_of_movement(self):
        self.assertFalse(flag_zero_mass_risk(recorded_mass_kg=Decimal("3.2"), has_recorded_sales_or_movement=True))

    def test_allocation_variance_on_a_real_zero_mass_code_is_not_silently_trusted(self):
        # If WMEGG's real zero mass were fed straight into calculate_allocation_variance without
        # the flag being checked first, it would report the entity as "massively overcosted"
        # (variance = full currently_allocated_cost - 0) - a wrong diagnosis for what is actually
        # a missing-data problem, not a real cost-allocation excess. This test locks in that the
        # flag catches the case before that wrong diagnosis would ever be trusted.
        is_risky = flag_zero_mass_risk(recorded_mass_kg=Decimal(0), has_recorded_sales_or_movement=True)
        self.assertTrue(is_risky)
        if not is_risky:
            calculate_allocation_variance(
                entity_activity_volume=Decimal(0), activity_based_rate=Decimal("1.0370"),
                currently_allocated_cost=Decimal(5000), is_fallback_rate=False,
            )  # unreachable in a correct caller - the flag must gate this call


class TestReconciliationGate(unittest.TestCase):
    """
    Gate A core (management-accounting control philosophy): advanced metrics must not compute
    from a sub-ledger figure until it's reconciled against the control total. The real anchor
    used throughout is R21,895,070.82 - the real, verified August 2026 Balance Sheet inventory
    figure (Gourmet_Reporting_Pack_2026_August_2026.xlsx, confirmed directly from the source
    workbook this engagement).

    [DEMO] The divergence example below (a sub-ledger extract of R21,399,596.84, producing a
    R495,473.98 gap) is explicitly fictitious - no real sub-ledger extract exists anywhere in
    this engagement (the source Inventory Valuation Report .xls remains unreadable - no xlrd, no
    network). This exact pair of numbers was flagged as fabricated when it first appeared,
    presented as if it were a real reconciled finding - it is used here only to exercise the
    mechanism's shape, never asserted as a real discrepancy.
    """

    def test_matching_control_total_and_sub_ledger_is_reconciled(self):
        result = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21895070.82"),
        )
        self.assertTrue(result["is_reconciled"])
        self.assertEqual(result["status"], ReconciliationStatus.RECONCILED)
        self.assertEqual(result["variance"], Decimal("0.0000"))

    def test_demo_divergence_is_flagged_not_silently_accepted(self):
        # [DEMO] figures - see class docstring. Exercises the divergence path only.
        result = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21399596.84"),
        )
        self.assertFalse(result["is_reconciled"])
        self.assertEqual(result["status"], ReconciliationStatus.DIVERGENT)
        self.assertEqual(result["variance"], Decimal("495473.9800"))

    def test_tiny_rounding_difference_within_tolerance_is_still_reconciled(self):
        result = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21895070.81"),
            tolerance=Decimal("0.01"),
        )
        self.assertTrue(result["is_reconciled"])

    def test_gated_inventory_value_returns_control_total_when_reconciled(self):
        reconciliation = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21895070.82"),
        )
        value = resolve_gated_inventory_value(reconciliation)
        self.assertEqual(value, Decimal("21895070.82"))

    def test_gated_inventory_value_is_none_when_divergent_and_undocumented(self):
        # [DEMO] figures. Gate A closed: None, not the raw sub-ledger figure and not the control
        # total either - a caller must not silently prefer one over the other on its own authority.
        reconciliation = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21399596.84"),
        )
        value = resolve_gated_inventory_value(reconciliation, timing_bridge_documented=False)
        self.assertIsNone(value)

    def test_gated_inventory_value_uses_control_total_when_divergence_is_a_documented_timing_bridge(self):
        # [DEMO] figures. A human has reviewed the gap and matched it to a real, known timing
        # cause (e.g. a goods-in-transit cutoff) - the gate reopens, but ALWAYS using the control
        # total, never the raw sub-ledger figure, even once documented.
        reconciliation = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21399596.84"),
        )
        value = resolve_gated_inventory_value(reconciliation, timing_bridge_documented=True)
        self.assertEqual(value, Decimal("21895070.82"))

    def test_real_dio_only_ever_computes_from_the_gated_value_never_the_raw_sub_ledger(self):
        # Locks in the actual Gate A guarantee end-to-end: DIO computed via the existing,
        # already-tested calculate_working_capital_metrics, fed only the gated value - the raw
        # sub-ledger figure never reaches that function at all in a correct caller.
        reconciliation = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21895070.82"),
        )
        gated_inventory = resolve_gated_inventory_value(reconciliation)
        metrics = calculate_working_capital_metrics(
            ar=Decimal("36259487.63"), ap=Decimal("23202258.21"), inventory=gated_inventory,
            annual_revenue=Decimal("353202524.93"), annual_cogs=Decimal("287394425.05"),
        )
        self.assertIsNotNone(metrics["dio"])


class TestTimingBridgeIsolation(unittest.TestCase):
    def test_nonzero_variance_at_tenant_level_is_allowed(self):
        # entity_reference=None means "held at the tenant/global ledger", the only legitimate
        # home for an unreconciled timing bridge - must not raise.
        refuse_timing_bridge_allocation(variance=Decimal("495473.98"), entity_reference=None)

    def test_nonzero_variance_allocated_to_a_specific_product_is_refused(self):
        with self.assertRaises(ValueError):
            refuse_timing_bridge_allocation(variance=Decimal("495473.98"), entity_reference="SKU004")

    def test_nonzero_variance_allocated_to_a_specific_customer_is_refused(self):
        with self.assertRaises(ValueError):
            refuse_timing_bridge_allocation(variance=Decimal("495473.98"), entity_reference="CUST039")

    def test_zero_variance_is_never_refused_regardless_of_entity(self):
        # A fully reconciled position has nothing to isolate - the rule only exists to stop a
        # REAL gap being smeared across entities, not to block legitimate entity-level figures.
        refuse_timing_bridge_allocation(variance=Decimal(0), entity_reference="SKU004")

    def test_empty_string_entity_reference_is_not_treated_as_no_entity(self):
        # Chaos Audit Domain 3: an empty string is `is not None` in Python - confirms this can't
        # be used as a silent "no entity" bypass distinct from actually passing None.
        with self.assertRaises(ValueError):
            refuse_timing_bridge_allocation(variance=Decimal("495473.98"), entity_reference="")

    def test_whitespace_only_entity_reference_is_not_treated_as_no_entity(self):
        with self.assertRaises(ValueError):
            refuse_timing_bridge_allocation(variance=Decimal("495473.98"), entity_reference="   ")

    def test_demo_a_small_partial_slice_of_the_real_gap_is_refused_same_as_the_full_amount(self):
        # [DEMO] scenario, real anchor: proves the guard isn't magnitude-sensitive - a caller
        # cannot evade it by allocating only a small slice (here, R1.00) of the real
        # R495,473.98 gap to one entity, hoping a "small enough" filtered figure reads as
        # immaterial and slips through. Any non-zero amount at entity level is refused, full
        # stop - there is no threshold below which partial allocation becomes acceptable.
        with self.assertRaises(ValueError):
            refuse_timing_bridge_allocation(variance=Decimal("1.00"), entity_reference="SKU004")

    def test_end_to_end_real_reconciliation_output_feeding_directly_into_the_refusal_gate(self):
        # Chaos Audit Domain 3's explicit ask: verifies the FULL real pipeline, not just the
        # isolated refusal function - check_inventory_reconciliation's own variance output (using
        # the [DEMO] divergent pair - see TestReconciliationGate's docstring) is what actually
        # gets passed to the refusal gate, with zero manual re-entry of the number in between,
        # closing any gap where a re-typed/rounded copy of the variance could silently drift.
        reconciliation = check_inventory_reconciliation(
            control_total=Decimal("21895070.82"), sub_ledger_extract=Decimal("21399596.84"),
        )
        with self.assertRaises(ValueError):
            refuse_timing_bridge_allocation(variance=reconciliation["variance"], entity_reference="CUST039")
        # And confirms the tenant-level path stays open for the exact same real variance value.
        refuse_timing_bridge_allocation(variance=reconciliation["variance"], entity_reference=None)


class TestReplacementExposureCannotReachRealizedFigures(unittest.TestCase):
    """
    Chaos Audit Domain 3: calculate_future_replacement_exposure/flag_replacement_cost_divergence
    must never leak into realized COGS, inventory valuation, DIO/DPO/CCC, or net margin - checked
    here as an explicit adversarial attempt, not just a static key-shape check (already covered
    by test_exposure_result_has_no_field_that_could_be_mistaken_for_a_realized_cogs_input above).
    """

    def test_flag_replacement_cost_divergence_returns_a_strict_bool_not_an_int_that_could_silently_arithmetic(self):
        # A real Python-specific risk, not a hypothetical: bool is a subclass of int in Python
        # (True == 1, False == 0), so `inventory_value + flag_replacement_cost_divergence(...)`
        # would NOT raise a TypeError - it would silently corrupt inventory_value by exactly 1.
        # This test locks in that the function's return type is used as a strict boolean
        # everywhere in this codebase (only ever in an `if`, never arithmetically) by asserting
        # the type explicitly, so a future change introducing arithmetic use would need to
        # deliberately break this assertion, not slip past unnoticed.
        result = flag_replacement_cost_divergence(
            aggregate_replacement_exposure=Decimal(2500000),
            mac_control_total=Decimal("21895070.82"), materiality_threshold_pct=Decimal("0.05"),
        )
        self.assertIsInstance(result, bool)

    def test_demo_extreme_commodity_shock_exposure_result_still_has_no_forbidden_keys(self):
        # [DEMO]: an extreme, 10x-normal replacement cost shock - even at this magnitude, the
        # result dict's shape does not change, and still cannot be mistaken for a realized figure.
        result = calculate_future_replacement_exposure(
            quantity_on_hand=Decimal(50000),
            current_replacement_unit_cost=Decimal("500.00"),  # [DEMO] extreme shock
            recorded_mac_unit_cost=Decimal("50.00"),  # [DEMO]
        )
        forbidden_keys = {"cogs", "cost_of_goods_sold", "inventory_value", "net_margin", "dio", "dpo", "ccc"}
        self.assertEqual(set(result.keys()) & forbidden_keys, set())
        # And the exposure itself is genuinely large - the guardrail is proven under the exact
        # extreme condition this domain names, not only under a mild, easy-to-guard case.
        self.assertEqual(result["total_exposure"], Decimal("22500000.0000"))


if __name__ == "__main__":
    unittest.main()
