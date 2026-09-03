"""
Phase 4b: purchase-transaction column mapping, reusing app.ingestion.mapping's suggest_mapping/
apply_mapping machinery (ADR-013) with its own canonical fields rather than duplicating the
matching logic. A purchase transaction file looks structurally different from a price list (dates
and amounts, not prices and packs), so it gets its own field set - but the same deterministic-
alias-then-fuzzy approach, same "user must confirm" rule (spec Section 3).
"""
from __future__ import annotations

from app.ingestion.mapping import apply_mapping, suggest_mapping  # noqa: F401 - re-exported

PURCHASE_TRANSACTION_CANONICAL_FIELDS = [
    "supplier_sku", "description", "transaction_date", "amount", "quantity", "reference",
]

PURCHASE_TRANSACTION_ALIASES: dict[str, list[str]] = {
    "supplier_sku": ["item code", "stock code", "supplier sku", "product code", "sku"],
    "description": ["description", "product description", "item description", "line description"],
    "transaction_date": ["date", "transaction date", "invoice date", "posting date", "txn date"],
    "amount": ["amount", "value", "line amount", "total", "net amount", "invoice amount"],
    "quantity": ["quantity", "qty", "units", "volume"],
    "reference": ["reference", "invoice number", "invoice no", "document number", "ref"],
}


def suggest_purchase_transaction_mapping(source_columns: list[str]) -> dict[str, str | None]:
    return suggest_mapping(
        source_columns,
        canonical_fields=PURCHASE_TRANSACTION_CANONICAL_FIELDS,
        aliases=PURCHASE_TRANSACTION_ALIASES,
    )
