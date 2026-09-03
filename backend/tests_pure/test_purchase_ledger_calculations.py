"""Covers PPV (analytics-methodology.md §5's worked example), invoice line calculations, and
goods-receipt variance."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics.purchase_ledger_calculations import (
    ReceiptStatus,
    calculate_invoice_line_net_amount,
    calculate_invoice_line_total_incl_tax,
    calculate_purchase_price_variance,
    calculate_receipt_variance,
)


class TestPurchasePriceVariance(unittest.TestCase):
    def test_ppv_worked_example(self):
        # analytics-methodology.md §5's own formula, reference price above actual (a favourable
        # variance - we paid less than the reference).
        result = calculate_purchase_price_variance(
            reference_price=Decimal("100"), actual_price=Decimal("95"), quantity=Decimal("20000"),
        )
        self.assertEqual(result.expected_cost, Decimal("2000000.0000"))
        self.assertEqual(result.actual_cost, Decimal("1900000.0000"))
        self.assertEqual(result.variance, Decimal("-100000.0000"))  # paid less than reference

    def test_unfavourable_variance_is_positive(self):
        result = calculate_purchase_price_variance(
            reference_price=Decimal("100"), actual_price=Decimal("110"), quantity=Decimal("1000"),
        )
        self.assertEqual(result.variance, Decimal("10000.0000"))
        self.assertGreater(result.variance, 0)

    def test_zero_reference_price_gives_none_percentage_not_error(self):
        result = calculate_purchase_price_variance(
            reference_price=Decimal("0"), actual_price=Decimal("50"), quantity=Decimal("10"),
        )
        self.assertIsNone(result.variance_pct)
        self.assertEqual(result.variance, Decimal("500.0000"))  # the absolute variance still computes


class TestInvoiceLineCalculations(unittest.TestCase):
    def test_net_amount_without_discount(self):
        net = calculate_invoice_line_net_amount(Decimal("10"), Decimal("25.50"))
        self.assertEqual(net, Decimal("255.0000"))

    def test_net_amount_with_discount(self):
        net = calculate_invoice_line_net_amount(Decimal("10"), Decimal("100"), Decimal("0.10"))
        self.assertEqual(net, Decimal("900.0000"))

    def test_total_incl_tax(self):
        total = calculate_invoice_line_total_incl_tax(Decimal("900"), Decimal("0.15"))
        self.assertEqual(total, Decimal("1035.0000"))

    def test_total_incl_tax_with_no_tax(self):
        total = calculate_invoice_line_total_incl_tax(Decimal("900"), None)
        self.assertEqual(total, Decimal("900.0000"))


class TestReceiptVariance(unittest.TestCase):
    def test_complete_receipt(self):
        result = calculate_receipt_variance(Decimal("100"), Decimal("100"))
        self.assertEqual(result.status, ReceiptStatus.COMPLETE)
        self.assertEqual(result.variance_quantity, Decimal("0"))

    def test_short_receipt(self):
        result = calculate_receipt_variance(Decimal("100"), Decimal("85"))
        self.assertEqual(result.status, ReceiptStatus.SHORT)
        self.assertEqual(result.variance_quantity, Decimal("-15"))

    def test_over_receipt(self):
        result = calculate_receipt_variance(Decimal("100"), Decimal("110"))
        self.assertEqual(result.status, ReceiptStatus.OVER)
        self.assertEqual(result.variance_quantity, Decimal("10"))

    def test_negative_quantities_rejected(self):
        with self.assertRaises(ValueError):
            calculate_receipt_variance(Decimal("-5"), Decimal("10"))

    def test_zero_ordered_gives_none_percentage(self):
        result = calculate_receipt_variance(Decimal("0"), Decimal("5"))
        self.assertIsNone(result.variance_pct)
        self.assertEqual(result.status, ReceiptStatus.OVER)


if __name__ == "__main__":
    unittest.main()
