"""
Phase 5b: inventory-snapshot column mapping, reusing app.ingestion.mapping's suggest_mapping/
apply_mapping machinery (ADR-013's established pattern) with its own canonical fields rather than
duplicating the matching logic. A stocktake export looks structurally different from a price list
or a transaction ledger (quantities and locations, not prices or amounts) - own field set, same
deterministic-alias-then-fuzzy approach, same "user must confirm" rule.
"""
from __future__ import annotations

from app.ingestion.mapping import apply_mapping, suggest_mapping  # noqa: F401 - re-exported

INVENTORY_SNAPSHOT_CANONICAL_FIELDS = [
    "supplier_sku", "description", "location", "snapshot_date",
    "quantity_on_hand", "unit_cost", "reorder_level", "expiry_date",
]

INVENTORY_SNAPSHOT_ALIASES: dict[str, list[str]] = {
    "supplier_sku": ["item code", "stock code", "supplier sku", "product code", "sku"],
    "description": ["description", "product description", "item description", "stock description"],
    "location": ["location", "warehouse", "site", "branch", "store"],
    "snapshot_date": ["date", "stocktake date", "count date", "as of date", "snapshot date"],
    "quantity_on_hand": ["quantity", "qty on hand", "qty", "units on hand", "stock on hand", "on hand"],
    "unit_cost": ["unit cost", "cost price", "average cost", "cost"],
    "reorder_level": ["reorder level", "reorder point", "min stock", "minimum quantity", "safety stock"],
    "expiry_date": ["expiry date", "expiry", "best before", "use by", "sell by date"],
}


def suggest_inventory_snapshot_mapping(source_columns: list[str]) -> dict[str, str | None]:
    return suggest_mapping(
        source_columns,
        canonical_fields=INVENTORY_SNAPSHOT_CANONICAL_FIELDS,
        aliases=INVENTORY_SNAPSHOT_ALIASES,
    )
