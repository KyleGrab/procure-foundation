"""
Tests for app.analytics.logistics_engine.calculate_segregated_route_cost.

[DEMO] stem/drop/return split (15km/25km/15km) - no real distance breakdown exists anywhere in
this engagement (the real Daily Truck Revenue sheet records weight/cost/sales per trip, never a
stem-vs-drop distance split). The REAL anchor is the R36,686.08 total trip cost pool - the actual
CAA 127155 West Coast route figure used throughout this engagement.

Two deliberate departures from the literal Phase request, both verified before being built, not
asserted:
1. drop_distance_km >= 0, not > 0. A route with exactly one delivery stop has zero km BETWEEN
   drops by definition - that's the correct value for a real, common scenario (a single large DC
   drop), not a data error. Rejecting it would make this function unable to cost a legitimate
   route shape. stem_distance_km and return_distance_km remain strictly > 0 - a delivery trip
   that never leaves or never returns the depot isn't physically sensible.
2. The rate (total_trip_cost_pool / total_distance) is carried at full, unrounded precision into
   BOTH the fixed and variable calculations - rounding it first, then multiplying, was checked
   directly and found to leak exactly R0.002 out of conservation on the real R36,686.08 anchor
   (verified independently before writing this module). Only the two final outputs are rounded.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.logistics_engine import calculate_segregated_route_cost

# [DEMO] split, REAL total_trip_cost_pool (CAA 127155, West Coast, confirmed real this engagement)
DEMO_STEM_KM = Decimal("15")
DEMO_DROP_KM = Decimal("25")
DEMO_RETURN_KM = Decimal("15")
REAL_TRIP_COST_POOL = Decimal("36686.08")


class TestCalculateSegregatedRouteCost(unittest.TestCase):
    def test_real_west_coast_trip_cost_pool_with_demo_distance_split_conserves_exactly(self):
        # Independently verified before this test was written: fixed + variable must sum to
        # EXACTLY the real R36,686.08 - not "close enough within rounding."
        result = calculate_segregated_route_cost(
            stem_distance_km=DEMO_STEM_KM, drop_distance_km=DEMO_DROP_KM,
            return_distance_km=DEMO_RETURN_KM, total_trip_cost_pool=REAL_TRIP_COST_POOL,
        )
        self.assertEqual(result["fixed_stem_cost"], Decimal("20010.5891"))
        self.assertEqual(result["variable_drop_cost"], Decimal("16675.4909"))
        self.assertEqual(result["fixed_stem_cost"] + result["variable_drop_cost"], REAL_TRIP_COST_POOL)

    def test_zero_drop_km_is_a_valid_single_drop_route_not_an_error(self):
        # The corrected version of what the original request's test (a) was reaching for: a
        # route with high stem-km and genuinely zero drop-km (one delivery stop) is real and
        # must compute successfully, not raise. All real cost lands in the fixed stem allocation.
        result = calculate_segregated_route_cost(
            stem_distance_km=Decimal("40"), drop_distance_km=Decimal("0"),
            return_distance_km=Decimal("40"), total_trip_cost_pool=REAL_TRIP_COST_POOL,
        )
        self.assertEqual(result["variable_drop_cost"], Decimal("0.0000"))
        self.assertEqual(result["fixed_stem_cost"], REAL_TRIP_COST_POOL)

    def test_negative_drop_km_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_segregated_route_cost(
                stem_distance_km=DEMO_STEM_KM, drop_distance_km=Decimal("-5"),
                return_distance_km=DEMO_RETURN_KM, total_trip_cost_pool=REAL_TRIP_COST_POOL,
            )

    def test_zero_stem_km_is_refused_a_delivery_trip_must_leave_the_depot(self):
        with self.assertRaises(ValueError):
            calculate_segregated_route_cost(
                stem_distance_km=Decimal("0"), drop_distance_km=DEMO_DROP_KM,
                return_distance_km=DEMO_RETURN_KM, total_trip_cost_pool=REAL_TRIP_COST_POOL,
            )

    def test_zero_return_km_is_refused_a_delivery_trip_must_return_to_the_depot(self):
        with self.assertRaises(ValueError):
            calculate_segregated_route_cost(
                stem_distance_km=DEMO_STEM_KM, drop_distance_km=DEMO_DROP_KM,
                return_distance_km=Decimal("0"), total_trip_cost_pool=REAL_TRIP_COST_POOL,
            )

    def test_zero_or_negative_cost_pool_is_refused(self):
        with self.assertRaises(ValueError):
            calculate_segregated_route_cost(
                stem_distance_km=DEMO_STEM_KM, drop_distance_km=DEMO_DROP_KM,
                return_distance_km=DEMO_RETURN_KM, total_trip_cost_pool=Decimal("0"),
            )

    def test_missing_any_parameter_is_a_type_error_not_a_fabricated_zero(self):
        with self.assertRaises(TypeError):
            calculate_segregated_route_cost(
                stem_distance_km=DEMO_STEM_KM, drop_distance_km=DEMO_DROP_KM,
                return_distance_km=DEMO_RETURN_KM,
            )

    def test_total_distance_zero_is_structurally_impossible_given_stem_and_return_are_required_positive(self):
        # Not a separate runtime check - a direct consequence of stem>0 and return>0 already
        # being enforced, so total_distance = stem+drop+return is always >= stem+return > 0.
        # This test locks in that the precondition validation genuinely prevents the
        # zero-denominator case from ever being reachable, not just handles it gracefully if hit.
        with self.assertRaises(ValueError):
            calculate_segregated_route_cost(
                stem_distance_km=Decimal("0"), drop_distance_km=Decimal("0"),
                return_distance_km=Decimal("0"), total_trip_cost_pool=REAL_TRIP_COST_POOL,
            )

    def test_increasing_drop_km_with_stem_and_return_fixed_still_conserves_exactly(self):
        # The corrected version of what the original request's test (b) was reaching for: NOT
        # "fixed stem cost stays constant as drop-km grows" (verified false - see module
        # docstring point 2, the shared rate genuinely changes as total distance changes), but
        # the real, provable invariant - conservation holds at every drop-km value, and the
        # stem/return INPUT figures themselves are never mutated by the calculation.
        for drop_km in (Decimal("10"), Decimal("25"), Decimal("60"), Decimal("100")):
            with self.subTest(drop_km=drop_km):
                result = calculate_segregated_route_cost(
                    stem_distance_km=DEMO_STEM_KM, drop_distance_km=drop_km,
                    return_distance_km=DEMO_RETURN_KM, total_trip_cost_pool=REAL_TRIP_COST_POOL,
                )
                self.assertEqual(
                    result["fixed_stem_cost"] + result["variable_drop_cost"], REAL_TRIP_COST_POOL,
                )

    def test_fixed_stem_cost_share_shrinks_as_drop_km_grows_a_real_property_not_an_assumed_one(self):
        # Directly proves the point made in the module docstring rather than leaving it as an
        # unverified claim: because cost_per_km is shared across the whole trip, more drop-km
        # dilutes the per-km rate applied to the FIXED stem+return distance too - fixed_stem_cost
        # genuinely decreases in Rand terms as drop_km grows, even though stem/return themselves
        # never change.
        low_drop = calculate_segregated_route_cost(
            stem_distance_km=DEMO_STEM_KM, drop_distance_km=Decimal("10"),
            return_distance_km=DEMO_RETURN_KM, total_trip_cost_pool=REAL_TRIP_COST_POOL,
        )
        high_drop = calculate_segregated_route_cost(
            stem_distance_km=DEMO_STEM_KM, drop_distance_km=Decimal("100"),
            return_distance_km=DEMO_RETURN_KM, total_trip_cost_pool=REAL_TRIP_COST_POOL,
        )
        self.assertGreater(low_drop["fixed_stem_cost"], high_drop["fixed_stem_cost"])


if __name__ == "__main__":
    unittest.main()
