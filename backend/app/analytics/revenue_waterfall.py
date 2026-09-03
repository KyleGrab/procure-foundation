"""
Gate A revenue layer: Gross Sales -> Net Revenue, before any CTS (cost-to-serve) engine engages.
Pure Decimal/dataclass - no DB, no framework, §2.1.

Two of the seven lines are grounded in real, verified figures (see
tests_pure/test_revenue_waterfall.py's docstring): the real Income Statement structure is
Turnover -> Less: Discount allowed -> Less: Rebates Paid -> Net Sales, and that real subtraction
reconciles exactly (R364,588,837.16 - R8,240,399.16 - R3,145,913.07 = R353,202,524.93, TTM ending
August 2026). The other four lines (credit_notes_issued, operational_claims_returns,
retro_pricing_adjustment, supplier_recoveries_allowances) are a finer-grained proposal beyond
what's been verified in the real P&L - real, plausible, food-distribution-specific deduction
categories, but not yet backed by a real Rand figure anywhere in this engagement.

The one rule this whole module exists to enforce: a missing line is never assumed to be zero.
An "invented zero" for e.g. operational_claims_returns would silently overstate Net Revenue by
exactly however much real claims/returns activity actually happened that period - a wrong number
with no visible sign that anything was wrong. is_complete=False and net_revenue=None instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class GrossToNetWaterfallInput:
    gross_sales: Decimal  # never optional - a waterfall with no starting figure isn't a waterfall
    settlement_discounts: Decimal | None
    volume_growth_rebates: Decimal | None
    credit_notes_issued: Decimal | None
    operational_claims_returns: Decimal | None
    retro_pricing_adjustment: Decimal | None  # signed - a late price correction can go either way
    supplier_recoveries_allowances: Decimal | None  # a recovery ADDS back, same sign convention as retro-pricing


_DEDUCTION_LINES = (
    "settlement_discounts", "volume_growth_rebates", "credit_notes_issued", "operational_claims_returns",
)
_SIGNED_LINES = ("retro_pricing_adjustment", "supplier_recoveries_allowances")


def calculate_gross_to_net_waterfall(inputs: GrossToNetWaterfallInput) -> dict:
    """
    Sequential deduction chain. gross_sales minus settlement_discounts, volume_growth_rebates,
    credit_notes_issued, operational_claims_returns; plus/minus retro_pricing_adjustment and
    supplier_recoveries_allowances (both genuinely signed, not deduction-only).

    Any line left as None means "not yet sourced" - the function refuses to substitute zero.
    is_complete=False, net_revenue=None, missing_lines lists every absent field together (not
    just the first one found), so a caller can report the whole gap in one pass rather than
    discovering it one field at a time across repeated calls.
    """
    all_line_values = {
        "settlement_discounts": inputs.settlement_discounts,
        "volume_growth_rebates": inputs.volume_growth_rebates,
        "credit_notes_issued": inputs.credit_notes_issued,
        "operational_claims_returns": inputs.operational_claims_returns,
        "retro_pricing_adjustment": inputs.retro_pricing_adjustment,
        "supplier_recoveries_allowances": inputs.supplier_recoveries_allowances,
    }
    missing_lines = [name for name, value in all_line_values.items() if value is None]

    if missing_lines:
        return {
            "is_complete": False, "missing_lines": missing_lines, "net_revenue": None,
            "gross_sales": round_currency(inputs.gross_sales),
        }

    net_revenue = inputs.gross_sales
    for line in _DEDUCTION_LINES:
        net_revenue -= all_line_values[line]
    for line in _SIGNED_LINES:
        net_revenue += all_line_values[line]

    result = {
        "is_complete": True, "missing_lines": [], "gross_sales": round_currency(inputs.gross_sales),
        "net_revenue": round_currency(net_revenue),
    }
    for name, value in all_line_values.items():
        result[name] = round_currency(value)
    return result
