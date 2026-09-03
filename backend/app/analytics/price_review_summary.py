"""
Supplier-level summary aggregation (spec Section 19). The one explicit rule here: the headline
weighted-average price increase MUST be spend- or volume-weighted, never a naive mean of
percentage changes across SKUs - a naive average lets one tiny high-percentage SKU distort the
number that ends up in front of the buyer.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.analytics.price_review_calculations import round_percentage


@dataclass(frozen=True)
class PriceReviewLineForSummary:
    movement_type: str
    percentage_change: Decimal | None
    annual_impact: Decimal | None
    annual_quantity: Decimal | None
    pack_changed: bool
    requires_review: bool


@dataclass(frozen=True)
class SupplierSummary:
    total_previous_skus: int
    total_new_skus: int
    matched_skus: int
    unmatched_skus: int
    new_skus: int
    discontinued_skus: int
    increasing_skus: int
    decreasing_skus: int
    unchanged_skus: int
    pack_changes: int
    weighted_average_price_increase_pct: Decimal | None
    annual_cost_impact: Decimal
    products_requiring_manual_review: int


def weighted_average_increase(lines: list[PriceReviewLineForSummary]) -> Decimal | None:
    """Weighted by annual_quantity's contribution to annual spend at the old price - a line with
    no quantity data contributes nothing to the weighted figure (it can't be silently treated as
    zero weight AND zero impact, that would understate the number; it's simply excluded, and the
    UI must show how many lines were excluded via products_requiring_manual_review /
    low-confidence counts elsewhere)."""
    numerator = Decimal("0")
    denominator = Decimal("0")
    for line in lines:
        if line.percentage_change is None or line.annual_quantity is None:
            continue
        if line.movement_type not in ("price_increase", "price_decrease", "no_change", "pack_change"):
            continue
        numerator += line.percentage_change * line.annual_quantity
        denominator += line.annual_quantity
    if denominator == 0:
        return None
    return round_percentage(numerator / denominator)


def summarize(
    lines: list[PriceReviewLineForSummary], *, total_previous_skus: int, total_new_skus: int
) -> SupplierSummary:
    matched = [l for l in lines if l.movement_type not in ("new_product", "discontinued", "review_required")]
    increasing = [l for l in matched if l.movement_type == "price_increase"]
    decreasing = [l for l in matched if l.movement_type == "price_decrease"]
    unchanged = [l for l in matched if l.movement_type == "no_change"]
    pack_changes = [l for l in lines if l.pack_changed]
    new_products = [l for l in lines if l.movement_type == "new_product"]
    discontinued = [l for l in lines if l.movement_type == "discontinued"]
    review_required = [l for l in lines if l.requires_review]

    annual_cost_impact = sum(
        (l.annual_impact for l in lines if l.annual_impact is not None), Decimal("0")
    )

    return SupplierSummary(
        total_previous_skus=total_previous_skus,
        total_new_skus=total_new_skus,
        matched_skus=len(matched),
        unmatched_skus=len(lines) - len(matched) - len(new_products) - len(discontinued),
        new_skus=len(new_products),
        discontinued_skus=len(discontinued),
        increasing_skus=len(increasing),
        decreasing_skus=len(decreasing),
        unchanged_skus=len(unchanged),
        pack_changes=len(pack_changes),
        weighted_average_price_increase_pct=weighted_average_increase(lines),
        annual_cost_impact=annual_cost_impact,
        products_requiring_manual_review=len(review_required),
    )
