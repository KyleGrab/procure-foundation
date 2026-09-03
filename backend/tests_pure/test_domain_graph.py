"""
Tests for app/analytics/domain_graph.py (Supplier Consolidation Graph, Candidate A). Written
before the implementation, per this turn's test-first sequence. Pure - no DB, no FastAPI - same
constraint every analytics module in this codebase already follows (§2.1).
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.domain_graph import (
    ConsolidationFlagInput,
    ConsolidationReviewAction,
    InvalidConsolidationTransitionError,
    SupplierInput,
    UnknownSupplierError,
    build_supplier_consolidation_graph,
    determine_consolidation_flag_transition,
)


def _suppliers():
    return [
        SupplierInput(id=1, public_id="sup-a", name="Cape Valley Foods"),
        SupplierInput(id=2, public_id="sup-b", name="Karoo Dry Goods"),
        SupplierInput(id=3, public_id="sup-c", name="Southern Packaging"),
    ]


class TestNodeDeduplication(unittest.TestCase):
    def test_supplier_appearing_in_multiple_flags_produces_one_node(self):
        flags = [
            ConsolidationFlagInput(1, 2, "Chicken Breast 5kg", "Chicken Breast 5kg", Decimal("0.92"), Decimal("50000"), "flagged"),
            ConsolidationFlagInput(1, 3, "Chicken Breast 5kg", "Poultry Fresh 5kg", Decimal("0.85"), None, "flagged"),
        ]
        graph = build_supplier_consolidation_graph(_suppliers(), flags)
        node_ids = [n.id for n in graph.nodes]
        self.assertEqual(len(node_ids), len(set(node_ids)), "supplier 1 must appear exactly once despite 2 flags")
        self.assertEqual(set(node_ids), {"sup-a", "sup-b", "sup-c"})
        self.assertEqual(len(graph.edges), 2)


class TestEdgeWeightFallback(unittest.TestCase):
    def test_combined_spend_used_when_present(self):
        flags = [ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.90"), Decimal("120000"), "flagged")]
        graph = build_supplier_consolidation_graph(_suppliers(), flags)
        self.assertEqual(graph.edges[0].weight, Decimal("120000"))

    def test_falls_back_to_similarity_score_when_spend_is_none(self):
        flags = [ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.90"), None, "flagged")]
        graph = build_supplier_consolidation_graph(_suppliers(), flags)
        self.assertEqual(graph.edges[0].weight, Decimal("0.90"))


class TestRawMetricsPreservedAlongsideWeight(unittest.TestCase):
    """The frontend drawer needs similarity_score and combined_spend as two separate numbers,
    not just the fallback-resolved weight (§2.1's boundary: the pure engine's job is topology +
    provenance, not deciding what a UI wants to show) - both raw fields must survive on the edge
    regardless of which one weight ended up resolving to."""

    def test_both_raw_fields_present_when_combined_spend_known(self):
        flags = [ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.90"), Decimal("120000"), "flagged")]
        graph = build_supplier_consolidation_graph(_suppliers(), flags)
        edge = graph.edges[0]
        self.assertEqual(edge.similarity_score, Decimal("0.90"))
        self.assertEqual(edge.combined_spend, Decimal("120000"))
        self.assertEqual(edge.weight, Decimal("120000"))  # weight still resolves to spend

    def test_similarity_score_present_and_combined_spend_none_when_unknown(self):
        flags = [ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.85"), None, "flagged")]
        graph = build_supplier_consolidation_graph(_suppliers(), flags)
        edge = graph.edges[0]
        self.assertEqual(edge.similarity_score, Decimal("0.85"))
        self.assertIsNone(edge.combined_spend)  # never fabricated
        self.assertEqual(edge.weight, Decimal("0.85"))  # weight falls back correctly


class TestEmptyInput(unittest.TestCase):
    def test_empty_flags_gives_empty_graph_not_an_error(self):
        graph = build_supplier_consolidation_graph(_suppliers(), [])
        self.assertEqual(graph.nodes, [])
        self.assertEqual(graph.edges, [])


class TestStrictStatusMapping(unittest.TestCase):
    def test_edge_status_matches_flag_status_verbatim_across_all_real_values(self):
        # Every real status value SupplierConsolidationFlag actually uses (app/db/models/
        # opportunity_flags.py) - proves no transformation, typo, or relabeling happens between
        # the DB column and the graph payload (§2.7's exact concern: a value compared/copied in
        # more than one place must not be able to silently drift).
        for real_status in ("flagged", "under_review", "consolidation_recommended", "rejected"):
            flags = [ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.90"), None, real_status)]
            graph = build_supplier_consolidation_graph(_suppliers(), flags)
            self.assertEqual(graph.edges[0].status, real_status)


class TestUnknownSupplierRaises(unittest.TestCase):
    def test_flag_referencing_unlisted_supplier_id_raises_not_silently_skips(self):
        # §5.2: never fail silently. A flag referencing a supplier_id the caller didn't provide
        # is a caller bug (FKs guarantee it can't happen from real DB data) - raise clearly
        # rather than quietly dropping the flag from the graph.
        flags = [ConsolidationFlagInput(1, 999, "A", "B", Decimal("0.90"), None, "flagged")]
        with self.assertRaises(UnknownSupplierError):
            build_supplier_consolidation_graph(_suppliers(), flags)


class TestDeterminism(unittest.TestCase):
    def test_identical_input_produces_byte_identical_output(self):
        # §7.3: same input, called twice, must produce equal output - the functional proof.
        flags = [
            ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.90"), Decimal("50000"), "flagged"),
            ConsolidationFlagInput(2, 3, "C", "D", Decimal("0.85"), None, "under_review"),
        ]
        first = build_supplier_consolidation_graph(_suppliers(), flags)
        second = build_supplier_consolidation_graph(_suppliers(), flags)
        self.assertEqual(first, second)

    def test_module_never_imports_time_or_datetime(self):
        # Structural proof, not just functional - catches a future addition that would silently
        # break determinism (e.g. someone adding a generated_at field with datetime.now() inside
        # the pure function) before it ever ships, not just when a test happens to notice output
        # changed. Same category of regression-proofing as §9's named historical fixtures.
        import app.analytics.domain_graph as module
        source = open(module.__file__).read()
        self.assertNotIn("import datetime", source)
        self.assertNotIn("from datetime", source)
        self.assertNotIn("import time", source)


class TestConsolidationFlagTransitions(unittest.TestCase):
    """Compliance-review follow-up: SupplierConsolidationFlag review workflow. Terminal states
    (consolidation_recommended, rejected) accept no further transitions; flagged can go straight
    to a terminal state or through under_review first - both are legitimate real-world paths."""

    def test_flagged_can_go_to_under_review(self):
        self.assertEqual(
            determine_consolidation_flag_transition("flagged", ConsolidationReviewAction.MARK_UNDER_REVIEW),
            "under_review",
        )

    def test_flagged_can_go_directly_to_consolidation_recommended(self):
        self.assertEqual(
            determine_consolidation_flag_transition("flagged", ConsolidationReviewAction.RECOMMEND_CONSOLIDATION),
            "consolidation_recommended",
        )

    def test_flagged_can_go_directly_to_rejected(self):
        self.assertEqual(
            determine_consolidation_flag_transition("flagged", ConsolidationReviewAction.REJECT),
            "rejected",
        )

    def test_under_review_can_reach_either_terminal_state(self):
        self.assertEqual(
            determine_consolidation_flag_transition("under_review", ConsolidationReviewAction.RECOMMEND_CONSOLIDATION),
            "consolidation_recommended",
        )
        self.assertEqual(
            determine_consolidation_flag_transition("under_review", ConsolidationReviewAction.REJECT),
            "rejected",
        )

    def test_under_review_cannot_go_back_to_flagged(self):
        # No action maps to 'flagged' at all - there is no way to construct this call that
        # succeeds, which is itself the point: flagged is only ever a starting state.
        with self.assertRaises(InvalidConsolidationTransitionError):
            determine_consolidation_flag_transition("under_review", ConsolidationReviewAction.MARK_UNDER_REVIEW)

    def test_consolidation_recommended_is_terminal(self):
        for action in ConsolidationReviewAction:
            with self.assertRaises(InvalidConsolidationTransitionError):
                determine_consolidation_flag_transition("consolidation_recommended", action)

    def test_rejected_is_terminal(self):
        for action in ConsolidationReviewAction:
            with self.assertRaises(InvalidConsolidationTransitionError):
                determine_consolidation_flag_transition("rejected", action)

    def test_unknown_current_status_raises(self):
        with self.assertRaises(InvalidConsolidationTransitionError):
            determine_consolidation_flag_transition("not_a_real_status", ConsolidationReviewAction.REJECT)


class TestMatchMethodPropagation(unittest.TestCase):
    """Compliance finding 4: match_method used to be computed by score_pair and silently
    discarded before ever reaching the flag or the graph. Confirms it now survives verbatim onto
    the edge, and that the test-convenience default doesn't leak into a real flag's output when a
    real value is supplied."""

    def test_match_method_survives_onto_the_edge(self):
        flags = [ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.90"), None, "flagged", match_method="fuzzy_description")]
        graph = build_supplier_consolidation_graph(_suppliers(), flags)
        self.assertEqual(graph.edges[0].match_method, "fuzzy_description")

    def test_default_match_method_is_unknown_when_not_specified(self):
        # Test-convenience default only - the real service layer always passes a value explicitly
        # (see domain_graph.py's ConsolidationFlagInput docstring for why this default exists).
        flags = [ConsolidationFlagInput(1, 2, "A", "B", Decimal("0.90"), None, "flagged")]
        graph = build_supplier_consolidation_graph(_suppliers(), flags)
        self.assertEqual(graph.edges[0].match_method, "unknown")


if __name__ == "__main__":
    unittest.main()
