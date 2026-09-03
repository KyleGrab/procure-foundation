"""
Import validation (spec Section 4). Every check returns a ValidationIssue tied back to the
source row number, so an error is always traceable to "row 47 of new_price_list.xlsx" - never a
bare "some rows failed." Errors block the row from analysis; warnings don't, but both are always
shown to the user (spec: "never hide source-data limitations").
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    row_number: int
    field: str
    severity: IssueSeverity
    message: str


@dataclass(frozen=True)
class ValidatedRow:
    row_number: int
    supplier_sku: str | None
    description: str | None
    price: Decimal | None
    pack_size: str | None
    issues: list[ValidationIssue]

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == IssueSeverity.ERROR for i in self.issues)


def _parse_price(raw: str | None) -> tuple[Decimal | None, ValidationIssue | None]:
    if raw is None or str(raw).strip() == "":
        return None, None  # missing price reported separately by the caller (distinct check)
    cleaned = str(raw).replace(",", "").replace("R", "").strip()
    try:
        return Decimal(cleaned), None
    except InvalidOperation:
        return None, ValidationIssue(0, "price", IssueSeverity.ERROR, f"Malformed price: {raw!r}")


def validate_rows(rows: list[dict[str, str | None]]) -> list[ValidatedRow]:
    validated: list[ValidatedRow] = []
    seen_skus: dict[str, int] = {}

    for idx, row in enumerate(rows, start=1):
        issues: list[ValidationIssue] = []

        sku = (row.get("supplier_sku") or "").strip() or None
        description = (row.get("description") or "").strip() or None
        pack_size = (row.get("pack_size") or "").strip() or None
        raw_price = row.get("price")

        if not sku:
            issues.append(ValidationIssue(idx, "supplier_sku", IssueSeverity.ERROR, "Missing product identifier"))
        if not description:
            issues.append(ValidationIssue(idx, "description", IssueSeverity.ERROR, "Missing product description"))

        price, price_error = _parse_price(raw_price)
        if raw_price is None or str(raw_price).strip() == "":
            issues.append(ValidationIssue(idx, "price", IssueSeverity.ERROR, "Missing price"))
        elif price_error:
            issues.append(ValidationIssue(idx, "price", IssueSeverity.ERROR, price_error.message))
        elif price is not None and price < 0:
            issues.append(ValidationIssue(idx, "price", IssueSeverity.ERROR, f"Negative price: {price}"))
        elif price is not None and price == 0:
            issues.append(ValidationIssue(idx, "price", IssueSeverity.WARNING, "Zero price - confirm this is intentional"))

        if sku:
            if sku in seen_skus:
                issues.append(ValidationIssue(
                    idx, "supplier_sku", IssueSeverity.ERROR,
                    f"Duplicate supplier SKU (first seen at row {seen_skus[sku]})",
                ))
            else:
                seen_skus[sku] = idx

        if not pack_size:
            issues.append(ValidationIssue(idx, "pack_size", IssueSeverity.WARNING, "Missing pack size - cannot normalize unit price"))

        validated.append(ValidatedRow(idx, sku, description, price, pack_size, issues))

    return validated


def summarize_issues(validated_rows: list[ValidatedRow]) -> dict[str, int]:
    errors = sum(1 for r in validated_rows for i in r.issues if i.severity == IssueSeverity.ERROR)
    warnings = sum(1 for r in validated_rows for i in r.issues if i.severity == IssueSeverity.WARNING)
    valid_rows = sum(1 for r in validated_rows if r.is_valid)
    return {"total_rows": len(validated_rows), "valid_rows": valid_rows, "errors": errors, "warnings": warnings}


def serialize_validation_issues(issues: list[ValidationIssue]) -> list[dict]:
    """
    Turns ValidationIssue objects into the list[dict] shape ProcureIQError.details expects (see
    app/core/exceptions.py) - one place this happens, reused by any route returning a 422 with
    field-level diagnostics, rather than each route hand-assembling the same dict shape. severity
    is always the enum's plain string value ("error"/"warning"), never the Enum member itself -
    a raw IssueSeverity.ERROR would serialize incorrectly (or fail outright) in a JSON response.
    """
    return [
        {"row_number": issue.row_number, "field": issue.field, "severity": issue.severity.value, "message": issue.message}
        for issue in issues
    ]
