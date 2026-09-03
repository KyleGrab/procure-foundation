"""
Phase 6 (CIMA F-pillar): NPV, IRR, discounted payback, capital allowance tax shields, and
speculative-residual-value flagging for long-term capital investment appraisal. Pure Decimal
logic - no DB, no framework, §2.1.

IRR has a real mathematical hazard, not a hypothetical one: no closed-form solution exists for a
multi-period cash flow sequence, and Descartes' rule of signs means a sequence with more than one
sign change can have multiple mathematically valid IRRs. calculate_irr refuses (returns None)
rather than silently return "a" root that might not be the economically meaningful one - the same
"never fabricate a plausible-looking wrong number" discipline applied throughout this engagement,
here applied to a genuine numerical-methods edge case rather than a missing-input edge case.

cash_flows convention throughout this module: index 0 is Year 0 (the initial capital outlay,
conventionally negative), indices 1..N are net operational inflows for years 1 through N.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

CURRENCY_QUANTIZE = Decimal("0.0001")
RATE_QUANTIZE = Decimal("0.000001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def round_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANTIZE, rounding=ROUND_HALF_EVEN)


def _npv_at_rate(rate: Decimal, cash_flows: list[Decimal]) -> Decimal:
    total = Decimal("0")
    for t, cf in enumerate(cash_flows):
        total += cf / (Decimal("1") + rate) ** t
    return total


def calculate_npv(discount_rate: Decimal, cash_flows: list[Decimal]) -> Decimal:
    """
    discount_rate (WACC) has NO default anywhere in this function's signature - a genuine
    operational input, never a house policy threshold, so omitting it is a TypeError, not a
    fabricated zero or an invented 10% benchmark. Non-positive rates are explicitly refused
    (ValueError): a zero or negative WACC either makes the discounting meaningless (zero) or
    inverts the time-value-of-money relationship entirely (negative) - never silently computed
    through as if it were a normal input.
    """
    if discount_rate <= 0:
        raise ValueError(f"discount_rate must be positive, got {discount_rate} - refusing to compute a meaningless NPV")
    return round_currency(_npv_at_rate(discount_rate, cash_flows))


def _count_sign_changes(cash_flows: list[Decimal]) -> int:
    """Descartes' rule of signs - zeros don't count as a sign change, only genuine sign flips
    between consecutive non-zero cash flows."""
    nonzero = [cf for cf in cash_flows if cf != 0]
    if len(nonzero) < 2:
        return 0
    return sum(1 for i in range(1, len(nonzero)) if (nonzero[i] > 0) != (nonzero[i - 1] > 0))


def calculate_irr(
    cash_flows: list[Decimal], *, max_iterations: int = 200, tolerance: Decimal = Decimal("0.0000001"),
) -> Decimal | None:
    """
    Bisection search for the discount rate producing NPV=0 - not Newton-Raphson, deliberately:
    bisection is guaranteed to converge given a bracket containing a sign change, with no
    derivative computation and no risk of overshooting into a nonsensical negative-100%-or-below
    rate the way an unconstrained Newton step can.

    Returns None, never a fabricated or ambiguous number, when:
    - the cash flow sequence does not have EXACTLY one sign change (Descartes' rule) - zero sign
      changes means no real root can exist (all one direction); more than one means multiple
      real IRRs could exist, and returning "a" one of them would misrepresent which is
      economically meaningful.
    - no root exists within the search bracket [-99.99%, 10000%] - covers every economically
      plausible IRR; a "root" outside this range is not a number worth reporting as an IRR.
    - bisection fails to converge within max_iterations - refuses rather than return an
      imprecise guess.
    """
    if _count_sign_changes(cash_flows) != 1:
        return None

    low, high = Decimal("-0.9999"), Decimal("100")
    npv_low, npv_high = _npv_at_rate(low, cash_flows), _npv_at_rate(high, cash_flows)
    if npv_low * npv_high > 0:
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2
        npv_mid = _npv_at_rate(mid, cash_flows)
        if abs(npv_mid) < tolerance:
            return round_rate(mid)
        if (npv_mid > 0) == (npv_low > 0):
            low, npv_low = mid, npv_mid
        else:
            high = mid
    return None


def calculate_discounted_payback_period(discount_rate: Decimal, cash_flows: list[Decimal]) -> Decimal | None:
    """
    Years until cumulative DISCOUNTED cash flow turns positive, interpolated within the crossing
    year rather than rounded to a whole year (a project that recovers its outlay 6 months into
    year 5 is meaningfully different from one that takes the full 5 years). Genuinely different
    math from NPV/IRR (a running cumulative sum with an interpolated crossing point, not a
    root-find or a single discounted total) - not a reuse of either.

    Returns None, not a fabricated period, when cumulative discounted cash flow never turns
    positive within the given cash flow horizon - the project simply never pays back on the data
    given, and reporting some number here would be worse than reporting nothing.

    discount_rate has no default, same posture as calculate_npv - omitting it is a TypeError.
    """
    if discount_rate <= 0:
        raise ValueError(f"discount_rate must be positive, got {discount_rate}")

    cumulative = Decimal("0")
    for t, cf in enumerate(cash_flows):
        discounted_cf = cf / (Decimal("1") + discount_rate) ** t
        previous_cumulative = cumulative
        cumulative += discounted_cf
        if t > 0 and previous_cumulative < 0 <= cumulative:
            fraction_of_year = -previous_cumulative / discounted_cf
            return round_rate(Decimal(t - 1) + fraction_of_year)
    return None


def apply_tax_shield_to_cash_flows(
    net_operational_cash_flows: list[Decimal], capital_allowance_schedule: list[Decimal], tax_rate: Decimal,
) -> list[Decimal]:
    """
    Adds the capital allowance tax shield (allowance x tax_rate) to each period's net operational
    cash flow - a real, positive cash benefit from reduced tax payable, not a bookkeeping
    adjustment to COGS or any realized figure. Covers years 1..N only - Year 0's initial outlay
    is untouched by this function, since wear-and-tear allowances apply to operating years, not
    the acquisition transaction itself; a caller combining this with Year 0 must prepend it
    separately, not pass it through this function.

    Schedule length mismatch is refused (ValueError), never silently truncated or zero-padded -
    a capital allowance schedule shorter than the cash flow projection is a real data gap, not
    something to paper over with an assumed zero for the missing years.
    """
    if len(net_operational_cash_flows) != len(capital_allowance_schedule):
        raise ValueError(
            f"net_operational_cash_flows has {len(net_operational_cash_flows)} periods but "
            f"capital_allowance_schedule has {len(capital_allowance_schedule)} - lengths must match"
        )
    return [
        round_currency(cf + (allowance * tax_rate))
        for cf, allowance in zip(net_operational_cash_flows, capital_allowance_schedule)
    ]


def flag_speculative_residual_value(
    residual_value: Decimal, initial_capital_outlay: Decimal, threshold_pct: Decimal = Decimal("0.20"),
) -> dict:
    """
    threshold_pct defaults to 20% - this IS a policy/materiality threshold, not an operational
    driver (same distinction already established in this codebase for
    check_inventory_reconciliation's tolerance and is_threshold_alert_due's buffer_pct/
    buffer_days) - unlike discount_rate above, which is a genuine per-project operational input
    and correctly has zero default. Inclusive boundary (>= flags, matching classify_expiry_risk/
    classify_aging_buckets' own conservative posture elsewhere in this codebase) - residual value
    at exactly the threshold is flagged, not given the benefit of the doubt.

    Returns a structured dict, never raises: a speculative residual value assumption is a real,
    valid (if risky) modelling choice a CFO might deliberately want to see flagged, not an error
    condition that should block the evaluation outright.
    """
    if initial_capital_outlay == 0:
        return {"is_speculative": False, "residual_pct_of_outlay": None, "warning": None}

    residual_pct = round_rate(abs(residual_value) / abs(initial_capital_outlay))
    is_speculative = residual_pct >= threshold_pct
    warning = None
    if is_speculative:
        warning = (
            f"Residual value (R{residual_value}) is {round_currency(residual_pct * 100)}% of "
            f"initial capital outlay (R{initial_capital_outlay}) - exceeds the "
            f"{round_currency(threshold_pct * 100)}% materiality threshold; speculative "
            f"terminal value accounting risk"
        )
    return {"is_speculative": is_speculative, "residual_pct_of_outlay": residual_pct, "warning": warning}


def evaluate_capital_investment(
    discount_rate: Decimal, cash_flows: list[Decimal], residual_value: Decimal,
    residual_flag_threshold_pct: Decimal = Decimal("0.20"),
) -> dict:
    """
    Bundles NPV, IRR, discounted payback, and the speculative-residual-value flag into one
    evaluation payload - reuses every other function in this module rather than reimplementing
    any of their math. Deliberately has NO key resembling cogs/inventory_value/net_margin/dio/
    dpo/ccc/mac_control_total (checked structurally in tests_pure) - a future capital project's
    projected returns must never be mistaken for a realized operational figure once this payload
    reaches a dashboard or report.

    cash_flows[0] (Year 0, the initial capital outlay) is what flag_speculative_residual_value
    compares residual_value against.
    """
    npv = calculate_npv(discount_rate=discount_rate, cash_flows=cash_flows)
    irr = calculate_irr(cash_flows)
    payback = calculate_discounted_payback_period(discount_rate=discount_rate, cash_flows=cash_flows)
    residual_flag = flag_speculative_residual_value(
        residual_value=residual_value, initial_capital_outlay=cash_flows[0], threshold_pct=residual_flag_threshold_pct,
    )
    return {
        "npv": npv, "irr": irr, "discounted_payback_period": payback,
        "residual_value_flag": residual_flag,
    }
