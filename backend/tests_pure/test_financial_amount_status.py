"""
Tests for classify_evidence_tier and is_evidence_downgrade - P-03. Pure mirror of the same
ranking used by the DB-level deferred trigger (check_event_chain_integrity) to decide which
change_reason_code values are valid for a given transition. Kept in sync deliberately, not
because the DB depends on this Python code (it doesn't - the DB enforces this independently via
CHECK constraints and PL/pgSQL), but because the service layer needs the same answer to build a
correct event before ever reaching the database, and to give an honest error message instead of
just "constraint violation" when a caller supplies a nonsensical reason code.
"""
from __future__ import annotations

import unittest

from app.analytics.management_accounting import (
    DOWNGRADE_APPROPRIATE_REASON_CODES,
    classify_evidence_tier,
    is_evidence_downgrade,
)


class TestClassifyEvidenceTier(unittest.TestCase):
    def test_unknown_and_not_applicable_share_tier_zero(self):
        self.assertEqual(classify_evidence_tier("unknown"), 0)
        self.assertEqual(classify_evidence_tier("not_applicable"), 0)

    def test_tiers_strictly_increase_through_the_evidence_hierarchy(self):
        ordered = ["unknown", "legacy_unverified", "estimated", "calculated", "confirmed"]
        tiers = [classify_evidence_tier(s) for s in ordered]
        self.assertEqual(tiers, sorted(tiers))
        self.assertEqual(len(set(tiers)), len(tiers))  # strictly increasing, no ties past tier 0

    def test_unrecognised_status_raises_rather_than_silently_defaulting(self):
        with self.assertRaises(ValueError):
            classify_evidence_tier("not_a_real_status")


class TestIsEvidenceDowngrade(unittest.TestCase):
    def test_confirmed_to_calculated_is_a_downgrade(self):
        self.assertTrue(is_evidence_downgrade(previous_status="confirmed", new_status="calculated"))

    def test_estimated_to_calculated_is_not_a_downgrade(self):
        self.assertFalse(is_evidence_downgrade(previous_status="estimated", new_status="calculated"))

    def test_same_status_is_not_a_downgrade(self):
        # A recalculation that stays in the same evidence tier (e.g. calculated -> calculated
        # with a revised amount) is explicitly not a downgrade - real, legitimate case.
        self.assertFalse(is_evidence_downgrade(previous_status="calculated", new_status="calculated"))

    def test_first_event_has_no_previous_status_and_is_never_a_downgrade(self):
        self.assertFalse(is_evidence_downgrade(previous_status=None, new_status="unknown"))
        self.assertFalse(is_evidence_downgrade(previous_status=None, new_status="confirmed"))


class TestDowngradeReasonCodeVocabulary(unittest.TestCase):
    def test_downgrade_appropriate_codes_are_a_real_subset_not_the_full_vocabulary(self):
        self.assertIn("correction", DOWNGRADE_APPROPRIATE_REASON_CODES)
        self.assertIn("evidence_withdrawn", DOWNGRADE_APPROPRIATE_REASON_CODES)
        self.assertIn("source_data_restated", DOWNGRADE_APPROPRIATE_REASON_CODES)
        self.assertNotIn("evidence_received", DOWNGRADE_APPROPRIATE_REASON_CODES)
        self.assertNotIn("manual_estimate", DOWNGRADE_APPROPRIATE_REASON_CODES)
        self.assertNotIn("initial_backfill", DOWNGRADE_APPROPRIATE_REASON_CODES)


if __name__ == "__main__":
    unittest.main()
