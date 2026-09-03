"""
Every deterministic financial function for the price-review workflow (spec Section 38), matching
docs/analytics-methodology.md's rules: Decimal only, ROUND_HALF_EVEN, round once at
persist/display time and never mid-calculation. This module is called from the price-review
service layer - nothing computes one of these figures inline anywhere else in the app.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")  # NUMERIC(18,4) storage precision
PERCENT_QUANTIZE = Decimal("0.000001")  # NUMERIC(9,6) storage precision


class PriceReviewMatchStatus(str, Enum):
    """Compliance finding 2: 16 bare string-literal occurrences across price_review_service.py
    and price_reviews.py before this. Deliberately separate from app.matching.scorer.MatchStatus
    (a different concept - that one is a single candidate pairing's confidence tier during
    matching; this one is the persisted outcome on a PriceReviewLine). Also deliberately does NOT
    cover movement_type's overlapping vocabulary ('review_required'/'discontinued'/'new_product'
    appear in both) - that's a related but separate field, out of this finding's stated scope,
    noted as a follow-up candidate rather than silently swept in here."""
    MATCHED = "matched"
    NEW_PRODUCT = "new_product"
    DISCONTINUED = "discontinued"
    REVIEW_REQUIRED = "review_required"
    IGNORED = "ignored"


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def round_percentage(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_QUANTIZE, rounding=ROUND_HALF_EVEN)


def calculate_price_change(old_price: Decimal, new_price: Decimal) -> Decimal:
    return round_currency(new_price - old_price)


def calculate_percentage_change(old_price: Decimal, new_price: Decimal) -> Decimal | None:
    """None (not zero, not an error) when old_price is zero - a percentage change from zero is
    undefined, and reporting 0% or a fabricated huge number are both wrong. Callers must handle
    None explicitly (spec Section 39 requires a dedicated 'zero old price' test)."""
    if old_price == 0:
        return None
    return round_percentage((new_price - old_price) / old_price)


def calculate_normalized_unit_price(total_price: Decimal, base_quantity: Decimal) -> Decimal:
    if base_quantity == 0:
        raise ValueError("base_quantity is zero - cannot normalize a unit price")
    return round_currency(total_price / base_quantity)


def calculate_annualized_quantity(
    observed_quantity: Decimal, months_observed: Decimal
) -> tuple[Decimal, str]:
    """Returns (annualized_quantity, confidence_tier) per docs/phase2-price-review-plan.md's
    manual-entry decision and spec Section 32's tiers. months_observed=12 is the only case that
    isn't an estimate."""
    if months_observed <= 0:
        raise ValueError("months_observed must be positive")
    annualized = observed_quantity * (Decimal("12") / months_observed)
    if months_observed >= 12:
        confidence = "high"
    elif months_observed >= 6:
        confidence = "medium"
    else:
        confidence = "low"
    return annualized.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN), confidence


def calculate_annual_impact(price_change: Decimal, annual_quantity: Decimal) -> Decimal:
    return round_currency(price_change * annual_quantity)


def determine_comparison_basis(
    old_normalized_price: Decimal | None, new_normalized_price: Decimal | None,
    old_base_unit: str | None, new_base_unit: str | None,
) -> str:
    """
    Compliance finding (docs/compliance-review-2026-08.md, Finding 1): calculate_line_movement in
    price_review_service.py used to resolve old/new comparison prices independently
    (`old_normalized_price or old_price`), which meant a line where normalization succeeded for
    one side and failed for the other silently compared incompatible units (a per-kg price
    against a raw case price) with no signal anywhere that it happened.

    Returns one of:
    - 'normalized': both sides normalized AND to the same base unit - genuinely comparable.
    - 'raw': neither side normalized - both are raw prices, comparable as raw prices (existing
      behavior, unchanged - this does not itself guarantee pack sizes match, only that both
      figures are the same *kind* of number; `pack_changed` is the separate signal for that).
    - 'unit_mismatch': exactly one side normalized, OR both normalized but to different base
      units (e.g. one to 'L', the other to 'kg' - genuinely different measurement types). Either
      way, the two figures are not safely comparable and the caller must refuse to compute a
      movement from them, not silently combine them.
    """
    old_normalized = old_normalized_price is not None
    new_normalized = new_normalized_price is not None

    if old_normalized and new_normalized:
        return "normalized" if old_base_unit == new_base_unit else "unit_mismatch"
    if not old_normalized and not new_normalized:
        return "raw"
    return "unit_mismatch"


def calculate_gross_margin(selling_price: Decimal, cost: Decimal) -> tuple[Decimal, Decimal]:
    """Returns (gross_profit, gross_margin_pct). gross_margin_pct is None-able via ValueError on
    zero selling price - callers decide whether that's a data-quality error to surface."""
    if selling_price == 0:
        raise ValueError("selling_price is zero - cannot compute a margin percentage")
    gross_profit = selling_price - cost
    return round_currency(gross_profit), round_percentage(gross_profit / selling_price)


def calculate_required_selling_price(cost: Decimal, target_margin_pct: Decimal) -> Decimal:
    if target_margin_pct >= 1:
        raise ValueError("target_margin_pct must be less than 1 (e.g. 0.30 for 30%)")
    return round_currency(cost / (Decimal("1") - target_margin_pct))


def calculate_potential_cost_avoidance(
    requested_new_price: Decimal, target_price: Decimal, annual_quantity: Decimal
) -> Decimal:
    """Spec Section 23 - explicitly NOT hard savings, a potential figure pending negotiation."""
    return round_currency((requested_new_price - target_price) * annual_quantity)


def calculate_actual_cost_avoidance(
    requested_new_price: Decimal, final_negotiated_price: Decimal, annual_quantity: Decimal
) -> Decimal:
    """Spec Section 24 - computed once a negotiated outcome is recorded, kept separate from
    hard savings / working capital / margin protection per analytics-methodology.md Section 7."""
    return round_currency((requested_new_price - final_negotiated_price) * annual_quantity)


def classify_risk(
    percentage_change: Decimal | None,
    *,
    low_max: Decimal = Decimal("0.02"),
    medium_max: Decimal = Decimal("0.05"),
    high_max: Decimal = Decimal("0.10"),
) -> str:
    """Default thresholds per spec Section 16 (0-2/2-5/5-10/10+). Organisation-configurable in
    the DB layer via organisation_settings (ADR-004) - this function just applies whatever
    thresholds it's given, it never hardcodes a business decision beyond the documented default."""
    if percentage_change is None:
        return "unclassified"
    magnitude = abs(percentage_change)
    if magnitude <= low_max:
        return "low"
    if magnitude <= medium_max:
        return "medium"
    if magnitude <= high_max:
        return "high"
    return "critical"


def classify_movement_type(
    *, is_matched: bool, is_new: bool, is_discontinued: bool,
    pack_changed: bool, percentage_change: Decimal | None,
) -> str:
    if is_new:
        return "new_product"
    if is_discontinued:
        return "discontinued"
    if not is_matched:
        return "review_required"
    if pack_changed:
        return "pack_change"
    if percentage_change is None:
        return "review_required"
    if percentage_change > 0:
        return "price_increase"
    if percentage_change < 0:
        return "price_decrease"
    return "no_change"
