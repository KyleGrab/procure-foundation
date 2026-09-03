"""
Route log physical plausibility and division-safety - Chaos Audit Domain 2. Genuinely separate
from exact_matcher.py's identity-matching concern (this validates that already-matched data is
physically possible, not whether it matches a source system reference). Pure Decimal/logic, no
DB, no framework.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def validate_route_log_plausibility(
    distance_km: Decimal, stop_count: int, total_drop_weight_kg: Decimal, vehicle_max_payload_kg: Decimal,
) -> list[str]:
    """
    Returns a list of plausibility violations - empty means clean, never silently accepts a
    physically impossible route log. Does not raise: a route/service layer decides severity
    (likely a 422, but that's this function's caller's decision, not baked in here), matching
    this codebase's established validation-module pattern (inventory_valuation_validation.py,
    working_capital_validation.py both return diagnostics rather than raise directly).

    Checks named explicitly by this domain's own audit brief:
    - zero distance_km with stop_count > 0: cannot happen physically - you cannot make multiple
      delivery stops having travelled zero kilometres.
    - total_drop_weight_kg exceeding vehicle_max_payload_kg: a real, plausible data-pipeline bug
      (e.g. a monthly fleet-aggregate figure accidentally fed into a single-trip check - not
      hypothetical, this is exactly what 30_TRUCK_PROFITABILITY's monthly totals vs a single
      day's real trip figures would produce if confused with each other), not just a "clipping
      error" in the literal sense.
    - negative distance_km or stop_count: never physically valid, always flagged.
    """
    violations: list[str] = []

    if distance_km == 0 and stop_count > 0:
        violations.append("zero distance_km with stop_count > 0 - physically impossible")

    if distance_km < 0:
        violations.append(f"negative distance_km: {distance_km}")

    if stop_count < 0:
        violations.append(f"negative stop_count: {stop_count}")

    if total_drop_weight_kg > vehicle_max_payload_kg:
        violations.append(
            f"total_drop_weight_kg ({total_drop_weight_kg}) exceeds vehicle_max_payload_kg "
            f"({vehicle_max_payload_kg}) - likely a unit-confusion or data-pipeline error, not a "
            f"real single-trip figure"
        )

    return violations


def calculate_cost_per_drop(total_route_cost: Decimal, stop_count: int) -> Decimal | None:
    """
    None when stop_count is zero or negative - a route log with cost but no plausible drop count
    is itself a plausibility violation (validate_route_log_plausibility), not something this
    function should mask with a ZeroDivisionError or a fabricated per-drop figure. Same
    zero-denominator discipline as allocate_activity_cost/calculate_allocation_variance elsewhere
    in this codebase - dividing by zero here is structurally impossible, not just avoided in the
    common case.
    """
    if stop_count <= 0:
        return None
    return round_currency(total_route_cost / Decimal(stop_count))
