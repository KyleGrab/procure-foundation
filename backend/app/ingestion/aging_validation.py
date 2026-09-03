"""
Aging-ledger row validation. Purpose-built, matching classify_aging_buckets's real input shape
(list of {"amount": Decimal, "days_overdue": int}) exactly, so validated rows need zero
transformation before hitting the pure function.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.ingestion.validation import IssueSeverity, ValidationIssue


def validate_aging_rows(rows: list[dict[str, str | None]]) -> list[dict]:
    """Batch validator (unlike working capital's single-row shape) - one aging upload is a full
    invoice-level line-item batch for one ledger_type/period."""
    results = []

    for idx, row in enumerate(rows, start=1):
        issues: list[ValidationIssue] = []

        raw_amount = row.get("amount")
        if raw_amount is None or not str(raw_amount).strip():
            issues.append(ValidationIssue(idx, "amount", IssueSeverity.ERROR, "Missing amount"))
        else:
            try:
                Decimal(str(raw_amount).replace(",", "").replace("R", "").strip())
            except InvalidOperation:
                issues.append(ValidationIssue(idx, "amount", IssueSeverity.ERROR, f"Malformed amount: {raw_amount!r}"))

        raw_days = row.get("days_overdue")
        if raw_days is None or not str(raw_days).strip():
            issues.append(ValidationIssue(idx, "days_overdue", IssueSeverity.ERROR, "Missing days_overdue"))
        else:
            try:
                int(str(raw_days).strip())
                # A negative value (not-yet-due) is deliberately not flagged -
                # classify_aging_buckets's own boundary (days < 30 -> current) already handles it
                # correctly without needing it rejected here.
            except ValueError:
                issues.append(ValidationIssue(idx, "days_overdue", IssueSeverity.ERROR, f"Malformed days_overdue: {raw_days!r}"))

        is_valid = not any(i.severity == IssueSeverity.ERROR for i in issues)
        results.append({"row_number": idx, "is_valid": is_valid, "issues": issues})

    return results
