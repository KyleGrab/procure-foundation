"""
The five-savings-type discipline (analytics-methodology.md §7, spec Section 34) as actual code,
not just a column constraint. Each function requires exactly the inputs its type needs - it
should be structurally awkward to compute a hard_saving figure using working_capital's inputs,
because they answer genuinely different financial questions (profitability vs. cash position vs.
risk avoided vs. margin preserved vs. time saved) and blending them is exactly what
analytics-methodology.md §7 calls "the fastest way to lose Finance's trust."
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


class SavingsType(str, Enum):
    HARD_SAVING = "hard_saving"
    COST_AVOIDANCE = "cost_avoidance"
    WORKING_CAPITAL = "working_capital"
    MARGIN_PROTECTION = "margin_protection"
    EFFICIENCY_SAVING = "efficiency_saving"


class BaselineMethodology(str, Enum):
    """analytics-methodology.md §7: baseline methodology is always stored alongside the figure -
    a savings number with no stated baseline is not auditable, same principle as PPV's
    reference_price_source (Phase 4c)."""
    HISTORIC_AVERAGE_PRICE = "historic_average_price"
    PRIOR_SUPPLIER_PRICE = "prior_supplier_price"
    BUDGET = "budget"
    CONTRACT_PRICE = "contract_price"
    APPROVED_QUOTATION = "approved_quotation"


@dataclass(frozen=True)
class SavingsResult:
    savings_type: SavingsType
    amount: Decimal
    baseline_methodology: BaselineMethodology | None
    is_one_time: bool  # working_capital is one-time cash release; the other four are recurring


def calculate_hard_saving(
    baseline_unit_cost: Decimal, new_unit_cost: Decimal, annual_quantity: Decimal,
    baseline_methodology: BaselineMethodology,
) -> SavingsResult:
    """Actual, measurable cost reduction - the spec's own worked example (Section 35):
    (baseline - new) * annual_quantity."""
    amount = round_currency((baseline_unit_cost - new_unit_cost) * annual_quantity)
    return SavingsResult(SavingsType.HARD_SAVING, amount, baseline_methodology, is_one_time=False)


def calculate_cost_avoidance(
    requested_price: Decimal, negotiated_or_target_price: Decimal, annual_quantity: Decimal,
) -> SavingsResult:
    """Future increase prevented or reduced - no baseline_methodology needed (there's no prior
    price being compared against, only a requested one that didn't fully materialize). This is
    the same formula as Phase 2's calculate_potential_cost_avoidance /
    calculate_actual_cost_avoidance, generalized here as the savings-register entry point for
    that figure - not a third reimplementation of the same math."""
    amount = round_currency((requested_price - negotiated_or_target_price) * annual_quantity)
    return SavingsResult(SavingsType.COST_AVOIDANCE, amount, None, is_one_time=False)


def calculate_working_capital_release(
    daily_relevant_spend: Decimal, current_terms_days: int, proposed_terms_days: int,
) -> SavingsResult:
    """analytics-methodology.md §6's exact formula. is_one_time=True is not a detail - this is
    the figure that must NEVER be summed with the other four on a dashboard total, because it
    answers a cash-position question, not a profitability one."""
    amount = round_currency(daily_relevant_spend * Decimal(proposed_terms_days - current_terms_days))
    return SavingsResult(SavingsType.WORKING_CAPITAL, amount, None, is_one_time=True)


def calculate_margin_protection(
    margin_at_risk_pct: Decimal, protected_revenue: Decimal,
) -> SavingsResult:
    """Margin preserved by an action (e.g. successfully resisting a price increase that would
    have eroded margin) - measured against revenue the margin applies to, not a unit-cost
    baseline, which is why this takes different inputs from calculate_hard_saving even though
    both eventually produce a Rand figure."""
    amount = round_currency(margin_at_risk_pct * protected_revenue)
    return SavingsResult(SavingsType.MARGIN_PROTECTION, amount, None, is_one_time=False)


def calculate_efficiency_saving(
    hours_saved_annually: Decimal, fully_loaded_hourly_rate: Decimal,
) -> SavingsResult:
    """Time/process reduction, converted to a Rand figure via a stated hourly rate - never
    blended with hard savings even though both end up denominated in currency, because one
    reflects cash that actually moves and the other reflects capacity freed up."""
    amount = round_currency(hours_saved_annually * fully_loaded_hourly_rate)
    return SavingsResult(SavingsType.EFFICIENCY_SAVING, amount, None, is_one_time=False)


@dataclass(frozen=True)
class SavingsWaterfallTotals:
    identified: Decimal
    validated: Decimal
    approved: Decimal
    implementation: Decimal
    realised: Decimal


def calculate_savings_waterfall(
    opportunities: list[tuple[str, Decimal, bool]],
) -> SavingsWaterfallTotals:
    """
    opportunities: (status, amount, is_one_time) tuples. spec Section 85's waterfall (identified
    -> validated -> approved -> implementation -> realised) shows the value AT each stage, not a
    running cumulative total across stages - an opportunity contributes to exactly one stage
    total, its current one, not to every stage it has already passed through.
    """
    stages = ("identified", "validated", "approved", "implementation", "realised")
    totals = {stage: Decimal("0") for stage in stages}
    for status, amount, _is_one_time in opportunities:
        if status in totals:
            totals[status] += amount
    return SavingsWaterfallTotals(**{stage: round_currency(totals[stage]) for stage in stages})
