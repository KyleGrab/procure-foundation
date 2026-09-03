"""
Gourmet-style Inventory Valuation Report row validation. Purpose-built, matching this sprint's
established pattern (working_capital_validation.py, aging_validation.py) rather than reused from
Phase 5b's inventory_validation.py, which validates a different real shape (a stocktake snapshot
with location/expiry_date - this validates a valuation-report row with a cross-field arithmetic
check that Phase 5b's validator has no reason to know about).

total_valuation is NOT one of InventorySnapshot's real columns (see the mapping module's
docstring) - it exists here only as a cross-check against quantity_on_hand * unit_cost, flagged
as a WARNING when it disagrees beyond a R0.01 tolerance, never persisted as a third,
independently-drifting figure and never a reason to reject the row (the row's actual stored
fields - sku, quantity, unit_cost - remain correct and usable even when the source's own
pre-computed total column is slightly off).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.ingestion.validation import IssueSeverity, ValidationIssue

_VALUATION_TOLERANCE = Decimal("0.01")


def _strip_currency(raw: str) -> str:
    return raw.replace("R", "").replace("$", "").replace(",", "").strip()


def validate_inventory_valuation_rows(rows: list[dict[str, str | None]]) -> list[dict]:
    results = []

    for idx, row in enumerate(rows, start=1):
        issues: list[ValidationIssue] = []
        parsed: dict[str, str | Decimal | None] = {}

        supplier_sku = row.get("supplier_sku")
        if not supplier_sku or not str(supplier_sku).strip():
            issues.append(ValidationIssue(idx, "supplier_sku", IssueSeverity.ERROR, "Missing supplier_sku"))
        else:
            parsed["supplier_sku"] = str(supplier_sku).strip()

        parsed["description"] = str(row.get("description") or "").strip() or None

        def _parse_required_decimal(field: str, label: str) -> Decimal | None:
            raw = row.get(field)
            if raw is None or not str(raw).strip():
                issues.append(ValidationIssue(idx, field, IssueSeverity.ERROR, f"Missing {label}"))
                return None
            try:
                return Decimal(_strip_currency(str(raw)))
            except InvalidOperation:
                issues.append(ValidationIssue(idx, field, IssueSeverity.ERROR, f"Malformed {label}: {raw!r}"))
                return None

        quantity = _parse_required_decimal("quantity_on_hand", "quantity on hand")
        if quantity is not None:
            parsed["quantity_on_hand"] = quantity
            if quantity < 0:
                # Flagged per this phase's spec, not rejected - a real (if unusual) back-order/
                # adjustment state, same posture as negative AR/AP in working_capital_validation.
                issues.append(ValidationIssue(
                    idx, "quantity_on_hand", IssueSeverity.WARNING,
                    f"Negative quantity on hand: {quantity} - unusual but not rejected",
                ))

        unit_cost = _parse_required_decimal("unit_cost", "unit cost")
        if unit_cost is not None:
            parsed["unit_cost"] = unit_cost

        raw_total_valuation = row.get("total_valuation")
        if raw_total_valuation is not None and str(raw_total_valuation).strip():
            try:
                total_valuation = Decimal(_strip_currency(str(raw_total_valuation)))
                parsed["total_valuation"] = total_valuation
                if quantity is not None and unit_cost is not None:
                    expected = quantity * unit_cost
                    if abs(total_valuation - expected) > _VALUATION_TOLERANCE:
                        issues.append(ValidationIssue(
                            idx, "total_valuation", IssueSeverity.WARNING,
                            f"total_valuation ({total_valuation}) does not match "
                            f"quantity_on_hand * unit_cost ({expected}) within R{_VALUATION_TOLERANCE} tolerance",
                        ))
            except InvalidOperation:
                issues.append(ValidationIssue(
                    idx, "total_valuation", IssueSeverity.WARNING,
                    f"Malformed total_valuation: {raw_total_valuation!r} - cross-check skipped",
                ))
        # Missing total_valuation entirely is not flagged at all - it's a cross-check field, not
        # a required one; some source formats won't have it.

        is_valid = not any(i.severity == IssueSeverity.ERROR for i in issues)
        results.append({"row_number": idx, "is_valid": is_valid, "issues": issues, "parsed": parsed})

    return results
