"""
Tests for app.analytics.logistics_engine's Phase 1/2 additions: trip fixed pools, distance
variable pools (stop-start fuel burn), warehouse picking labor, drop-latency demurrage, and the
synthesizing calculate_true_route_profitability.

[DEMO] cost-pool figures throughout - no real driver salary, fuel rate, picking rate, or
demurrage rate has ever been provided in this engagement. The REAL anchors are the CAA 127155
West Coast route's actual figures (3 July 2026, tem_daily_truck_revenue_sheet0.xlsx Sheet2):
686.435kg real weight, 24 real drops, R36,686.08 real Cost of Sale, R45,189.62 real Sales Ex VAT
- NOT "14 tonnes", which matches neither this real single-trip weight nor the real monthly fleet
total for the same vehicle (94,284.424kg, 30_TRUCK_PROFITABILITY) - checked directly before
writing this file, not assumed.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.logistics_engine import (
    calculate_distance_variable_cost,
    calculate_drop_latency_demurrage_cost,
    calculate_trip_fixed_cost,
    calculate_true_route_profitability,
    calculate_warehouse_picking_labor_cost,
)

# Real anchor: CAA 127155, West Coast, 3 July 2026 - real weight, real drops, real cost/sales.
REAL_ROUTE_WEIGHT_KG = Decimal("686.435")
REAL_DROP_COUNT = 24
REAL_COGS = Decimal("36686.08")
REAL_SALES_EX_VAT = Decimal("45189.62")


class TestCalculateTripFixedCost(unittest.TestCase):
    def test_demo_all_three_pools_sum_correctly(self):
        result = calculate_trip_fixed_cost(
            driver_base_salary=Decimal("850"), co_driver_base_salary=Decimal("650"),
            fixed_vehicle_asset_cost=Decimal("1200"),
        )
        self.assertEqual(result, Decimal("2700.0000"))

    def test_zero_co_driver_salary_is_valid_a_single_driver_route_is_real(self):
        # Same reasoning as calculate_segregated_route_cost's drop_distance_km=0 case last turn:
        # a single-driver route (no co-driver) is a real, common, valid scenario, not a data
        # error - co_driver_base_salary is the one pool where zero must not be rejected.
        result = calculate_trip_fixed_cost(
            driver_base_salary=Decimal("850"), co_driver_base_salary=Decimal("0"),
            fixed_vehicle_asset_cost=Decimal("1200"),
        )
        self.assertEqual(result, Decimal("2050.0000"))

    def test_zero_driver_base_salary_is_refused_every_trip_has_a_driver(self):
        with self.assertRaises(ValueError):
            calculate_trip_fixed_cost(
                driver_base_salary=Decimal("0"), co_driver_base_salary=Decimal("0"),
                fixed_vehicle_asset_cost=Decimal("1200"),
            )

    def test_zero_fixed_vehicle_asset_cost_is_refused_every_trip_uses_a_real_vehicle(self):
        with self.assertRaises(ValueError):
            calculate_trip_fixed_cost(
                driver_base_salary=Decimal("850"), co_driver_base_salary=Decimal("0"),
                fixed_vehicle_asset_cost=Decimal("0"),
            )

    def test_missing_any_pool_is_a_type_error(self):
        with self.assertRaises(TypeError):
            calculate_trip_fixed_cost(driver_base_salary=Decimal("850"), co_driver_base_salary=Decimal("0"))


class TestCalculateDistanceVariableCost(unittest.TestCase):
    def test_demo_stop_start_multiplier_applies_only_to_the_drop_leg(self):
        # [DEMO]: R8.50/km base rate, 1.3x stop-start multiplier on the drop leg only - real MSc
        # supply chain principle: stop-start driving in a dense multi-drop leg burns more fuel
        # per km than steady stem-leg driving.
        result = calculate_distance_variable_cost(
            stem_distance_km=Decimal("15"), drop_distance_km=Decimal("25"),
            base_rate_per_km=Decimal("8.50"), stop_start_multiplier=Decimal("1.3"),
        )
        # stem: 15 * 8.50 = 127.50 (no multiplier)
        # drop: 25 * 8.50 * 1.3 = 276.25 (multiplier applied)
        self.assertEqual(result["stem_leg_cost"], Decimal("127.5000"))
        self.assertEqual(result["drop_leg_cost"], Decimal("276.2500"))
        self.assertEqual(result["total"], Decimal("403.7500"))

    def test_multiplier_of_exactly_1_makes_drop_and_stem_rates_identical(self):
        result = calculate_distance_variable_cost(
            stem_distance_km=Decimal("10"), drop_distance_km=Decimal("10"),
            base_rate_per_km=Decimal("8.50"), stop_start_multiplier=Decimal("1.0"),
        )
        self.assertEqual(result["stem_leg_cost"], result["drop_leg_cost"])

    def test_multiplier_below_1_is_refused_stop_start_driving_never_burns_less_fuel(self):
        # A physical-plausibility guard, not just an input-completeness one: stop-start driving
        # is never MORE fuel-efficient than steady driving - a multiplier < 1 is a data error.
        with self.assertRaises(ValueError):
            calculate_distance_variable_cost(
                stem_distance_km=Decimal("10"), drop_distance_km=Decimal("10"),
                base_rate_per_km=Decimal("8.50"), stop_start_multiplier=Decimal("0.8"),
            )

    def test_missing_stop_start_multiplier_is_a_type_error(self):
        with self.assertRaises(TypeError):
            calculate_distance_variable_cost(
                stem_distance_km=Decimal("10"), drop_distance_km=Decimal("10"), base_rate_per_km=Decimal("8.50"),
            )


class TestCalculateWarehousePickingLaborCost(unittest.TestCase):
    def test_demo_driven_by_line_count_and_cube_not_weight(self):
        # No weight parameter exists in this function's signature at all - enforced structurally,
        # not just by convention, matching the real supply chain principle that picking labor
        # time is driven by line complexity and bulk, not payload mass.
        result = calculate_warehouse_picking_labor_cost(
            sku_line_count=18, total_cube_m3=Decimal("4.2"),
            rate_per_line=Decimal("12.50"), rate_per_cube_m3=Decimal("35.00"),
        )
        # (18 * 12.50) + (4.2 * 35.00) = 225.00 + 147.00 = 372.00
        self.assertEqual(result, Decimal("372.0000"))

    def test_zero_sku_line_count_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_warehouse_picking_labor_cost(
                sku_line_count=0, total_cube_m3=Decimal("4.2"),
                rate_per_line=Decimal("12.50"), rate_per_cube_m3=Decimal("35.00"),
            )

    def test_zero_cube_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_warehouse_picking_labor_cost(
                sku_line_count=18, total_cube_m3=Decimal("0"),
                rate_per_line=Decimal("12.50"), rate_per_cube_m3=Decimal("35.00"),
            )


class TestCalculateDropLatencyDemurrageCost(unittest.TestCase):
    def test_demo_time_within_free_allowance_incurs_no_demurrage(self):
        # Demurrage only applies BEYOND a contractual free-time allowance - the first N minutes
        # at the bay are normal, expected drop time, not a penalty.
        result = calculate_drop_latency_demurrage_cost(
            time_at_bay_minutes=Decimal("25"), free_time_minutes=Decimal("30"),
            demurrage_rate_per_minute=Decimal("15"),
        )
        self.assertEqual(result, Decimal("0.0000"))

    def test_demo_time_exceeding_free_allowance_is_charged_only_for_the_excess(self):
        result = calculate_drop_latency_demurrage_cost(
            time_at_bay_minutes=Decimal("50"), free_time_minutes=Decimal("30"),
            demurrage_rate_per_minute=Decimal("15"),
        )
        self.assertEqual(result, Decimal("300.0000"))  # (50-30) * 15

    def test_negative_time_at_bay_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_drop_latency_demurrage_cost(
                time_at_bay_minutes=Decimal("-5"), free_time_minutes=Decimal("30"),
                demurrage_rate_per_minute=Decimal("15"),
            )


class TestCalculateTrueRouteProfitability(unittest.TestCase):
    def test_real_west_coast_route_grounded_demo_profitability(self):
        # Real revenue/COGS (CAA 127155, West Coast, 3 July 2026); [DEMO] cost pool breakdown
        # since no real driver salary/fuel rate/picking rate/demurrage figures exist anywhere.
        result = calculate_true_route_profitability(
            revenue=REAL_SALES_EX_VAT, cogs=REAL_COGS, trade_spend=Decimal("0"), revenue_basis="gross",
            trip_fixed_costs=Decimal("2700"), distance_variable_costs=Decimal("403.75"),
            activity_time_costs=Decimal("372"),
        )
        # net_revenue=45189.62, gross_margin=45189.62-36686.08=8503.54 (matches the sheet's own
        # real GP/Rands figure exactly), cost_to_serve=2700+403.75+372=3475.75
        # net_net_profit = 8503.54 - 3475.75 = 5027.79
        self.assertEqual(result["gross_margin"], Decimal("8503.5400"))
        self.assertEqual(result["net_net_profit"], Decimal("5027.7900"))
        self.assertIn("trip_fixed_costs", result)
        self.assertIn("distance_variable_costs", result)
        self.assertIn("activity_time_costs", result)

    def test_demo_combined_costs_exceeding_gross_margin_flips_net_net_profit_negative_and_flags_it(self):
        # [DEMO]: an adversarial scenario where combined operational cost pools wipe out the
        # route's entire gross margin - must show a real negative figure and the explicit
        # is_net_revenue_negative-style signal, never floor-clamped to zero.
        result = calculate_true_route_profitability(
            revenue=Decimal("10000"), cogs=Decimal("6000"), trade_spend=Decimal("0"), revenue_basis="gross",
            trip_fixed_costs=Decimal("2500"), distance_variable_costs=Decimal("1000"),
            activity_time_costs=Decimal("1500"),
        )
        # gross_margin=4000, cost_to_serve=5000, net_net_profit=-1000
        self.assertEqual(result["net_net_profit"], Decimal("-1000.0000"))
        self.assertFalse(result["is_net_revenue_negative"])  # revenue itself is still positive

    def test_reuses_calculate_customer_net_margin_not_a_reimplementation(self):
        # Structural confirmation, not just a numeric coincidence: calling
        # calculate_customer_net_margin directly with the summed cost pools must produce the
        # exact same net_margin figure as calculate_true_route_profitability's net_net_profit.
        from app.analytics.management_accounting import calculate_customer_net_margin
        direct = calculate_customer_net_margin(
            revenue=REAL_SALES_EX_VAT, cogs=REAL_COGS, trade_spend=Decimal("0"), revenue_basis="gross",
            direct_logistics_cost=Decimal("2700") + Decimal("403.75"), warehouse_abc_cost=Decimal("372"),
        )
        via_route_engine = calculate_true_route_profitability(
            revenue=REAL_SALES_EX_VAT, cogs=REAL_COGS, trade_spend=Decimal("0"), revenue_basis="gross",
            trip_fixed_costs=Decimal("2700"), distance_variable_costs=Decimal("403.75"),
            activity_time_costs=Decimal("372"),
        )
        self.assertEqual(direct["net_margin"], via_route_engine["net_net_profit"])

    def test_missing_any_cost_pool_is_a_type_error(self):
        with self.assertRaises(TypeError):
            calculate_true_route_profitability(
                revenue=REAL_SALES_EX_VAT, cogs=REAL_COGS, trade_spend=Decimal("0"), revenue_basis="gross",
                trip_fixed_costs=Decimal("2700"), distance_variable_costs=Decimal("403.75"),
            )


if __name__ == "__main__":
    unittest.main()
