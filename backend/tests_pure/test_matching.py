"""Covers spec Section 39: exact SKU matching, fuzzy matching, similar-but-different rejection,
new products, discontinued products - the matching-pipeline slice of the required test list."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.matching.exact_matcher import verify_exact_match_for_route_log
from app.matching.route_log_validation import calculate_cost_per_drop, validate_route_log_plausibility
from app.matching.review import is_authoritative, requires_human_review
from app.matching.scorer import CandidateItem, MatchMethod, MatchStatus, find_best_match


class TestExactMatching(unittest.TestCase):
    def test_exact_sku_match_wins_over_similar_description(self):
        old = CandidateItem(key="old-1", supplier_sku="ABC123", barcode=None, description="Widget A")
        new_same_sku = CandidateItem(key="new-1", supplier_sku="ABC123", barcode=None, description="Widget A v2")
        new_similar_desc = CandidateItem(key="new-2", supplier_sku="XYZ999", barcode=None, description="Widget A")

        result = find_best_match(old, [new_similar_desc, new_same_sku])
        self.assertEqual(result.new_key, "new-1")
        self.assertEqual(result.method, MatchMethod.SKU)
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.status, MatchStatus.AUTO_MATCHED)
        self.assertTrue(is_authoritative(result.status))


class TestFuzzyMatching(unittest.TestCase):
    def test_reordered_pack_description_still_matches(self):
        # "COKE ZERO CAN 24 X 330ML" vs "Coke Zero 330ml x24" - spec Section 5's own example of
        # descriptions that should be recognised as potentially equivalent despite reordering.
        old = CandidateItem(key="old-1", supplier_sku=None, barcode=None,
                             description="COKE ZERO CAN 24 X 330ML")
        new = CandidateItem(key="new-1", supplier_sku=None, barcode=None,
                             description="Coke Zero 330ml x24")
        result = find_best_match(old, [new])
        self.assertEqual(result.method, MatchMethod.FUZZY)
        self.assertGreaterEqual(result.confidence, 0.60)
        self.assertTrue(requires_human_review(result.status) or result.status == MatchStatus.AUTO_MATCHED)

    def test_similar_but_different_product_is_rejected_from_auto_match(self):
        # The exact required test from spec Section 41: must NOT auto-match on description
        # similarity alone when the variant word conflicts.
        old = CandidateItem(key="old-1", supplier_sku=None, barcode=None,
                             description="Cheddar Cheese Mature 2kg")
        new = CandidateItem(key="new-1", supplier_sku=None, barcode=None,
                             description="Cheddar Cheese Mild 2kg")
        result = find_best_match(old, [new])
        self.assertNotEqual(result.status, MatchStatus.AUTO_MATCHED)
        self.assertFalse(is_authoritative(result.status))
        self.assertTrue(requires_human_review(result.status))


class TestNewAndDiscontinued(unittest.TestCase):
    def test_no_candidates_yields_no_candidate_status(self):
        old = CandidateItem(key="old-1", supplier_sku="Z1", barcode=None, description="Discontinued Item")
        result = find_best_match(old, [])
        self.assertEqual(result.status, MatchStatus.NO_CANDIDATE)
        self.assertIsNone(result.new_key)
        self.assertTrue(requires_human_review(result.status))


if __name__ == "__main__":
    unittest.main()


class TestRouteLogPlausibility(unittest.TestCase):
    """
    Chaos Audit Domain 2. verify_exact_match_for_route_log itself has no division at all (pure
    string comparison) - the real risk this domain names is a route-efficiency ratio with no
    zero-denominator guard, and no check that a route log's physical figures are even possible.
    Baseline figures are real (tem_daily_truck_revenue_sheet0.xlsx, Sheet2: CAA 127155, West
    Coast, 3 July 2026, 24 real drops, 686.435kg real weight, R36,686.08 real cost) - the SINGLE-
    TRIP figures, not 30_TRUCK_PROFITABILITY's monthly fleet total (94,284.424kg), which would be
    the wrong unit entirely for a single-trip plausibility check - using it here would itself be
    exactly the kind of boundary-anomaly bug this domain exists to catch. vehicle_max_payload_kg
    is [DEMO] throughout - no real rated vehicle capacity is documented anywhere in this
    engagement.
    """

    def test_real_west_coast_single_trip_figures_are_plausible(self):
        violations = validate_route_log_plausibility(
            distance_km=Decimal("45.2"),  # [DEMO] - no real distance figure recorded for this trip
            stop_count=24, total_drop_weight_kg=Decimal("686.435"),
            vehicle_max_payload_kg=Decimal("8000"),  # [DEMO] assumed capacity, not a documented real spec
        )
        self.assertEqual(violations, [])

    def test_zero_distance_with_real_drop_count_is_a_physical_impossibility(self):
        # The exact scenario named in this domain: zero km travelled but real, multiple drops -
        # cannot happen physically, must be flagged, never silently accepted as "efficient."
        violations = validate_route_log_plausibility(
            distance_km=Decimal("0"), stop_count=24, total_drop_weight_kg=Decimal("686.435"),
            vehicle_max_payload_kg=Decimal("8000"),
        )
        self.assertIn("zero distance_km with stop_count > 0 - physically impossible", violations)

    def test_zero_distance_with_zero_stops_is_plausible_not_flagged(self):
        # A genuinely idle vehicle (no trip logged) is not a plausibility violation - zero and
        # zero together are consistent with each other, unlike zero km with real drops.
        violations = validate_route_log_plausibility(
            distance_km=Decimal("0"), stop_count=0, total_drop_weight_kg=Decimal("0"),
            vehicle_max_payload_kg=Decimal("8000"),
        )
        self.assertEqual(violations, [])

    def test_demo_drop_weight_exceeding_vehicle_capacity_is_a_data_clipping_flag(self):
        # [DEMO]: 94,284.424kg is the REAL number from 30_TRUCK_PROFITABILITY's monthly fleet
        # total for this same vehicle - deliberately reused here as an adversarial input to prove
        # exactly the unit-confusion failure mode this function exists to catch (a monthly
        # aggregate fed into a single-trip capacity check, a real and plausible data-pipeline bug).
        violations = validate_route_log_plausibility(
            distance_km=Decimal("45.2"), stop_count=24, total_drop_weight_kg=Decimal("94284.424"),
            vehicle_max_payload_kg=Decimal("8000"),
        )
        self.assertTrue(any("exceeds vehicle_max_payload_kg" in v for v in violations))

    def test_negative_distance_or_stop_count_is_always_flagged(self):
        violations = validate_route_log_plausibility(
            distance_km=Decimal("-10"), stop_count=-1, total_drop_weight_kg=Decimal("100"),
            vehicle_max_payload_kg=Decimal("8000"),
        )
        self.assertEqual(len(violations), 2)


class TestCostPerDropDivisionSafety(unittest.TestCase):
    def test_real_west_coast_cost_per_drop(self):
        # Real R36,686.08 cost across real 24 drops.
        result = calculate_cost_per_drop(total_route_cost=Decimal("36686.08"), stop_count=24)
        self.assertEqual(result, Decimal("1528.5867"))

    def test_zero_stop_count_returns_none_not_a_zero_division_error(self):
        # A route log with real cost but zero drops is itself a plausibility violation (see
        # TestRouteLogPlausibility above) - this function refuses to mask that with a crash OR a
        # fabricated per-drop figure; None either way.
        result = calculate_cost_per_drop(total_route_cost=Decimal("36686.08"), stop_count=0)
        self.assertIsNone(result)

    def test_negative_stop_count_also_returns_none_not_a_negative_cost_per_drop(self):
        result = calculate_cost_per_drop(total_route_cost=Decimal("36686.08"), stop_count=-1)
        self.assertIsNone(result)


class TestExactMatchVerificationForRouteLogs(unittest.TestCase):
    """
    Gate B structural guardrail: deliberately NOT routed through find_best_match/scorer.py above
    - that fuzzy-matching machinery is correct for supplier/SKU deduplication (human-reviewed,
    not on the direct path to a booked cost figure). A transport route log feeding a cost pool
    has no review step, so it gets its own, strictly separate, similarity-free verification path.
    """

    def test_exact_match_on_registration_and_route_reference_passes(self):
        self.assertTrue(verify_exact_match_for_route_log(
            logged_vehicle_registration="CAA 127155", source_system_vehicle_registration="CAA 127155",
            logged_route_reference="WEST-COAST-15110", source_system_route_reference="WEST-COAST-15110",
        ))

    def test_case_and_whitespace_normalization_is_not_fuzzy_matching(self):
        # Real-world data-entry variance (trailing space, inconsistent casing) is not the same
        # risk as similarity scoring - normalizing this is still strict equality underneath.
        self.assertTrue(verify_exact_match_for_route_log(
            logged_vehicle_registration=" caa 127155 ", source_system_vehicle_registration="CAA 127155",
            logged_route_reference="west-coast-15110", source_system_route_reference="WEST-COAST-15110",
        ))

    def test_single_character_difference_in_registration_is_rejected_not_scored(self):
        # The exact failure mode this rule exists to prevent: find_best_match above would likely
        # score this as a high-confidence fuzzy match (one character off) - this function has no
        # concept of "close enough" at all, so it's rejected outright, same as a wholly different value.
        self.assertFalse(verify_exact_match_for_route_log(
            logged_vehicle_registration="CAA 127155", source_system_vehicle_registration="CAA 127156",
            logged_route_reference="WEST-COAST-15110", source_system_route_reference="WEST-COAST-15110",
        ))

    def test_matching_registration_but_mismatched_route_reference_is_rejected(self):
        # Both fields must match independently - a correct vehicle on the wrong route is a wrong
        # record, not a partial match worth accepting.
        self.assertFalse(verify_exact_match_for_route_log(
            logged_vehicle_registration="CAA 127155", source_system_vehicle_registration="CAA 127155",
            logged_route_reference="WEST-COAST-15110", source_system_route_reference="CAMPS-BAY-15111",
        ))
