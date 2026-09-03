"""
Gate C: the 13-week rolling cash model. Pure Decimal/dict logic - no DB, no framework, §2.1.

Deliberately scoped: this module owns the FORECAST MATH once weekly cash figures are already
resolved. It does NOT compute disputed_amount/unapplied_cash/GRNI from raw AR/AP aging data -
that resolution needs real schema (a disputes table, an unapplied-cash ledger) that doesn't exist
anywhere in this engagement yet, and guessing at its structure now would repeat the exact mistake
already avoided for temperature logs, energy costs, and recall tracking earlier in this
engagement. What IS built is the boundary contract: resolve_weekly_cash_receipts/
resolve_weekly_supplier_payments take already-known figures and combine them correctly; nothing
here can silently substitute a fabricated zero for a missing one, since none of the parameters in
this whole module have a default.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def resolve_weekly_cash_receipts(
    contractual_dso_expected_receipts: Decimal, disputed_amount: Decimal, unapplied_cash: Decimal,
) -> Decimal:
    """
    True expected cash receipts for the week = contractual DSO-based expected receipts, minus
    amounts under active dispute (won't be collected until resolved - counting a disputed
    invoice as available cash would overstate the forecast and hide the exact liquidity risk
    this model exists to surface), plus unapplied cash already received but not yet matched to a
    specific invoice (it IS real cash sitting in the bank, just not yet allocated - excluding it
    would understate real, available cash just as badly as including a dispute would overstate it).
    """
    return round_currency(contractual_dso_expected_receipts - disputed_amount + unapplied_cash)


def resolve_weekly_supplier_payments(
    contractual_dpo_expected_payments: Decimal, grni_amount: Decimal,
) -> Decimal:
    """
    GRNI (Goods Received Not Invoiced - real, traceable against this codebase's actual
    GoodsReceipt table, confirmed before this was written) represents real supplier obligations
    already incurred (goods physically received) but not yet reflected in a payable invoice - a
    genuine forward cash outflow a contractual-DPO-only schedule would miss entirely, since DPO
    is computed from INVOICED amounts only (calculate_working_capital_metrics' own dpo formula).
    Added, not subtracted - GRNI is additional expected outflow, a real liability the business
    will need to pay once invoiced, not an offset against what's already forecast.
    """
    return round_currency(contractual_dpo_expected_payments + grni_amount)


def calculate_weekly_cash_position(
    starting_cash: Decimal, resolved_cash_receipts: Decimal, forced_supplier_payments: Decimal,
    gate_b_operational_cost_pools: Decimal,
) -> dict:
    """
    Weekly Cash Position = Starting Cash + Resolved Cash Receipts - Forced Supplier Payments -
    Gate B Operational Cost Pools - the exact formula this request specifies. All four inputs
    are required, no defaults anywhere on this function - a missing figure must never be
    silently treated as zero (Chaos Audit Domain 1's own discipline, applied here from the
    start rather than retrofitted after the fact).

    is_overdraft flags a negative ending_cash explicitly - the "stark liquidity risk indicator"
    this request names directly, made a first-class, queryable field rather than left for the
    caller to infer from a bare negative number, same pattern as calculate_allocation_variance's
    is_undercosted.
    """
    ending_cash = round_currency(
        starting_cash + resolved_cash_receipts - forced_supplier_payments - gate_b_operational_cost_pools
    )
    return {"ending_cash": ending_cash, "is_overdraft": ending_cash < 0}


_REQUIRED_WEEKLY_KEYS = ("resolved_cash_receipts", "forced_supplier_payments", "gate_b_operational_cost_pools")


def build_13_week_cash_forecast(opening_cash: Decimal, weekly_inputs: list[dict]) -> dict:
    """
    opening_cash has no default (the current bank ledger balance, named explicitly in this
    request as the one input that must never silently default to zero) - omitting it is a
    TypeError at the call site, not a fabricated opening position.

    weekly_inputs must be exactly 13 dicts, each with resolved_cash_receipts/
    forced_supplier_payments/gate_b_operational_cost_pools already resolved (via
    resolve_weekly_cash_receipts/resolve_weekly_supplier_payments upstream, or a direct known
    figure). ANY missing key or None value in ANY single week locks the WHOLE forecast -
    is_complete=False, weeks=None - never a partial result presented as if the full 13-week
    horizon were resolved when only some weeks actually are. This is the explicit Gate C rule:
    a forecast "complete except for week 7" does not exist as a concept in this function.
    """
    if len(weekly_inputs) != 13:
        return {
            "is_complete": False, "weeks": None,
            "error": f"expected exactly 13 weeks of input, got {len(weekly_inputs)}",
        }

    for week_num, week in enumerate(weekly_inputs, start=1):
        missing = [key for key in _REQUIRED_WEEKLY_KEYS if week.get(key) is None]
        if missing:
            return {"is_complete": False, "weeks": None, "error": f"week {week_num} missing: {missing}"}

    weeks: list[dict] = []
    running_cash = opening_cash
    first_overdraft_week: int | None = None

    for week_num, week in enumerate(weekly_inputs, start=1):
        position = calculate_weekly_cash_position(
            starting_cash=running_cash, resolved_cash_receipts=week["resolved_cash_receipts"],
            forced_supplier_payments=week["forced_supplier_payments"],
            gate_b_operational_cost_pools=week["gate_b_operational_cost_pools"],
        )
        weeks.append({"week": week_num, **position})
        if position["is_overdraft"] and first_overdraft_week is None:
            first_overdraft_week = week_num
        running_cash = position["ending_cash"]

    return {"is_complete": True, "weeks": weeks, "error": None, "first_overdraft_week": first_overdraft_week}
