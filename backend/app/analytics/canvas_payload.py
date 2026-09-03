"""
Consolidates every real, already-tested pure engine in this codebase into one management canvas
payload, with per-layer graceful degradation. Pure orchestration - no DB, no framework, §2.1.
Does not compute anything itself; every real number in the payload comes from a function this
codebase has already built and tested (calculate_customer_net_margin, calculate_gross_to_net_waterfall,
resolve_gated_inventory_value, calculate_allocation_variance, calculate_markdown_adjusted_gmroi,
build_13_week_cash_forecast, refuse_timing_bridge_allocation) - this module's only real logic is
the failure-isolation boundary between them.

Deliberately catches only (ValueError, TypeError) - the two exception shapes every real gate
function in this codebase actually raises for a violated precondition (ValueError) or a missing
required argument (TypeError, since several of these functions have zero defaults by design).
Never a blanket except: Exception - that would silently swallow a genuine bug (a KeyError from an
actual programming mistake, say) behind a calm-looking "diagnostic state" label, which would be
worse than letting the dashboard crash, not better.
"""
from __future__ import annotations

from typing import Callable

_CAUGHT_EXCEPTION_TYPES = (ValueError, TypeError)


def build_widget_result(compute_fn: Callable[..., dict], *args, **kwargs) -> dict:
    """
    Calls compute_fn(*args, **kwargs). On success: {"status": "ok", "data": <real result>,
    "reason_codes": []}. On a ValueError or TypeError (the two shapes this codebase's real gate
    functions raise): {"status": "diagnostic", "data": None, "reason_codes": [<the real
    exception message>]} - the specific widget transitions to a diagnostic state with the actual
    reason, never a generic "something went wrong."

    Any OTHER exception type propagates uncaught, deliberately - see module docstring.
    """
    try:
        result = compute_fn(*args, **kwargs)
        return {"status": "ok", "data": result, "reason_codes": []}
    except _CAUGHT_EXCEPTION_TYPES as exc:
        return {"status": "diagnostic", "data": None, "reason_codes": [str(exc)]}


def build_management_canvas_payload(
    revenue_layer_fn: Callable[[], dict], operations_layer_fn: Callable[[], dict],
    liquidity_layer_fn: Callable[[], dict], risk_layer_fn: Callable[[], dict],
) -> dict:
    """
    Each layer function is a zero-argument callable wrapping an already-parameterized real
    calculation (a closure over the period's real, resolved figures - this function never sees
    or touches the raw inputs). Each layer is evaluated independently through build_widget_result:
    one layer's ValueError/TypeError becomes that layer's own diagnostic state and has zero
    effect on the other three - the explicit, named requirement that a failing 13-week cash
    model or trade-spend gate must never crash the whole dashboard, and that Gross Revenue (or
    any other working layer) stays fully populated and interactive regardless.

    Always returns all four keys, every time, regardless of how many layers failed - the payload
    itself is never "all or nothing."
    """
    return {
        "revenue_layer": build_widget_result(revenue_layer_fn),
        "operations_layer": build_widget_result(operations_layer_fn),
        "liquidity_layer": build_widget_result(liquidity_layer_fn),
        "risk_layer": build_widget_result(risk_layer_fn),
    }
