"""
Purchase-transaction row validation (Phase 4b). NOT a reuse of app.ingestion.validation.validate_rows
- that function is price-review-specific (hard-checks a `price` and `pack_size` field, both
absent from a transaction row), confirmed by actually running it against a mapped transaction row
before shipping this: it flagged every row with a fabricated "Missing price" error. Rather than
force-fitting a generic version of that validator (different required fields, different
appropriate severities - a negative amount is a legitimate credit/return here, not an error the
way a negative price would be), this is a small, purpose-built equivalent following the same
IssueSeverity/traceable-to-row-number shape.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from app.ingestion.validation import IssueSeverity, ValidationIssue


def validate_purchase_transaction_rows(rows: list[dict[str, str | None]]) -> list[dict]:
    """Returns one dict per row: {'row_number', 'is_valid', 'issues': [ValidationIssue, ...]}."""
    results = []
    seen_dupes: dict[tuple, int] = {}

    for idx, row in enumerate(rows, start=1):
        issues: list[ValidationIssue] = []

        raw_date = row.get("transaction_date")
        if not raw_date or not str(raw_date).strip():
            issues.append(ValidationIssue(idx, "transaction_date", IssueSeverity.ERROR, "Missing transaction date"))
        else:
            try:
                date.fromisoformat(str(raw_date).strip()[:10])
            except ValueError:
                issues.append(ValidationIssue(
                    idx, "transaction_date", IssueSeverity.ERROR,
                    f"Malformed date: {raw_date!r} (expected ISO 8601, e.g. 2026-03-15)",
                ))

        raw_amount = row.get("amount")
        amount: Decimal | None = None
        if not raw_amount or not str(raw_amount).strip():
            issues.append(ValidationIssue(idx, "amount", IssueSeverity.ERROR, "Missing amount"))
        else:
            try:
                amount = Decimal(str(raw_amount).replace(",", "").replace("R", "").strip())
            except InvalidOperation:
                issues.append(ValidationIssue(idx, "amount", IssueSeverity.ERROR, f"Malformed amount: {raw_amount!r}"))

        if amount is not None and amount == 0:
            issues.append(ValidationIssue(idx, "amount", IssueSeverity.WARNING, "Zero amount - confirm intentional"))
        if amount is not None and amount < 0:
            # Legitimate for transactions (credits/returns) - a warning to confirm, not an error
            # the way a negative price would be in price_review validation.
            issues.append(ValidationIssue(idx, "amount", IssueSeverity.WARNING, "Negative amount - confirm this is a credit/return"))

        if not (row.get("supplier_sku") or row.get("description")):
            issues.append(ValidationIssue(
                idx, "supplier_sku", IssueSeverity.WARNING,
                "No product identifier or description - transaction cannot be linked to a specific SKU",
            ))

        dupe_key = (row.get("reference"), raw_amount, raw_date)
        if row.get("reference") and dupe_key in seen_dupes:
            issues.append(ValidationIssue(
                idx, "reference", IssueSeverity.WARNING,
                f"Same reference/amount/date as row {seen_dupes[dupe_key]} - possible duplicate upload",
            ))
        elif row.get("reference"):
            seen_dupes[dupe_key] = idx

        is_valid = not any(i.severity == IssueSeverity.ERROR for i in issues)
        results.append({"row_number": idx, "is_valid": is_valid, "issues": issues})

    return results
