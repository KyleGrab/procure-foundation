"""
Pack-size parsing and unit normalization (spec Sections 6-7). This is the module that makes
"12 x 1kg at R480" vs "10 x 1kg at R450" comparable as R40/kg vs R45/kg rather than a
misleading case-price drop - see the required test in spec Section 40, reproduced in
tests_pure/test_matching.py::test_pack_change_detection_cooking_oil.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# Base unit each recognised unit converts into, and the multiplier to get there.
# Mass -> kg, volume -> L, count -> each. Extending this table is how new units get supported -
# never infer a conversion factor per-row (that's a matching problem, not a units problem).
_UNIT_CONVERSIONS: dict[str, tuple[str, Decimal]] = {
    "g": ("kg", Decimal("0.001")),
    "gram": ("kg", Decimal("0.001")),
    "grams": ("kg", Decimal("0.001")),
    "kg": ("kg", Decimal("1")),
    "kilogram": ("kg", Decimal("1")),
    "kilograms": ("kg", Decimal("1")),
    "ml": ("L", Decimal("0.001")),
    "millilitre": ("L", Decimal("0.001")),
    "millilitres": ("L", Decimal("0.001")),
    "l": ("L", Decimal("1")),
    "litre": ("L", Decimal("1")),
    "litres": ("L", Decimal("1")),
    "liter": ("L", Decimal("1")),
    "liters": ("L", Decimal("1")),
    "each": ("each", Decimal("1")),
    "unit": ("each", Decimal("1")),
    "units": ("each", Decimal("1")),
    "ea": ("each", Decimal("1")),
}

# "24 x 330ml", "6 x 2L", "4x5kg" (case-insensitive, optional spaces around x)
_MULTI_PACK_RE = re.compile(
    r"^\s*(?P<qty>\d+(?:\.\d+)?)\s*x\s*(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+)\s*$",
    re.IGNORECASE,
)
# "10kg", "2L", "500g" - single item, no explicit multiplier
_SINGLE_RE = re.compile(
    r"^\s*(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+)\s*$", re.IGNORECASE
)
# "12 units", "24 each"
_COUNT_RE = re.compile(
    r"^\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>units?|each|ea)\s*$", re.IGNORECASE
)
# "case 24", "case of 24"
_CASE_RE = re.compile(r"^\s*case\s*(?:of\s*)?(?P<qty>\d+(?:\.\d+)?)\s*$", re.IGNORECASE)


class UnrecognizedPackFormatError(ValueError):
    """Raised when a pack string doesn't match any known pattern. Caller decides whether that's
    a validation error (reject the row) or a low-confidence match input (spec Section 31/32)."""


@dataclass(frozen=True)
class ParsedPack:
    pack_quantity: Decimal      # number of sub-units in the pack, e.g. 24
    unit_size: Decimal          # size of each sub-unit in its original unit, e.g. 330
    unit: str                   # original unit as given, lowercased, e.g. "ml"
    base_quantity: Decimal      # pack_quantity * unit_size converted to base_unit
    base_unit: str              # "kg" | "L" | "each"


def parse_pack_string(raw: str) -> ParsedPack:
    if raw is None:
        raise UnrecognizedPackFormatError("empty pack string")
    text = raw.strip()
    if not text:
        raise UnrecognizedPackFormatError("empty pack string")

    match = _MULTI_PACK_RE.match(text)
    if match:
        qty = Decimal(match.group("qty"))
        size = Decimal(match.group("size"))
        unit = match.group("unit").lower()
        return _build(qty, size, unit)

    match = _CASE_RE.match(text)
    if match:
        qty = Decimal(match.group("qty"))
        return _build(qty, Decimal("1"), "each")

    match = _COUNT_RE.match(text)
    if match:
        qty = Decimal(match.group("qty"))
        return _build(qty, Decimal("1"), "each")

    match = _SINGLE_RE.match(text)
    if match:
        size = Decimal(match.group("size"))
        unit = match.group("unit").lower()
        return _build(Decimal("1"), size, unit)

    raise UnrecognizedPackFormatError(f"Could not parse pack string: {raw!r}")


def _build(pack_quantity: Decimal, unit_size: Decimal, unit: str) -> ParsedPack:
    if unit not in _UNIT_CONVERSIONS:
        raise UnrecognizedPackFormatError(f"Unrecognised unit: {unit!r}")
    base_unit, factor = _UNIT_CONVERSIONS[unit]
    base_quantity = pack_quantity * unit_size * factor
    return ParsedPack(
        pack_quantity=pack_quantity,
        unit_size=unit_size,
        unit=unit,
        base_quantity=base_quantity,
        base_unit=base_unit,
    )


def price_per_base_unit(total_price: Decimal, parsed_pack: ParsedPack) -> Decimal:
    if parsed_pack.base_quantity == 0:
        raise ValueError("base_quantity is zero - cannot compute a unit price")
    return total_price / parsed_pack.base_quantity
