"""Covers spec Section 39: duplicate rows, malformed spreadsheet handling - the ingestion slice
of the required test list."""
from __future__ import annotations

import unittest

from app.ingestion.csv_reader import read_csv_rows
from app.ingestion.mapping import apply_mapping, suggest_mapping
from app.ingestion.validation import IssueSeverity, validate_rows


class TestCsvReader(unittest.TestCase):
    def test_reads_rows_keyed_by_header(self):
        content = "Item Code,Description,Price\nSKU1,Widget,10.50\nSKU2,Gadget,5.00\n"
        rows = read_csv_rows(content)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Item Code"], "SKU1")


class TestColumnMapping(unittest.TestCase):
    def test_known_alias_maps_directly(self):
        mapping = suggest_mapping(["Item Code", "Stock Code", "Supplier SKU", "Product Code"])
        # all four columns are aliases of supplier_sku - only the first one found should be used,
        # never silently overwritten, so the result is deterministic given column order.
        self.assertIsNotNone(mapping["supplier_sku"])

    def test_realistic_supplier_header_row(self):
        columns = ["Stock Code", "Description", "Pack Size", "Nett Price", "Barcode"]
        mapping = suggest_mapping(columns)
        self.assertEqual(mapping["supplier_sku"], "Stock Code")
        self.assertEqual(mapping["description"], "Description")
        self.assertEqual(mapping["pack_size"], "Pack Size")
        self.assertEqual(mapping["price"], "Nett Price")
        self.assertEqual(mapping["barcode"], "Barcode")

    def test_apply_mapping_reshapes_row(self):
        mapping = {"supplier_sku": "Stock Code", "description": "Description", "price": None}
        row = {"Stock Code": "SKU1", "Description": "Widget"}
        reshaped = apply_mapping(row, mapping)
        self.assertEqual(reshaped["supplier_sku"], "SKU1")
        self.assertIsNone(reshaped["price"])


class TestValidation(unittest.TestCase):
    def test_missing_price_is_an_error(self):
        rows = [{"supplier_sku": "SKU1", "description": "Widget", "price": "", "pack_size": "1kg"}]
        validated = validate_rows(rows)
        self.assertFalse(validated[0].is_valid)
        self.assertTrue(any(i.field == "price" for i in validated[0].issues))

    def test_negative_price_is_an_error(self):
        rows = [{"supplier_sku": "SKU1", "description": "Widget", "price": "-5", "pack_size": "1kg"}]
        validated = validate_rows(rows)
        self.assertFalse(validated[0].is_valid)

    def test_zero_price_is_a_warning_not_an_error(self):
        rows = [{"supplier_sku": "SKU1", "description": "Widget", "price": "0", "pack_size": "1kg"}]
        validated = validate_rows(rows)
        self.assertTrue(validated[0].is_valid)
        self.assertTrue(any(i.severity == IssueSeverity.WARNING for i in validated[0].issues))

    def test_duplicate_sku_flagged_and_traceable_to_both_rows(self):
        # spec Section 39 "duplicate rows" required test.
        rows = [
            {"supplier_sku": "SKU1", "description": "Widget", "price": "10", "pack_size": "1kg"},
            {"supplier_sku": "SKU1", "description": "Widget Duplicate", "price": "11", "pack_size": "1kg"},
        ]
        validated = validate_rows(rows)
        self.assertTrue(validated[0].is_valid)  # first occurrence is fine
        self.assertFalse(validated[1].is_valid)  # second occurrence is the duplicate
        dup_issue = next(i for i in validated[1].issues if "Duplicate" in i.message)
        self.assertIn("row 1", dup_issue.message)  # traceable back to the original row

    def test_malformed_price_does_not_crash_the_batch(self):
        # spec Section 39 "malformed spreadsheet" - one bad row must not take down the import.
        rows = [
            {"supplier_sku": "SKU1", "description": "Widget", "price": "not-a-number", "pack_size": "1kg"},
            {"supplier_sku": "SKU2", "description": "Gadget", "price": "10", "pack_size": "1kg"},
        ]
        validated = validate_rows(rows)
        self.assertFalse(validated[0].is_valid)
        self.assertTrue(validated[1].is_valid)


if __name__ == "__main__":
    unittest.main()
