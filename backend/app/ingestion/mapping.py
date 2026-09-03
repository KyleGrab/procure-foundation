"""
Column-mapping suggestion (spec Section 3). Deterministic synonym lookup first, then fuzzy
column-name matching as a fallback - AI-assisted suggestion (the spec's third tier) is deferred
to Phase 6's LLMProvider per docs/architecture.md's AI sequencing; a human confirms every
mapping regardless of which tier proposed it (spec Section 3's own requirement), so the AI tier
being deferred doesn't block this working end-to-end.

CANONICAL_FIELDS/_ALIASES below are the price-review defaults (Phase 2). Phase 4b's
purchase-transaction ingestion reuses this same suggest_mapping()/apply_mapping() machinery with
its own field set (PURCHASE_TRANSACTION_CANONICAL_FIELDS/_ALIASES) rather than duplicating the
matching logic - see app/ingestion/purchase_transaction_mapping.py.
"""
from __future__ import annotations

from difflib import get_close_matches

CANONICAL_FIELDS = [
    "supplier_sku", "description", "brand", "category", "uom", "pack_quantity",
    "pack_size", "weight", "weight_uom", "barcode", "price", "effective_date",
]

# Known aliases seen in real South African supplier price lists. Extending this list is cheap
# and safe; it's the first (and cheapest, most reliable) mapping tier for a reason.
_ALIASES: dict[str, list[str]] = {
    "supplier_sku": ["item code", "stock code", "supplier sku", "product code", "sku",
                      "item no", "stock no", "code"],
    "description": ["description", "product description", "item description", "product name",
                     "stock description"],
    "brand": ["brand", "brand name", "manufacturer"],
    "category": ["category", "product category", "department"],
    "uom": ["uom", "unit of measure", "unit"],
    "pack_quantity": ["pack qty", "pack quantity", "case qty", "units per case", "pack size qty"],
    "pack_size": ["pack size", "pack", "pack description", "size"],
    "weight": ["weight", "net weight", "mass"],
    "weight_uom": ["weight uom", "weight unit"],
    "barcode": ["barcode", "ean", "upc", "ean13", "ean code"],
    "price": ["price", "unit price", "cost price", "list price", "nett price", "net price"],
    "effective_date": ["effective date", "price date", "valid from", "date"],
}
_ALIAS_LOOKUP: dict[str, str] = {
    alias: canonical for canonical, aliases in _ALIASES.items() for alias in aliases
}


def suggest_mapping(
    source_columns: list[str],
    canonical_fields: list[str] | None = None,
    aliases: dict[str, list[str]] | None = None,
) -> dict[str, str | None]:
    """
    Returns {canonical_field: source_column_or_None}. Never auto-applied - the caller must have
    the user confirm ambiguous mappings (spec Section 3) before any row is processed.

    canonical_fields/aliases default to the price-review field set (Phase 2) for backward
    compatibility with every existing call site - Phase 4b's purchase-transaction ingestion
    passes its own (see app/ingestion/purchase_transaction_mapping.py) rather than this function
    changing behavior for callers that don't ask for it.
    """
    canonical_fields = canonical_fields if canonical_fields is not None else CANONICAL_FIELDS
    aliases = aliases if aliases is not None else _ALIASES
    alias_lookup = {alias: canonical for canonical, aliases_ in aliases.items() for alias in aliases_}

    normalized_columns = {c: c.strip().lower() for c in source_columns}
    result: dict[str, str | None] = {field: None for field in canonical_fields}

    # Tier 1: exact alias match
    for source_col, normalized in normalized_columns.items():
        canonical = alias_lookup.get(normalized)
        if canonical and result.get(canonical) is None:
            result[canonical] = source_col

    # Tier 2: fuzzy match against remaining unmapped canonical fields, using both the canonical
    # field name itself and its aliases as match candidates.
    unmapped_columns = [c for c in source_columns if c not in result.values()]
    for canonical in canonical_fields:
        if result[canonical] is not None:
            continue
        candidates = [canonical.replace("_", " ")] + aliases.get(canonical, [])
        for source_col in unmapped_columns:
            normalized = normalized_columns[source_col]
            close = get_close_matches(normalized, candidates, n=1, cutoff=0.75)
            if close:
                result[canonical] = source_col
                unmapped_columns.remove(source_col)
                break

    return result


def apply_mapping(row: dict[str, str], mapping: dict[str, str | None]) -> dict[str, str | None]:
    """Reshapes one source row into canonical-field keys, given a (user-confirmed) mapping."""
    return {
        canonical: (row.get(source_col) if source_col else None)
        for canonical, source_col in mapping.items()
    }
