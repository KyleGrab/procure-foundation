"""
Working-capital-snapshot row validation. Purpose-built, not reused from another validator -
Phase 4b's lesson (reusing price-review validation for transaction rows flagged every row with
"missing price") applies here too: a balance-sheet-style row has its own real edge cases.

Deliberately asymmetric negative-value handling, stated per field rather than one blanket rule:
cash_balance can legitimately be negative (an overdraft - Gourmet's own real August 2026 figure
is -R19,518,395.79) and is never flagged, not even as a warning. accounts_receivable/
accounts_payable going negative (a credit balance/overpayment) is unusual but real - a warning,
not an error. inventory_value has no legitimate negative state - an error.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from app.ingestion.validation import IssueSeverity, ValidationIssue


def validate_working_capital_row(row: dict[str, str | None]) -> dict:
    """One row per period, not a batch - returns {'is_valid', 'issues'} directly, not a list."""
    issues: list[ValidationIssue] = []

    raw_date = row.get("as_of_date")
    if not raw_date or not str(raw_date).strip():
        issues.append(ValidationIssue(1, "as_of_date", IssueSeverity.ERROR, "Missing as_of_date"))
    else:
        try:
            date.fromisoformat(str(raw_date).strip()[:10])
        except ValueError:
            issues.append(ValidationIssue(
                1, "as_of_date", IssueSeverity.ERROR,
                f"Malformed date: {raw_date!r} (expected ISO 8601, e.g. 2026-08-31)",
            ))

    def _parse_required_decimal(field: str, label: str) -> Decimal | None:
        raw = row.get(field)
        if raw is None or not str(raw).strip():
            issues.append(ValidationIssue(1, field, IssueSeverity.ERROR, f"Missing {label}"))
            return None
        try:
            return Decimal(str(raw).replace(",", "").replace("R", "").strip())
        except InvalidOperation:
            issues.append(ValidationIssue(1, field, IssueSeverity.ERROR, f"Malformed {label}: {raw!r}"))
            return None

    ar = _parse_required_decimal("accounts_receivable", "accounts receivable")
    if ar is not None and ar < 0:
        issues.append(ValidationIssue(
            1, "accounts_receivable", IssueSeverity.WARNING,
            f"Negative accounts receivable: {ar} - unusual (a credit balance) but not rejected",
        ))

    ap = _parse_required_decimal("accounts_payable", "accounts payable")
    if ap is not None and ap < 0:
        issues.append(ValidationIssue(
            1, "accounts_payable", IssueSeverity.WARNING,
            f"Negative accounts payable: {ap} - unusual (an overpayment) but not rejected",
        ))

    inventory = _parse_required_decimal("inventory_value", "inventory value")
    if inventory is not None and inventory < 0:
        # Unlike AR/AP/cash, no legitimate real-world state produces a negative inventory value -
        # an error, not a warning.
        issues.append(ValidationIssue(
            1, "inventory_value", IssueSeverity.ERROR, f"Negative inventory value: {inventory}",
        ))

    raw_cash = row.get("cash_balance")
    if raw_cash is not None and str(raw_cash).strip():
        try:
            Decimal(str(raw_cash).replace(",", "").replace("R", "").strip())
            # Deliberately never flagged for sign, at any severity - see module docstring.
        except InvalidOperation:
            issues.append(ValidationIssue(1, "cash_balance", IssueSeverity.WARNING, f"Malformed cash balance: {raw_cash!r} - ignored"))

    # Zero is valid for both - calculate_working_capital_metrics already returns None gracefully
    # for a zero denominator, so this isn't re-flagged as a data problem at ingestion time.
    _parse_required_decimal("annualized_revenue", "annualized revenue")
    _parse_required_decimal("annualized_cogs", "annualized COGS")

    is_valid = not any(i.severity == IssueSeverity.ERROR for i in issues)
    return {"is_valid": is_valid, "issues": issues}
