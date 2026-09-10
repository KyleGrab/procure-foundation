"""
Covers spec Section 39's required test cases that fall under pack/unit parsing and description
normalization, plus the two tests the spec calls out explicitly by name in Sections 40 and 41.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.matching.normalize import find_variant_group, normalize_description
from app.matching.pack_parser import (
    UnrecognizedPackFormatError,
    parse_pack_string,
    price_per_base_unit,
)


class TestUnitConversion(unittest.TestCase):
    def test_kg_g_conversion(self):
        # 500g should normalize to the same base unit (kg) as a kg-denominated pack, so they're
        # comparable - spec Section 39 "kg/g conversion".
        grams = parse_pack_string("500g")
        self.assertEqual(grams.base_unit, "kg")
        self.assertEqual(grams.base_quantity, Decimal("0.5"))

        kilos = parse_pack_string("2kg")
        self.assertEqual(kilos.base_unit, "kg")
        self.assertEqual(kilos.base_quantity, Decimal(2))

    def test_litre_ml_conversion(self):
        # spec Section 39 "litre/ml conversion"
        ml = parse_pack_string("750ml")
        self.assertEqual(ml.base_unit, "L")
        self.assertEqual(ml.base_quantity, Decimal("0.75"))

        litres = parse_pack_string("2L")
        self.assertEqual(litres.base_unit, "L")
        self.assertEqual(litres.base_quantity, Decimal(2))

    def test_multi_pack_parsing(self):
        parsed = parse_pack_string("24 x 330ml")
        self.assertEqual(parsed.pack_quantity, Decimal(24))
        self.assertEqual(parsed.unit_size, Decimal(330))
        self.assertEqual(parsed.base_unit, "L")
        self.assertEqual(parsed.base_quantity, Decimal("7.92"))

    def test_case_and_count_formats(self):
        self.assertEqual(parse_pack_string("case 24").base_quantity, Decimal(24))
        self.assertEqual(parse_pack_string("12 units").base_quantity, Decimal(12))

    def test_unrecognized_format_raises(self):
        with self.assertRaises(UnrecognizedPackFormatError):
            parse_pack_string("assorted")

    def test_price_per_unit_conversion(self):
        # spec Section 39 "price-per-unit conversion"
        parsed = parse_pack_string("6 x 2L")
        price = price_per_base_unit(Decimal(360), parsed)
        self.assertEqual(price, Decimal(30))


class TestPackChangeDetection(unittest.TestCase):
    """The exact worked example from spec Section 40 - a case-price drop that is actually a
    10% normalized (per-litre) increase once pack size is accounted for."""

    def test_pack_change_detection_cooking_oil(self):
        old = parse_pack_string("6 x 2L")
        old_price_per_l = price_per_base_unit(Decimal(360), old)
        self.assertEqual(old_price_per_l, Decimal(30))

        new = parse_pack_string("4 x 2L")
        new_price_per_l = price_per_base_unit(Decimal(264), new)
        self.assertEqual(new_price_per_l, Decimal(33))

        pct_change = (new_price_per_l - old_price_per_l) / old_price_per_l
        self.assertEqual(pct_change, Decimal("0.1"))  # 10% increase, not a case-price decrease
        # The trap this test guards against: the raw case price dropped (264 < 360) while the
        # normalized per-litre price rose - a naive case-price comparison would report a
        # decrease when the true, pack-adjusted result is a 10% increase.
        self.assertLess(Decimal(264), Decimal(360))
        self.assertGreater(pct_change, 0)

    def test_pack_change_detection_frozen_chips_example(self):
        # spec Section 7's own worked example: 12x1kg at R480 -> 10x1kg at R450 is a 12.5%
        # per-kg increase, not the ~6% case-price drop it looks like at first glance.
        old = parse_pack_string("12 x 1kg")
        old_price_per_kg = price_per_base_unit(Decimal(480), old)
        self.assertEqual(old_price_per_kg, Decimal(40))

        new = parse_pack_string("10 x 1kg")
        new_price_per_kg = price_per_base_unit(Decimal(450), new)
        self.assertEqual(new_price_per_kg, Decimal(45))

        pct_change = (new_price_per_kg - old_price_per_kg) / old_price_per_kg
        self.assertEqual(pct_change, Decimal("0.125"))


class TestDescriptionNormalization(unittest.TestCase):
    def test_normalization_is_idempotent_and_strips_noise(self):
        normalized = normalize_description("  Coca-Cola   Zero!! 330ml x24  ")
        self.assertEqual(normalize_description(normalized), normalized)
        self.assertNotIn("!", normalized)

    def test_variant_conflict_detection_cheddar(self):
        # spec Section 41's required test: "Cheddar Cheese Mature 2kg" and "Cheddar Cheese Mild
        # 2kg" must be recognised as conflicting variants, not as the same product.
        mature = normalize_description("Cheddar Cheese Mature 2kg")
        mild = normalize_description("Cheddar Cheese Mild 2kg")
        self.assertIsNotNone(find_variant_group(mature))
        self.assertIsNotNone(find_variant_group(mild))
        self.assertNotEqual(find_variant_group(mature), find_variant_group(mild))


if __name__ == "__main__":
    unittest.main()
