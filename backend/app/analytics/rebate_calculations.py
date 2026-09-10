"""
Deterministic rebate calculations (spec Section 29, analytics-methodology.md §8, this delivery's
Phase 4). Pure `Decimal`/`date`/stdlib - no DB, no network - same pattern as
price_review_calculations.py and contract_calculations.py: every number here is produced by
exactly one function, tested against worked examples, called from the service layer, never
recomputed inline. Reuses the tiered-band lookup shape from
`contract_calculations.TieredEscalationBand` rather than inventing a second one (see
`RebateBand` below - same fields, different name because a rebate rate and an escalation rate are
different business concepts even when the math is identical).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")


class EntrySource(str, Enum):
    """Compliance finding 2 (docs/compliance-review-2026-08.md): drives ADR-014's rebate-source
    waterfall precedence and was previously a bare string literal in 6 places across 3 files
    (rebate_service.py, rebate_aggregation_service.py, db/models/rebate.py) - a typo in any one
    would have silently broken the precedence with no exception raised. Mechanical consolidation
    only - no string values changed, so existing DB rows and behavior are unaffected."""
    MANUAL = "manual"
    TRANSACTION_AGGREGATION = "transaction_aggregation"
    INVOICE_AGGREGATION = "invoice_aggregation"


class RebateType(str, Enum):
    FIXED_PERCENTAGE = "fixed_percentage"
    TIERED = "tiered"
    VOLUME = "volume"
    GROWTH = "growth"
    FIXED_AMOUNT = "fixed_amount"
    RETROSPECTIVE = "retrospective"


class RebateStatus(str, Enum):
    ON_TRACK = "on_track"
    THRESHOLD_APPROACHING = "threshold_approaching"
    PERIOD_CLOSED_AWAITING_PAYMENT = "period_closed_awaiting_payment"
    LEAKAGE_DETECTED = "leakage_detected"
    RECONCILED = "reconciled"


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class RebateBand:
    threshold_spend: Decimal
    rate_pct: Decimal


def calculate_expected_rebate(
    actual_spend: Decimal, rebate_type: RebateType, *,
    flat_rate_pct: Decimal | None = None,
    bands: list[RebateBand] | None = None,
    fixed_amount: Decimal | None = None,
) -> Decimal:
    """
    Progressive - recalculated every time actual_spend changes (spec Section 29's "approaching
    threshold" alert depends on this being live, not fixed at period end - see
    calculate_progress_to_next_tier below for the alert-driving half of that).
    """
    if rebate_type in (RebateType.FIXED_PERCENTAGE, RebateType.VOLUME, RebateType.GROWTH):
        if flat_rate_pct is None:
            raise ValueError(f"{rebate_type.value} rebates require flat_rate_pct")
        return round_currency(actual_spend * flat_rate_pct)

    if rebate_type in (RebateType.TIERED, RebateType.RETROSPECTIVE):
        if not bands:
            raise ValueError(f"{rebate_type.value} rebates require at least one band")
        applicable = [b for b in bands if actual_spend >= b.threshold_spend]
        if not applicable:
            return Decimal("0.0000")  # spend hasn't reached the first tier yet - not an error
        best = max(applicable, key=lambda b: b.threshold_spend)
        return round_currency(actual_spend * best.rate_pct)

    if rebate_type == RebateType.FIXED_AMOUNT:
        if fixed_amount is None:
            raise ValueError("fixed_amount rebates require fixed_amount")
        return round_currency(fixed_amount)

    raise ValueError(f"Unhandled rebate_type: {rebate_type!r}")


def calculate_progress_to_next_tier(
    actual_spend: Decimal, bands: list[RebateBand]
) -> tuple[Decimal | None, Decimal | None]:
    """
    Returns (next_threshold, amount_remaining) - None, None if there is no higher tier left (spend
    has already reached the top band). This is what actually drives the threshold-approaching
    alert, not calculate_expected_rebate itself, which only reports the tier already reached.
    """
    if not bands:
        raise ValueError("bands must not be empty")
    higher_bands = sorted(
        (b for b in bands if b.threshold_spend > actual_spend), key=lambda b: b.threshold_spend
    )
    if not higher_bands:
        return None, None
    next_band = higher_bands[0]
    return next_band.threshold_spend, round_currency(next_band.threshold_spend - actual_spend)


def calculate_rebate_leakage(expected_amount: Decimal, received_amount: Decimal | None) -> Decimal:
    """
    analytics-methodology.md §8's formula. received_amount=None means "nothing has been received
    yet" - the full expected_amount is at-risk leakage until a credit note/payment reference sets
    it, never assumed equal to expected (spec's own explicit warning against that assumption).
    """
    received = received_amount if received_amount is not None else Decimal(0)
    return round_currency(expected_amount - received)


def calculate_aggregate_rebate_leakage(period_pairs: list[tuple[Decimal, Decimal | None]]) -> Decimal:
    """Org-wide leakage across every rebate period given. Reuses calculate_rebate_leakage per
    pair rather than reimplementing the math (§2.7) - this function only sums. Does not floor
    the total at zero: a period with received > expected produces a real negative leakage figure
    that partially offsets the total, same as calculate_rebate_leakage's own signed behavior -
    clamping it away here would hide a real correction/over-payment, not just tidy a number."""
    return round_currency(sum(
        (calculate_rebate_leakage(expected, received) for expected, received in period_pairs),
        Decimal(0),
    ))


def is_threshold_alert_due(
    actual_spend: Decimal, bands: list[RebateBand], today: date, period_end: date, *,
    buffer_pct: Decimal = Decimal("0.85"), buffer_days: int = 30,
) -> bool:
    """
    Product decision (confirmed): fires when spend has reached buffer_pct (85%) of the next
    unreached tier's threshold AND today is within buffer_days (30) of period close - both
    conditions together, not either alone. A supplier hitting 85% of a tier in month one of a
    12-month period isn't urgent; the same 85% with 30 days left to influence it is. If bands are
    already fully reached (no next tier), there's nothing to approach - returns False, not an
    error, since "already at the top tier" is a valid, common state.
    """
    next_threshold, _ = calculate_progress_to_next_tier(actual_spend, bands)
    if next_threshold is None:
        return False
    days_to_close = (period_end - today).days
    if days_to_close < 0 or days_to_close > buffer_days:
        return False
    return actual_spend >= next_threshold * buffer_pct


def classify_rebate_status(
    expected_amount: Decimal, received_amount: Decimal | None, *,
    period_closed: bool, threshold_alert_due: bool,
) -> RebateStatus:
    if received_amount is not None:
        leakage = calculate_rebate_leakage(expected_amount, received_amount)
        return RebateStatus.RECONCILED if leakage <= Decimal("0.0001") else RebateStatus.LEAKAGE_DETECTED
    if period_closed:
        return RebateStatus.PERIOD_CLOSED_AWAITING_PAYMENT
    if threshold_alert_due:
        return RebateStatus.THRESHOLD_APPROACHING
    return RebateStatus.ON_TRACK


def is_period_due_for_close(period_end: date, today: date) -> bool:
    """The 'formal period-close snapshot' trigger (product decision: monthly job checks this for
    every open rebate_period_actuals row, regardless of the rebate's own period_type - a period
    is due the moment today reaches its end date, whether the job runs daily or monthly)."""
    return today >= period_end


@dataclass(frozen=True)
class TransactionAggregate:
    total_spend: Decimal
    total_volume: Decimal
    transaction_count: int


def aggregate_transactions_for_period(
    transactions: list[tuple[Decimal, Decimal, date]], period_start: date, period_end: date,
) -> TransactionAggregate:
    """
    Phase 4b: sums (amount, quantity, transaction_date) tuples falling within [period_start,
    period_end] inclusive. Pure aggregation - the caller (service layer) is responsible for
    fetching the right supplier's rows from `purchase_transactions`; this function trusts nothing
    about the input beyond the tuple shape, so it's exercised directly in
    tests_pure/test_rebate_calculations.py without a DB.
    """
    in_period = [t for t in transactions if period_start <= t[2] <= period_end]
    total_spend = sum((t[0] for t in in_period), Decimal(0))
    total_volume = sum((t[1] for t in in_period), Decimal(0))
    return TransactionAggregate(
        total_spend=round_currency(total_spend), total_volume=total_volume,
        transaction_count=len(in_period),
    )
