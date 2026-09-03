"""Proves the purpose-built purchase-transaction validator handles rows correctly - including the
exact case that broke when validate_rows (price-review-specific) was force-reused."""
from __future__ import annotations

import unittest

from app.ingestion.purchase_transaction_validation import validate_purchase_transaction_rows


class TestPurchaseTransactionValidation(unittest.TestCase):
    def test_well_formed_row_is_valid(self):
        # The exact row shape that validate_rows incorrectly rejected with "Missing price" -
        # this is the regression case.
        rows = [{"supplier_sku": "SKU1", "description": "Widget", "transaction_date": "2026-03-15",
                  "amount": "1500.00", "quantity": "10", "reference": "INV-001"}]
        results = validate_purchase_transaction_rows(rows)
        self.assertTrue(results[0]["is_valid"])
        self.assertEqual(results[0]["issues"], [])

    def test_missing_amount_is_an_error(self):
        rows = [{"transaction_date": "2026-03-15", "amount": ""}]
        results = validate_purchase_transaction_rows(rows)
        self.assertFalse(results[0]["is_valid"])

    def test_missing_date_is_an_error(self):
        rows = [{"transaction_date": "", "amount": "100"}]
        results = validate_purchase_transaction_rows(rows)
        self.assertFalse(results[0]["is_valid"])

    def test_malformed_date_is_an_error(self):
        rows = [{"transaction_date": "15/03/2026", "amount": "100"}]
        results = validate_purchase_transaction_rows(rows)
        self.assertFalse(results[0]["is_valid"])

    def test_negative_amount_is_a_warning_not_an_error(self):
        # A credit/return is legitimate for a transaction, unlike a negative price.
        rows = [{"transaction_date": "2026-03-15", "amount": "-250.00", "reference": "CN-001"}]
        results = validate_purchase_transaction_rows(rows)
        self.assertTrue(results[0]["is_valid"])
        self.assertTrue(any(i.severity.value == "warning" for i in results[0]["issues"]))

    def test_possible_duplicate_flagged_as_warning(self):
        rows = [
            {"transaction_date": "2026-03-15", "amount": "100", "reference": "INV-100"},
            {"transaction_date": "2026-03-15", "amount": "100", "reference": "INV-100"},
        ]
        results = validate_purchase_transaction_rows(rows)
        self.assertTrue(results[0]["is_valid"])
        self.assertTrue(results[1]["is_valid"])  # warning, not blocked
        self.assertTrue(any("duplicate" in i.message.lower() for i in results[1]["issues"]))


if __name__ == "__main__":
    unittest.main()
