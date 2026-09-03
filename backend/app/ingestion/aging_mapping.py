"""
Aging-ledger column mapping, reusing app.ingestion.mapping's machinery. One mapping shape for
both ledger types - debtors and creditors uploads have identical columns (amount, days_overdue);
which ledger a batch represents is a service-layer parameter, not something the mapping/row
shape itself needs to encode.
"""
from __future__ import annotations

from app.ingestion.mapping import apply_mapping, suggest_mapping  # noqa: F401 - re-exported

AGING_CANONICAL_FIELDS = ["amount", "days_overdue"]

AGING_ALIASES: dict[str, list[str]] = {
    "amount": ["amount", "balance", "outstanding amount", "invoice amount", "value"],
    "days_overdue": ["days overdue", "age (days)", "days outstanding", "aging days", "days"],
}


def suggest_aging_mapping(source_columns: list[str]) -> dict[str, str | None]:
    return suggest_mapping(source_columns, canonical_fields=AGING_CANONICAL_FIELDS, aliases=AGING_ALIASES)
