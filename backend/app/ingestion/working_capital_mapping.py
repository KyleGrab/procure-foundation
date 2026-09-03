"""
Working-capital-snapshot column mapping, reusing app.ingestion.mapping's suggest_mapping/
apply_mapping machinery (ADR-013's established pattern) with its own canonical fields. One row
per period - a balance-sheet-style summary snapshot, not a line-item batch (that's what
aging_mapping.py is for).
"""
from __future__ import annotations

from app.ingestion.mapping import apply_mapping, suggest_mapping  # noqa: F401 - re-exported

WORKING_CAPITAL_CANONICAL_FIELDS = [
    "as_of_date", "accounts_receivable", "accounts_payable", "inventory_value",
    "cash_balance", "annualized_revenue", "annualized_cogs",
]

WORKING_CAPITAL_ALIASES: dict[str, list[str]] = {
    "as_of_date": ["date", "period end", "as at", "balance sheet date", "period"],
    "accounts_receivable": ["trade receivables", "debtors", "ar", "accounts receivable"],
    "accounts_payable": ["trade payables", "trade creditors", "creditors", "ap", "accounts payable"],
    "inventory_value": ["inventory", "stock value", "inventory value", "stock on hand value"],
    "cash_balance": ["cash", "cash and cash equivalents", "bank balance", "cash at bank"],
    "annualized_revenue": ["annual revenue", "ttm revenue", "annualised turnover", "net sales ttm"],
    "annualized_cogs": ["annual cogs", "ttm cogs", "annualised cost of sales", "net cost of sales ttm"],
}


def suggest_working_capital_mapping(source_columns: list[str]) -> dict[str, str | None]:
    return suggest_mapping(
        source_columns, canonical_fields=WORKING_CAPITAL_CANONICAL_FIELDS, aliases=WORKING_CAPITAL_ALIASES,
    )
