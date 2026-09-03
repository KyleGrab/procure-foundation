"""
Multi-Tier Transport Route Cost Engine - structurally separates the fixed stem/return leg from
the variable inter-drop leg, closing the flat-distance conflation already proven (Phase 1,
30_TRUCK_PROFITABILITY) to produce a real, quantified R288,373/month cross-subsidy across the
real 17-truck fleet. Pure Decimal logic - no DB, no framework, §2.1.

Two deliberate departures from how this was originally specified, both verified numerically
before being built (see tests_pure/test_logistics_engine.py's module docstring for the full
reasoning): drop_distance_km permits zero (a real, valid single-drop route, not a data error),
and the per-km rate is carried at full unrounded precision into both allocations rather than
rounded before multiplying, since rounding it first was checked and found to leak real currency
out of conservation.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from app.analytics.management_accounting import calculate_customer_net_margin

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def calculate_segregated_route_cost(
    stem_distance_km: Decimal, drop_distance_km: Decimal, return_distance_km: Decimal,
    total_trip_cost_pool: Decimal,
) -> dict:
    """
    Fixed Stem Cost = (stem_distance_km + return_distance_km) * cost_per_km
    Variable Drop Cost = drop_distance_km * cost_per_km
    where cost_per_km = total_trip_cost_pool / total_distance, carried at full precision (never
    rounded before the multiplication - rounding it first was verified to leak currency out of
    conservation on the real R36,686.08 West Coast anchor). Fixed + Variable always sums to
    exactly total_trip_cost_pool - checked directly in tests_pure, not assumed from the formula
    shape alone.

    All four parameters are required, no defaults anywhere - omitting any one is a TypeError, not
    a fabricated zero.

    stem_distance_km, return_distance_km: must be strictly positive (ValueError otherwise) - a
    delivery trip that never leaves or never returns the depot isn't physically sensible. This
    also makes total_distance == 0 structurally impossible once these two are validated
    (total_distance = stem + drop + return >= stem + return > 0), so no separate zero-denominator
    branch exists - prevented at the precondition, not caught after the fact.

    drop_distance_km: must be non-negative (ValueError only on negative) - zero is a real, valid
    single-drop route (one delivery stop has, by definition, no distance between drops), not a
    data-quality violation. A caller needing to detect the DIFFERENT real violation - zero
    drop-km reported alongside a route that genuinely has multiple stops - needs a stop count,
    which isn't one of this function's four parameters; that check belongs with
    app.matching.route_log_validation.validate_route_log_plausibility, which already has one.

    total_trip_cost_pool: must be strictly positive (ValueError otherwise). This function is
    scoped to delivery trips - a real "Collection" trip type (stock collected from the warehouse,
    genuinely zero delivery fees/cost, confirmed real earlier in this engagement) has no stem/
    drop/return legs in this sense at all and must be routed through separate logic entirely, not
    forced through this function with a fabricated zero cost pool.
    """
    if stem_distance_km <= 0:
        raise ValueError(f"stem_distance_km must be positive, got {stem_distance_km} - a delivery trip must leave the depot")
    if return_distance_km <= 0:
        raise ValueError(f"return_distance_km must be positive, got {return_distance_km} - a delivery trip must return to the depot")
    if drop_distance_km < 0:
        raise ValueError(f"drop_distance_km cannot be negative, got {drop_distance_km}")
    if total_trip_cost_pool <= 0:
        raise ValueError(
            f"total_trip_cost_pool must be positive, got {total_trip_cost_pool} - if this is a "
            f"Collection trip (genuinely zero cost), route it through separate logic, not this function"
        )

    total_distance = stem_distance_km + drop_distance_km + return_distance_km
    cost_per_km = total_trip_cost_pool / total_distance  # unrounded - see module docstring

    fixed_stem_cost = round_currency((stem_distance_km + return_distance_km) * cost_per_km)
    variable_drop_cost = round_currency(drop_distance_km * cost_per_km)

    return {
        "fixed_stem_cost": fixed_stem_cost,
        "variable_drop_cost": variable_drop_cost,
        "total_distance_km": total_distance,
    }


# ---------------------------------------------------------------------------
# Multidimensional Cost-to-Serve pools (Phase 1) + true route profitability (Phase 2)
# ---------------------------------------------------------------------------

def calculate_trip_fixed_cost(
    driver_base_salary: Decimal, co_driver_base_salary: Decimal, fixed_vehicle_asset_cost: Decimal,
) -> Decimal:
    """
    Flat, indivisible per-trip cost - driver_base_salary and fixed_vehicle_asset_cost must be
    strictly positive (every real trip has a driver and uses a real vehicle). co_driver_base_salary
    is the one pool permitted to be zero, same reasoning as calculate_segregated_route_cost's
    drop_distance_km=0 last turn: a single-driver route (no co-driver) is a real, common, valid
    scenario, not a data error - the only pool here where zero must NOT be rejected.
    """
    if driver_base_salary <= 0:
        raise ValueError(f"driver_base_salary must be positive, got {driver_base_salary} - every trip has a driver")
    if co_driver_base_salary < 0:
        raise ValueError(f"co_driver_base_salary cannot be negative, got {co_driver_base_salary}")
    if fixed_vehicle_asset_cost <= 0:
        raise ValueError(f"fixed_vehicle_asset_cost must be positive, got {fixed_vehicle_asset_cost} - every trip uses a real vehicle")
    return round_currency(driver_base_salary + co_driver_base_salary + fixed_vehicle_asset_cost)


def calculate_distance_variable_cost(
    stem_distance_km: Decimal, drop_distance_km: Decimal, base_rate_per_km: Decimal, stop_start_multiplier: Decimal,
) -> dict:
    """
    Diesel/wear-and-tear cost built up from first principles (distance x rate), not allocated
    from an already-known total the way calculate_segregated_route_cost is - a genuinely
    different, complementary calculation, not a duplicate of that function's purpose.

    stop_start_multiplier applies ONLY to the drop leg - real MSc supply chain principle: dense,
    stop-start multi-drop driving burns meaningfully more fuel per km than steady stem-leg
    driving. Must be >= 1 (ValueError otherwise): stop-start driving is never MORE fuel-efficient
    than steady driving - a multiplier below 1 is a physical-plausibility violation, not just a
    missing input.
    """
    if stem_distance_km < 0 or drop_distance_km < 0:
        raise ValueError("stem_distance_km and drop_distance_km cannot be negative")
    if base_rate_per_km <= 0:
        raise ValueError(f"base_rate_per_km must be positive, got {base_rate_per_km}")
    if stop_start_multiplier < 1:
        raise ValueError(
            f"stop_start_multiplier must be >= 1, got {stop_start_multiplier} - stop-start "
            f"driving is never more fuel-efficient than steady driving"
        )
    stem_leg_cost = round_currency(stem_distance_km * base_rate_per_km)
    drop_leg_cost = round_currency(drop_distance_km * base_rate_per_km * stop_start_multiplier)
    return {"stem_leg_cost": stem_leg_cost, "drop_leg_cost": drop_leg_cost, "total": round_currency(stem_leg_cost + drop_leg_cost)}


def calculate_warehouse_picking_labor_cost(
    sku_line_count: int, total_cube_m3: Decimal, rate_per_line: Decimal, rate_per_cube_m3: Decimal,
) -> Decimal:
    """
    Driven by SKU line complexity and volumetric footprint - NOT payload weight, which has no
    parameter here at all (enforced structurally, not just by convention). Real supply chain
    principle: picking labor time scales with how many distinct lines and how bulky a pick is,
    not how heavy it is - a light but bulky, many-SKU order takes meaningfully longer to pick
    than a heavy but simple single-SKU order.
    """
    if sku_line_count <= 0:
        raise ValueError(f"sku_line_count must be positive, got {sku_line_count}")
    if total_cube_m3 <= 0:
        raise ValueError(f"total_cube_m3 must be positive, got {total_cube_m3}")
    return round_currency(Decimal(sku_line_count) * rate_per_line + total_cube_m3 * rate_per_cube_m3)


def calculate_drop_latency_demurrage_cost(
    time_at_bay_minutes: Decimal, free_time_minutes: Decimal, demurrage_rate_per_minute: Decimal,
) -> Decimal:
    """
    Demurrage applies only BEYOND the contractual free-time allowance - the first
    free_time_minutes at the loading bay are normal, expected drop time, not a penalty. Only the
    excess is charged, never the full dwell time.
    """
    if time_at_bay_minutes < 0:
        raise ValueError(f"time_at_bay_minutes cannot be negative, got {time_at_bay_minutes}")
    if free_time_minutes < 0:
        raise ValueError(f"free_time_minutes cannot be negative, got {free_time_minutes}")
    excess_minutes = max(Decimal("0"), time_at_bay_minutes - free_time_minutes)
    return round_currency(excess_minutes * demurrage_rate_per_minute)


def calculate_true_route_profitability(
    revenue: Decimal, cogs: Decimal, trade_spend: Decimal, revenue_basis: str,
    trip_fixed_costs: Decimal, distance_variable_costs: Decimal, activity_time_costs: Decimal,
) -> dict:
    """
    Net Net Profit = Net Revenue - Realized COGS - (Trip Fixed + Distance Variable + Activity
    Time). Reuses app.analytics.management_accounting.calculate_customer_net_margin directly for
    this arithmetic rather than reimplementing it - trip_fixed_costs + distance_variable_costs
    map to direct_logistics_cost ("getting the truck there"), activity_time_costs maps to
    warehouse_abc_cost (its existing, real intent: warehouse/activity-driven cost) - which means
    this function automatically inherits that function's already-proven, already-tested
    revenue_basis double-counting guard, never-floor-clamp behavior, and is_net_revenue_negative
    flag, rather than re-deriving any of them a third time. Confirmed identical to a direct call
    in tests_pure, not assumed from the mapping alone.

    All three cost pool totals are required, no defaults - omitting any is a TypeError.
    net_net_profit is calculate_customer_net_margin's own net_margin field, renamed in this
    function's result for this domain's own vocabulary - the underlying number is identical.
    """
    margin_result = calculate_customer_net_margin(
        revenue=revenue, cogs=cogs, trade_spend=trade_spend, revenue_basis=revenue_basis,
        direct_logistics_cost=trip_fixed_costs + distance_variable_costs, warehouse_abc_cost=activity_time_costs,
    )
    return {
        "net_revenue": margin_result["net_revenue"], "gross_margin": margin_result["gross_margin"],
        "trip_fixed_costs": round_currency(trip_fixed_costs),
        "distance_variable_costs": round_currency(distance_variable_costs),
        "activity_time_costs": round_currency(activity_time_costs),
        "net_net_profit": margin_result["net_margin"],
        "is_net_revenue_negative": margin_result["is_net_revenue_negative"],
    }
