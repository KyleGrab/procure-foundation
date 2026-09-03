"""Confirms Phase 4b's purchase-transaction mapping genuinely reuses Phase 2's mapping engine
against a realistic transaction-file header row, not just that the function doesn't crash."""
from __future__ import annotations

import unittest

from app.ingestion.purchase_transaction_mapping import suggest_purchase_transaction_mapping


class TestPurchaseTransactionMapping(unittest.TestCase):
    def test_realistic_transaction_header_row(self):
        columns = ["Stock Code", "Line Description", "Invoice Date", "Net Amount", "Qty", "Invoice Number"]
        mapping = suggest_purchase_transaction_mapping(columns)
        self.assertEqual(mapping["supplier_sku"], "Stock Code")
        self.assertEqual(mapping["description"], "Line Description")
        self.assertEqual(mapping["transaction_date"], "Invoice Date")
        self.assertEqual(mapping["amount"], "Net Amount")
        self.assertEqual(mapping["quantity"], "Qty")
        self.assertEqual(mapping["reference"], "Invoice Number")

    def test_does_not_pick_up_price_review_only_fields(self):
        # pack_size/barcode are price-review canonical fields (Phase 2) - they must not appear
        # in a purchase-transaction mapping's output at all, proving the two field sets are
        # genuinely separate, not just the same dict with extra unused keys.
        mapping = suggest_purchase_transaction_mapping(["Stock Code", "Amount", "Date"])
        self.assertNotIn("pack_size", mapping)
        self.assertNotIn("barcode", mapping)


if __name__ == "__main__":
    unittest.main()
