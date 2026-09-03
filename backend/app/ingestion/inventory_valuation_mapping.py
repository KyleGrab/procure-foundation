"""
Gourmet-style Inventory Valuation Report (Crystal Reports export) column mapping. Reuses
app.ingestion.mapping's suggest_mapping/apply_mapping machinery (ADR-013's pattern), same as
every other ingestion module this sprint.

Deliberately resolves onto the SAME canonical fields app.ingestion.inventory_mapping already
defines (Phase 5b) - supplier_sku, description, quantity_on_hand, unit_cost - not a new,
parallel field set. "MAC Unit Cost" and "Stock Code" are Gourmet's own vocabulary for concepts
InventorySnapshot already models; giving them different canonical names here would mean this
module's output could never actually connect to that table without a second translation layer.

total_valuation is the one genuinely new field, and it is NOT one of InventorySnapshot's real
columns - see inventory_valuation_validation.py's docstring for why it exists only as a
cross-check against quantity_on_hand * unit_cost, never as a third, independently-persisted figure.
"""
from __future__ import annotations

from app.ingestion.inventory_mapping import INVENTORY_SNAPSHOT_CANONICAL_FIELDS
from app.ingestion.mapping import apply_mapping, suggest_mapping  # noqa: F401 - re-exported

INVENTORY_VALUATION_CANONICAL_FIELDS = [
    f for f in INVENTORY_SNAPSHOT_CANONICAL_FIELDS
    if f in ("supplier_sku", "description", "quantity_on_hand", "unit_cost")
] + ["total_valuation"]

INVENTORY_VALUATION_ALIASES: dict[str, list[str]] = {
    "supplier_sku": ["stock code", "stock_code", "stock no", "stock_no", "item_code", "item code", "sku"],
    "description": ["description", "item_description", "item description", "stock_description", "stock description"],
    "quantity_on_hand": ["qty_on_hand", "qty on hand", "closing_stock", "closing stock", "quantity", "qoh"],
    "unit_cost": ["moving_avg_cost", "moving avg cost", "mac_unit_cost", "mac unit cost", "unit_cost", "unit cost", "avg_cost", "avg cost"],
    "total_valuation": ["total_valuation", "total valuation", "asset_value", "asset value", "total_cost", "total cost"],
}


def suggest_inventory_valuation_mapping(source_columns: list[str]) -> dict[str, str | None]:
    return suggest_mapping(
        source_columns, canonical_fields=INVENTORY_VALUATION_CANONICAL_FIELDS, aliases=INVENTORY_VALUATION_ALIASES,
    )
