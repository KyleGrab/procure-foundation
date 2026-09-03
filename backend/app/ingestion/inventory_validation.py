"""
Inventory-snapshot row validation (Phase 5b). NOT a reuse of app.ingestion.validation.validate_rows
or purchase_transaction_validation.py's validator - a stocktake row has its own required fields
(quantity_on_hand, not price or amount) and its own legitimate edge cases (quantity_on_hand of
exactly 0 is a completely normal, real state for an out-of-stock item - not a warning the way a
zero transaction amount is). Small, purpose-built, same IssueSeverity/traceable-to-row-number
shape as every other ingestion validator in this codebase.

Two-stage design, deliberately: this module validates individual field values on the raw mapped
rows (before any DB lookup). Grain validation (app.analytics.inventory_calculations -
validate_snapshot_grain, already built and tested) needs a resolved location_id, which doesn't
exist until the not-yet-built service layer matches each row's free-text location string to a
real Location - so it runs as a separate, later step over SnapshotRow objects the service layer
constructs, not inside this module's field-level pass. Re-exported here for callers that want both
steps from one import, not because this module computes it.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from app.analytics.inventory_calculations import (  # noqa: F401 - re-exported, see module docstring
    GrainViolation,
    SnapshotRow,
    validate_snapshot_grain,
)
from app.ingestion.validation import IssueSeverity, ValidationIssue


def validate_inventory_snapshot_rows(rows: list[dict[str, str | None]]) -> list[dict]:
    """Returns one dict per row: {'row_number', 'is_valid', 'issues': [ValidationIssue, ...]}."""
    results = []

    for idx, row in enumerate(rows, start=1):
        issues: list[ValidationIssue] = []

        if not (row.get("supplier_sku") or row.get("description")):
            issues.append(ValidationIssue(
                idx, "description", IssueSeverity.ERROR,
                "No product identifier or description - snapshot row cannot be linked to an item",
            ))

        raw_date = row.get("snapshot_date")
        if not raw_date or not str(raw_date).strip():
            issues.append(ValidationIssue(idx, "snapshot_date", IssueSeverity.ERROR, "Missing snapshot date"))
        else:
            try:
                date.fromisoformat(str(raw_date).strip()[:10])
            except ValueError:
                issues.append(ValidationIssue(
                    idx, "snapshot_date", IssueSeverity.ERROR,
                    f"Malformed date: {raw_date!r} (expected ISO 8601, e.g. 2026-03-15)",
                ))

        raw_quantity = row.get("quantity_on_hand")
        if not raw_quantity or not str(raw_quantity).strip():
            issues.append(ValidationIssue(idx, "quantity_on_hand", IssueSeverity.ERROR, "Missing quantity on hand"))
        else:
            try:
                quantity = Decimal(str(raw_quantity).replace(",", "").strip())
                if quantity < 0:
                    # Unlike a transaction amount, a negative quantity on hand has no legitimate
                    # real-world meaning (unlike a credit/return) - an error, not a warning.
                    issues.append(ValidationIssue(
                        idx, "quantity_on_hand", IssueSeverity.ERROR,
                        f"Negative quantity on hand: {raw_quantity!r}",
                    ))
                # quantity == 0 is deliberately NOT flagged - a genuinely out-of-stock item is a
                # normal, real state, not a data-quality signal.
            except InvalidOperation:
                issues.append(ValidationIssue(
                    idx, "quantity_on_hand", IssueSeverity.ERROR, f"Malformed quantity: {raw_quantity!r}",
                ))

        for field_name, label in (("unit_cost", "unit cost"), ("reorder_level", "reorder level")):
            raw_value = row.get(field_name)
            if raw_value and str(raw_value).strip():
                try:
                    value = Decimal(str(raw_value).replace(",", "").replace("R", "").strip())
                    if value < 0:
                        issues.append(ValidationIssue(
                            idx, field_name, IssueSeverity.WARNING, f"Negative {label}: {raw_value!r} - confirm intentional",
                        ))
                except InvalidOperation:
                    issues.append(ValidationIssue(idx, field_name, IssueSeverity.WARNING, f"Malformed {label}: {raw_value!r} - ignored"))

        raw_expiry = row.get("expiry_date")
        if raw_expiry and str(raw_expiry).strip():
            try:
                date.fromisoformat(str(raw_expiry).strip()[:10])
            except ValueError:
                issues.append(ValidationIssue(
                    idx, "expiry_date", IssueSeverity.WARNING, f"Malformed expiry date: {raw_expiry!r} - ignored",
                ))

        if not row.get("location"):
            issues.append(ValidationIssue(
                idx, "location", IssueSeverity.ERROR, "Missing location - cannot resolve to a real Location record",
            ))

        is_valid = not any(i.severity == IssueSeverity.ERROR for i in issues)
        results.append({"row_number": idx, "is_valid": is_valid, "issues": issues})

    return results
