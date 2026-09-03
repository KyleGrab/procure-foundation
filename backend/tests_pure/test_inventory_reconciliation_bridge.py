"""
Tests for validate_reconciliation_bridge_completeness - Gate A, migration 0020.

Distinct from check_inventory_reconciliation (already real, tested, Chaos Audit): that function
DETECTS whether a gap exists between a sub-ledger extract and the control total. This function
checks whether the SUM of actual, evidenced bridge line items genuinely CLOSES that gap.
bridge_total is never derived by solving "whatever makes the equation balance" - it comes from
real bridge evidence independently, and final_variance is a genuine, non-trivial check on
whether that evidence is actually correct and complete.

[DEMO] figures throughout, deliberately different from R21,399,596.84/R495,473.98 - that specific
pair was identified as fabricated earlier in this engagement (traced to a prior document that
presented it as an authoritative real reconciliation; it was not) and is never used here, even
illustratively, to avoid any risk of it being mistaken for something this file treats as real.
The one real, verified figure is R21,895,070.82 - the actual Balance Sheet control total.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.management_accounting import validate_reconciliation_bridge_completeness

REAL_CONTROL_TOTAL = Decimal("21895070.82")


class TestValidateReconciliationBridgeCompleteness(unittest.TestCase):
    def test_demo_fully_evidenced_bridge_produces_zero_final_variance(self):
        result = validate_reconciliation_bridge_completeness(
            control_total=REAL_CONTROL_TOTAL,
            raw_subledger_total=Decimal("21500000.00"), bridge_total=Decimal("395070.82"),
        )
        self.assertEqual(result["reconciled_total"], Decimal("21895070.8200"))
        self.assertEqual(result["final_variance"], Decimal("0.0000"))
        self.assertTrue(result["is_fully_explained"])

    def test_demo_incomplete_bridge_evidence_leaves_a_real_nonzero_residual(self):
        # The genuine point of this function: if the evidenced bridge amount doesn't actually
        # cover the real gap, that must show up as a real, visible variance - never silently
        # accepted as "reconciled" just because a bridge record exists at all.
        result = validate_reconciliation_bridge_completeness(
            control_total=REAL_CONTROL_TOTAL,
            raw_subledger_total=Decimal("21500000.00"), bridge_total=Decimal("300000.00"),
        )
        self.assertEqual(result["final_variance"], Decimal("-95070.8200"))
        self.assertFalse(result["is_fully_explained"])

    def test_demo_over_evidenced_bridge_also_flags_as_not_fully_explained(self):
        # Symmetric case - bridge evidence exceeding what's actually needed is equally a real
        # problem (overstated adjustments), not silently accepted just because it's the "wrong
        # direction" of error.
        result = validate_reconciliation_bridge_completeness(
            control_total=REAL_CONTROL_TOTAL,
            raw_subledger_total=Decimal("21500000.00"), bridge_total=Decimal("500000.00"),
        )
        self.assertFalse(result["is_fully_explained"])
        self.assertNotEqual(result["final_variance"], Decimal("0.0000"))

    def test_zero_bridge_with_matching_subledger_is_trivially_fully_explained(self):
        # No bridge needed at all - sub-ledger already equals control total exactly.
        result = validate_reconciliation_bridge_completeness(
            control_total=REAL_CONTROL_TOTAL, raw_subledger_total=REAL_CONTROL_TOTAL, bridge_total=Decimal("0"),
        )
        self.assertTrue(result["is_fully_explained"])


if __name__ == "__main__":
    unittest.main()
