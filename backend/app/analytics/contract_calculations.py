"""
Deterministic contract-lifecycle math (spec Section 31-32, this delivery's Phase 3 addendum).
Pure `datetime`/`Decimal`/stdlib - no DB, no network - by design, same pattern as
`price_review_calculations.py`: every number here is produced by exactly one function, tested
against worked examples, and called from the service layer, never recomputed inline. See
docs/phase3-contract-lifecycle-plan.md §2.1 for why text extraction is deliberately NOT part of
this module - only calculations over already-known structured terms belong here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")

# Days-before-expiry thresholds at which an alert should fire (spec's own Contract Alerts list:
# 180/90/60/30 days), organisation-configurable in the DB layer via organisation_settings
# (ADR-004's pattern) - these are the defaults this module applies when none are supplied.
DEFAULT_ALERT_THRESHOLDS_DAYS = (180, 90, 60, 30)


class ContractStatus(str, Enum):
    ACTIVE = "active"
    NOTICE_PERIOD_OPEN = "notice_period_open"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    AUTO_RENEWING = "auto_renewing"


class EscalationType(str, Enum):
    NONE = "none"
    FIXED_PERCENTAGE = "fixed_percentage"
    CPI_LINKED = "cpi_linked"
    TIERED = "tiered"
    NEGOTIATED = "negotiated"


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def calculate_notice_deadline(expiry_date: date, notice_period_days: int) -> date:
    """The last date notice can be given to prevent auto-renewal/rollover. Negative
    notice_period_days is a data-entry error, not a valid contract term - raise, don't guess."""
    if notice_period_days < 0:
        raise ValueError("notice_period_days cannot be negative")
    return expiry_date - timedelta(days=notice_period_days)


def is_notice_window_open(today: date, notice_deadline: date, expiry_date: date) -> bool:
    """True if notice can still be given today without missing the deadline. False both before
    the notice window conceptually opens (irrelevant this far out) and after it's closed."""
    return today <= notice_deadline and today <= expiry_date


def calculate_next_renewal_date(
    expiry_date: date, *, auto_renew: bool, renewal_term_months: int | None
) -> date | None:
    """None if the contract doesn't auto-renew - there's no next date to compute, and returning
    a fabricated one would be worse than admitting there isn't one."""
    if not auto_renew:
        return None
    if not renewal_term_months or renewal_term_months <= 0:
        raise ValueError("auto_renew=True requires a positive renewal_term_months")
    return _add_months(expiry_date, renewal_term_months)


def _add_months(base: date, months: int) -> date:
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day for months with fewer days (e.g. 31 Jan + 1 month should not crash on Feb 31).
    day = min(base.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def classify_contract_status(
    today: date, expiry_date: date, notice_deadline: date, *, auto_renew: bool,
    expiring_soon_threshold_days: int = 90,
) -> ContractStatus:
    """See ADR-010: pure function of dates, callable at any time - never assume a stored status
    is still correct without re-running this."""
    if today > expiry_date:
        return ContractStatus.EXPIRED
    if today > notice_deadline:
        # Past the point where notice can stop it - if it auto-renews, renewal is now locked in.
        return ContractStatus.AUTO_RENEWING if auto_renew else ContractStatus.NOTICE_PERIOD_OPEN
    days_to_expiry = (expiry_date - today).days
    if days_to_expiry <= expiring_soon_threshold_days:
        return ContractStatus.EXPIRING_SOON
    return ContractStatus.ACTIVE


def determine_due_alerts(
    today: date, expiry_date: date, notice_deadline: date,
    already_fired: set[str], *, thresholds_days: tuple[int, ...] = DEFAULT_ALERT_THRESHOLDS_DAYS,
) -> list[str]:
    """
    Returns alert-type strings that should fire today and haven't already (idempotent - see
    contract_alerts table in the migration). 'expiry_N' for each threshold crossed, plus
    'notice_deadline' on the day the notice window closes. Intended to be called once per day per
    contract by a scheduled job (Phase 9's background processing, not built here) - calling it
    more than once a day is safe because `already_fired` prevents duplicates either way.
    """
    due: list[str] = []
    days_to_expiry = (expiry_date - today).days

    for threshold in sorted(thresholds_days, reverse=True):
        alert_type = f"expiry_{threshold}"
        if days_to_expiry <= threshold and alert_type not in already_fired:
            due.append(alert_type)

    if today == notice_deadline and "notice_deadline" not in already_fired:
        due.append("notice_deadline")

    return due


def calculate_escalated_price(
    base_price: Decimal, escalation_type: EscalationType, *,
    escalation_rate_pct: Decimal | None = None,
    external_index_value_pct: Decimal | None = None,
    periods_elapsed: int = 1,
) -> Decimal:
    """
    See ADR-009: for cpi_linked, external_index_value_pct is REQUIRED - this function will never
    look up or estimate an index value itself. Passing one in for a fixed_percentage contract (or
    vice-versa) is a caller error and raises, rather than silently picking whichever value happens
    to be non-None.
    """
    if escalation_type == EscalationType.NONE:
        return round_currency(base_price)

    if escalation_type == EscalationType.FIXED_PERCENTAGE:
        if escalation_rate_pct is None:
            raise ValueError("fixed_percentage escalation requires escalation_rate_pct")
        factor = (Decimal("1") + escalation_rate_pct) ** periods_elapsed
        return round_currency(base_price * factor)

    if escalation_type == EscalationType.CPI_LINKED:
        if external_index_value_pct is None:
            raise ValueError(
                "cpi_linked escalation requires external_index_value_pct to be supplied "
                "explicitly - this function will not estimate or default it (ADR-009)"
            )
        factor = (Decimal("1") + external_index_value_pct) ** periods_elapsed
        return round_currency(base_price * factor)

    raise ValueError(
        f"calculate_escalated_price does not support {escalation_type.value!r} directly - "
        "tiered/negotiated escalations require a human-reviewed schedule, not a single formula"
    )


@dataclass(frozen=True)
class TieredEscalationBand:
    threshold_spend: Decimal   # cumulative spend at which this tier's rate applies
    rate_pct: Decimal


def calculate_tiered_escalated_price(
    base_price: Decimal, cumulative_spend: Decimal, bands: list[TieredEscalationBand],
) -> Decimal:
    """Tiered escalation applies the rate of the highest threshold band the cumulative spend has
    reached. bands must be supplied by the caller from verified contract terms - never inferred."""
    if not bands:
        raise ValueError("tiered escalation requires at least one band")
    applicable = [b for b in bands if cumulative_spend >= b.threshold_spend]
    if not applicable:
        return round_currency(base_price)  # spend hasn't reached the first tier yet
    best = max(applicable, key=lambda b: b.threshold_spend)
    return round_currency(base_price * (Decimal("1") + best.rate_pct))
