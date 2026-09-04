"""
Phase 5b (ADR-018) inventory calculations. Pure `Decimal`/`date`/`dataclass` - no SQLAlchemy, no
FastAPI - same §2.1 boundary as every analytics module in this codebase.

No `product_id` anywhere here - confirmed before this module was written that no `products` table
exists in ProcureIQ (deliberate since Phase 2, restated in ADR-015/ADR-018). Item identity is
`description` (+ optional `supplier_sku`), matching purchase_invoice_lines/purchase_transactions/
price_review_lines - the same convention, not a fourth one.

`as_of` is always a caller-supplied parameter, never `datetime.now()` called inside a function
here - same non-negotiable determinism rule as domain_graph.py (tests_pure checks this
structurally, not just functionally).

calculate_days_since_last_movement is an honest proxy, not a real turnover rate: no sales/
consumption fact table exists in this schema (sales_facts is also unbuilt - data-model.md), so
"movement" here means "quantity_on_hand decreased between two consecutive snapshots for the same
grain key" - a restock (increase) is explicitly not movement, and is not allowed to reset the
measurement.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class SnapshotRow:
    description: str
    supplier_sku: str | None
    location_id: int
    snapshot_date: date
    row_index: int  # position in the uploaded batch - referenced by GrainViolation, not used in
    # the grain key itself


@dataclass(frozen=True)
class GrainViolation:
    key: tuple[str, str | None, int, date]
    row_indices: list[int]


def validate_snapshot_grain(rows: list[SnapshotRow]) -> list[GrainViolation]:
    """
    Grain invariant: (description, supplier_sku, location_id, snapshot_date) must be unique - two
    rows sharing a key mean the same item, same place, same day was uploaded twice with no way to
    know which is authoritative. Flagged explicitly (§2.2's "row-count-in must equal row-count-out
    for any transform that isn't an explicit aggregation" - this is the same discipline applied at
    ingestion time, before anything downstream aggregates over a duplicated key), never silently
    allowed or silently deduplicated.
    """
    rows_by_key: dict[tuple[str, str | None, int, date], list[int]] = defaultdict(list)
    for row in rows:
        key = (row.description, row.supplier_sku, row.location_id, row.snapshot_date)
        rows_by_key[key].append(row.row_index)
    return [
        GrainViolation(key=key, row_indices=indices)
        for key, indices in rows_by_key.items()
        if len(indices) > 1
    ]


def calculate_days_since_last_movement(
    ordered_snapshots: list[tuple[date, Decimal]], as_of: date,
) -> int | None:
    """
    ordered_snapshots: (snapshot_date, quantity_on_hand) for ONE grain key, already sorted
    ascending by date by the caller (same documented-not-enforced assumption as
    calculate_abc_classification's sorted-input requirement).

    Returns None with fewer than 2 snapshots (no transition is observable at all). Otherwise scans
    backwards for the most recent snapshot where quantity decreased from the one before it - that
    date is "the last confirmed movement." If quantity never decreased across the whole series,
    returns days since the earliest snapshot ("no confirmed movement for at least this long"), not
    None - 2+ snapshots with no observed decrease is still real information, not missing data.
    """
    if len(ordered_snapshots) < 2:
        return None

    for i in range(len(ordered_snapshots) - 1, 0, -1):
        current_date, current_qty = ordered_snapshots[i]
        _prior_date, prior_qty = ordered_snapshots[i - 1]
        if current_qty < prior_qty:
            return (as_of - current_date).days

    earliest_date, _ = ordered_snapshots[0]
    return (as_of - earliest_date).days


def calculate_excess_stock_value(
    quantity_on_hand: Decimal, reorder_level: Decimal | None, unit_cost: Decimal | None,
) -> Decimal | None:
    """excess = max(0, quantity_on_hand - reorder_level) * unit_cost. None if either baseline
    input is missing - never a fabricated reorder level or a guessed unit cost (same "no stated
    baseline, no figure" rule as PPV's reference_price and hard_saving's baseline_methodology)."""
    if reorder_level is None or unit_cost is None:
        return None
    excess_quantity = max(Decimal(0), quantity_on_hand - reorder_level)
    return round_currency(excess_quantity * unit_cost)


class ExpiryRisk(str, Enum):
    NO_EXPIRY_TRACKED = "no_expiry_tracked"
    EXPIRED = "expired"
    EXPIRING_SOON = "expiring_soon"
    HEALTHY = "healthy"


def classify_expiry_risk(
    expiry_date: date | None, as_of: date, warning_window_days: int = 30,
) -> ExpiryRisk:
    """warning_window_days is a parameter, not a hardcoded business decision (§2.4) - an
    organisation stocking fresh produce and one stocking canned goods need very different
    windows. Boundary is inclusive: exactly warning_window_days out counts as expiring_soon, not
    healthy - the more conservative reading of an ambiguous edge case for something that
    determines whether stock gets flagged for action."""
    if expiry_date is None:
        return ExpiryRisk.NO_EXPIRY_TRACKED
    if expiry_date < as_of:
        return ExpiryRisk.EXPIRED
    days_until_expiry = (expiry_date - as_of).days
    if days_until_expiry <= warning_window_days:
        return ExpiryRisk.EXPIRING_SOON
    return ExpiryRisk.HEALTHY
