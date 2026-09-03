"""
Deterministic spend analytics (spec Sections 20-23, 27's Pareto/ABC references, Phase 5). Pure
`Decimal`/stdlib - no DB, no network - same pattern as every analytics module this session. See
docs/phase5-opportunity-engine-plan.md §2.1-2.2 for the two scope reconciliations this module
embodies: spend groups by free-text SKU/description (no product catalog exists), and price
consistency (§23) is a genuinely different question from Phase 4c's PPV, not a duplicate of it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class SpendItem:
    key: str  # supplier_id, sku, or month label - whatever the caller is grouping by
    label: str
    amount: Decimal


def aggregate_spend(rows: list[tuple[str, str, Decimal]]) -> list[SpendItem]:
    """rows: (key, label, amount) tuples - e.g. (supplier_id, supplier_name, line_net_amount)
    from purchase_invoice_lines, or (sku, description, amount) from either ledger. Sums by key,
    sorted highest-spend-first (the natural order for every downstream use: ABC, Pareto, a
    ranked table)."""
    totals: dict[str, Decimal] = {}
    labels: dict[str, str] = {}
    for key, label, amount in rows:
        totals[key] = totals.get(key, Decimal("0")) + amount
        labels[key] = label
    items = [SpendItem(key, labels[key], round_currency(total)) for key, total in totals.items()]
    return sorted(items, key=lambda i: -i.amount)


class ABCClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


@dataclass(frozen=True)
class ABCResult:
    item: SpendItem
    cumulative_pct: Decimal
    classification: ABCClass


def calculate_abc_classification(
    items: list[SpendItem], *,
    a_threshold_pct: Decimal = Decimal("0.80"), b_threshold_pct: Decimal = Decimal("0.95"),
) -> list[ABCResult]:
    """
    Cumulative-spend banding. Default 80/95 (A = top 80% of cumulative spend, B = next 15% up to
    95%, C = the long tail) - organisation-configurable via organisation_settings
    (ADR-004's pattern), never hardcoded as a business decision baked into the function.
    items must already be sorted highest-first (aggregate_spend does this) - this function
    doesn't re-sort, so a caller passing unsorted items gets a wrong-but-silent answer if it did;
    documented here rather than defended against, since re-sorting silently would hide a caller
    bug instead of surfacing it.
    """
    total = sum((i.amount for i in items), Decimal("0"))
    if total == 0:
        return [ABCResult(i, Decimal("0"), ABCClass.C) for i in items]

    results = []
    running = Decimal("0")
    for item in items:
        running += item.amount
        cumulative_pct = round_currency(running / total * 100) / Decimal("100")
        if cumulative_pct <= a_threshold_pct:
            classification = ABCClass.A
        elif cumulative_pct <= b_threshold_pct:
            classification = ABCClass.B
        else:
            classification = ABCClass.C
        results.append(ABCResult(item, cumulative_pct, classification))
    return results


@dataclass(frozen=True)
class ParetoResult:
    contributors: list[SpendItem]
    contributor_count: int
    total_item_count: int
    cumulative_pct_covered: Decimal


def calculate_pareto_contributors(items: list[SpendItem], target_pct: Decimal = Decimal("0.80")) -> ParetoResult:
    """The "top suppliers/SKUs accounting for 80% of spend" figure (spec Section 21), as its own
    view distinct from ABC banding - ABC classifies every item, this answers "how few items does
    it actually take" which is the number that goes in an executive summary."""
    total = sum((i.amount for i in items), Decimal("0"))
    if total == 0:
        return ParetoResult([], 0, len(items), Decimal("0"))

    contributors = []
    running = Decimal("0")
    for item in items:
        contributors.append(item)
        running += item.amount
        if running / total >= target_pct:
            break
    cumulative_pct = round_currency(running / total * 100) / Decimal("100")
    return ParetoResult(contributors, len(contributors), len(items), cumulative_pct)


@dataclass(frozen=True)
class MonthOverMonthPoint:
    month_label: str  # "2026-01"
    amount: Decimal
    change_pct: Decimal | None  # vs. prior month; None for the first point in the series


def calculate_month_over_month_trend(monthly_totals: list[tuple[str, Decimal]]) -> list[MonthOverMonthPoint]:
    """
    monthly_totals: (month_label, amount) tuples, already aggregated and sorted chronologically by
    the caller (this function doesn't sort - a caller passing an unsorted series gets a
    wrong-but-silent trend, same documented tradeoff as calculate_abc_classification's sorted-input
    assumption). change_pct is None for the first point (no prior month to compare against) and
    when the prior month's amount was zero (a percentage change from zero is undefined, not 0% or
    an error - same rule as calculate_percentage_change in price_review_calculations.py).
    """
    points = []
    prior_amount: Decimal | None = None
    for month_label, amount in monthly_totals:
        change_pct = None
        if prior_amount is not None and prior_amount != 0:
            change_pct = round_currency((amount - prior_amount) / prior_amount * 100) / Decimal("100")
        points.append(MonthOverMonthPoint(month_label, round_currency(amount), change_pct))
        prior_amount = amount
    return points


@dataclass(frozen=True)
class PriceObservation:
    price: Decimal
    observed_date: date
    location_label: str | None = None


@dataclass(frozen=True)
class PriceConsistencyResult:
    min_price: Decimal
    max_price: Decimal
    spread: Decimal
    spread_pct: Decimal | None  # relative to min_price; None if min_price is zero
    is_significant: bool
    observation_count: int


def calculate_price_consistency(
    observations: list[PriceObservation], *, significance_threshold_pct: Decimal = Decimal("0.05"),
) -> PriceConsistencyResult:
    """
    Spec Section 23: same SKU, same supplier, different prices paid across purchases/locations -
    a genuinely different question from PPV (app.analytics.purchase_ledger_calculations), which
    compares one price against one stated reference. This compares purchases against each other,
    no reference price required or even meaningful here.

    significance_threshold_pct is organisation-configurable, not fixed - a R2 spread on a R4 item
    and a R2 spread on a R4,000 item are not the same signal, which is exactly why this returns
    the relative spread_pct alongside is_significant rather than a caller having to compute it.
    """
    if not observations:
        raise ValueError("observations must not be empty")
    prices = [o.price for o in observations]
    min_price, max_price = min(prices), max(prices)
    spread = round_currency(max_price - min_price)
    spread_pct = None if min_price == 0 else round_currency(spread / min_price * 100) / Decimal("100")
    is_significant = spread_pct is not None and spread_pct >= significance_threshold_pct
    return PriceConsistencyResult(min_price, max_price, spread, spread_pct, is_significant, len(observations))
