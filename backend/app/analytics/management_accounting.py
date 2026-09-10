"""
Tenant-agnostic Management Accounting & Cost-to-Serve engine. Pure `Decimal`/`Enum` - no
SQLAlchemy, no FastAPI, no Pydantic - same §2.1 boundary as every analytics module in this
codebase (checked structurally by tests_pure/test_management_accounting.py, not just by
convention).

The fallback-allocation hierarchy is *generalized* from NetDrop IQ's proven cts_engine.py pattern
(direct actual cost > activity-rate basis > volumetric basis, never blended on one row) -
deliberately not that project's specific trip/Case_Count/driver business rules, which belong to
one client's logistics domain and would violate this turn's own constraint that ProcureIQ stay
tenant-agnostic. A tenant using this engine supplies its own cost pools, activity volumes, and
basis flags; nothing here assumes trucks, drivers, or any specific industry.

Two deliberate deviations from the literal request, both because the alternative would mean
fabricating or silently dropping a figure:
1. `allocate_activity_cost` returns `Decimal | None`, not `Decimal` - a zero-volume denominator
   makes a rate undefined, not zero (§3.2). Every other zero-denominator case in this codebase
   (calculate_percentage_change, calculate_price_consistency, etc.) follows the same rule.
2. `calculate_working_capital_metrics` gains an explicit optional `cash` parameter not in the
   original signature - the spec's own Working Capital Ratio formula needs it
   ((AR + Inventory + Cash) / AP), and the alternative (assume cash=0, or silently drop the
   ratio) would either understate a real figure or omit a metric that was explicitly asked for.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")
DAYS_QUANTIZE = Decimal("0.1")
RATIO_QUANTIZE = Decimal("0.01")
PERCENT_QUANTIZE = Decimal("0.01")

_RECOGNIZED_ALLOCATION_TYPES = frozenset({"per_unit", "per_pallet", "per_km", "pct_revenue"})


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def round_days(value: Decimal) -> Decimal:
    return value.quantize(DAYS_QUANTIZE, rounding=ROUND_HALF_EVEN)


def round_ratio(value: Decimal) -> Decimal:
    return value.quantize(RATIO_QUANTIZE, rounding=ROUND_HALF_EVEN)


def round_percentage(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_QUANTIZE, rounding=ROUND_HALF_EVEN)


class AllocationLevel(str, Enum):
    DIRECT = "direct"                # Level 1: known actual cost
    ACTIVITY_RATE = "activity_rate"  # Level 2: cost per km / cost per drop-hour
    VOLUMETRIC = "volumetric"        # Level 3: cost per unit/pallet/case share
    UNALLOCATED = "unallocated"      # none of the above basis data available for this row


def determine_allocation_level(
    *, has_direct_cost: bool, has_activity_rate_basis: bool, has_volumetric_basis: bool,
) -> AllocationLevel:
    """
    Configurable fallback hierarchy, evaluated in strict priority order. A row with both direct
    cost AND activity-rate basis data always uses Level 1 - never blended (generalizes NetDrop
    IQ's own "a single row is never charged under more than one level" rule, which exists there
    for the identical reason: mixing an actual-cost allocation with a rate-based one on the same
    row double-counts cost).
    """
    if has_direct_cost:
        return AllocationLevel.DIRECT
    if has_activity_rate_basis:
        return AllocationLevel.ACTIVITY_RATE
    if has_volumetric_basis:
        return AllocationLevel.VOLUMETRIC
    return AllocationLevel.UNALLOCATED


def allocate_activity_cost(
    total_cost_pool: Decimal, activity_volume: Decimal, allocation_type: str,
) -> Decimal | None:
    """
    Generic rate: total_cost_pool / activity_volume. allocation_type is validated against a
    recognized, named set - not because it changes this function's arithmetic (every recognized
    type reduces to the same division; what differs is what activity_volume represents, which is
    the caller's concern via cost_allocation_rules, not this function's), but because silently
    accepting an arbitrary unrecognized string would be exactly the kind of unvalidated
    provenance label §2.4 warns against - a typo'd allocation_type should be caught here, not
    persisted downstream as if it meant something.
    """
    if allocation_type not in _RECOGNIZED_ALLOCATION_TYPES:
        raise ValueError(
            f"Unrecognized allocation_type: {allocation_type!r} - expected one of {sorted(_RECOGNIZED_ALLOCATION_TYPES)}"
        )
    if activity_volume == 0:
        return None
    return round_currency(total_cost_pool / activity_volume)


def resolve_trade_spend_for_period(trade_spend_record: Decimal | None, agreement_exists: bool) -> Decimal:
    """
    Gates calculate_customer_net_margin's trade_spend input at the point sourcing genuinely
    matters - that function's own Decimal("0") default is correct for customers with no
    trade-spend concept at all, but leaves "not sourced" and "genuinely zero" indistinguishable
    at any call site that DOES have a real sell-side agreement. This function is that
    distinction, made explicit:
    - No agreement exists: a real, correct zero - not a data-quality problem.
    - Agreement exists, this period's figure is loaded (including a real, confirmed zero):
      returns it.
    - Agreement exists, this period's figure was never loaded: raises ValueError rather than
      silently returning zero, which would understate trade spend and overstate net margin with
      no visible sign anything was wrong. Same precedent as refuse_timing_bridge_allocation - a
      plain ValueError for a violated precondition, mapped to ValidationFailedError (422) by
      whichever service/route layer calls this, not raised as an HTTP-shaped exception here.
    """
    if not agreement_exists:
        return Decimal(0)
    if trade_spend_record is None:
        raise ValueError(
            "A sell-side trade spend agreement exists for this customer but the current "
            "period's figure has not been sourced - refusing to substitute zero"
        )
    return trade_spend_record


def calculate_customer_net_margin(
    revenue: Decimal, cogs: Decimal, direct_logistics_cost: Decimal, warehouse_abc_cost: Decimal,
    trade_spend: Decimal, revenue_basis: str,
) -> dict:
    """net_revenue = revenue - trade_spend. gross_margin = net_revenue - cogs. cost_to_serve =
    direct_logistics_cost + warehouse_abc_cost. net_margin = gross_margin - cost_to_serve.
    Never clamped at zero - a negative net_margin is the entire point of this calculation
    (identifying a customer relationship that's actually losing money once true cost-to-serve is
    accounted for), and hiding it would defeat the metric's purpose. net_margin_pct is None when
    revenue is zero, not a fabricated 0%. is_net_revenue_negative is a distinct, explicit flag
    (Chaos Audit, targeted Phase 2 re-audit) - a customer whose combined deductions exceed gross
    revenue entirely is a qualitatively more extreme condition than a merely negative net_margin
    (which can happen even with healthy net_revenue, purely from high cost-to-serve), and deserves
    its own signal rather than being inferred from a bare negative number three fields down.

    revenue_basis is REQUIRED (Chaos Audit, targeted Phase 2 re-audit) - closes a real,
    quantified double-counting hazard: calculate_gross_to_net_waterfall already deducts
    volume_growth_rebates from gross_sales to produce net_revenue. Before this fix, nothing
    stopped a caller from feeding that already-net figure into THIS function's `revenue`
    parameter and ALSO passing a non-zero trade_spend representing the same real-world rebate -
    silently double-deducting it. Proven with real production data before this fix: doing exactly
    that with the real R353,202,524.93 waterfall output and the real R3,145,913.07 TTM rebate
    understated net_margin by exactly R3,145,913.07, with zero error and zero warning.

    "gross": `revenue` is pre-deduction Turnover; trade_spend is this function's one and only
    revenue deduction - the historical, still-valid usage.
    "net_of_waterfall": `revenue` already had rebates/discounts/etc. deducted via
    calculate_gross_to_net_waterfall - trade_spend MUST be Decimal("0") here (raises ValueError
    otherwise), since any non-zero value would double-count what the waterfall already removed.

    trade_spend is REQUIRED (Chaos Audit Domain 1, earlier this engagement) - it originally
    defaulted to Decimal("0") for backward compatibility, but that default was itself the exact
    fabricated-zero surface this engagement exists to close: a caller could silently omit it and
    get a real financial result computed as if trade spend were confirmed-zero, with no way to
    distinguish that from "genuinely resolved to zero." Every real caller must now go through
    resolve_trade_spend_for_period() first (which itself returns a real Decimal("0") for the
    correct, non-fabricated reason - no agreement exists) - the bypass is no longer possible at
    the type level, not just discouraged in a docstring. It is a REVENUE deduction, not folded
    into cost_to_serve: this matches the real P&L structure this engagement examined (Turnover ->
    Less: Rebates Paid -> Net Sales - trade spend reduces revenue before gross margin is struck,
    it is not a logistics/handling cost, and conflating the two would misstate both cost-to-serve
    and the true drivers of a negative margin."""
    if revenue_basis not in ("gross", "net_of_waterfall"):
        raise ValueError(f"Unrecognized revenue_basis: {revenue_basis!r} - expected 'gross' or 'net_of_waterfall'")
    if revenue_basis == "net_of_waterfall" and trade_spend != 0:
        raise ValueError(
            "revenue_basis='net_of_waterfall' means trade spend was already deducted via "
            "calculate_gross_to_net_waterfall - a non-zero trade_spend here would double-count it"
        )
    net_revenue = round_currency(revenue - trade_spend)
    gross_margin = round_currency(net_revenue - cogs)
    cost_to_serve = round_currency(direct_logistics_cost + warehouse_abc_cost)
    net_margin = round_currency(gross_margin - cost_to_serve)
    net_margin_pct = None if revenue == 0 else round_percentage(net_margin / revenue * 100)
    return {
        "net_revenue": net_revenue, "gross_margin": gross_margin, "cost_to_serve": cost_to_serve,
        "net_margin": net_margin, "net_margin_pct": net_margin_pct,
        "is_net_revenue_negative": net_revenue < 0,
    }


def calculate_working_capital_metrics(
    ar: Decimal, ap: Decimal, inventory: Decimal, annual_revenue: Decimal, annual_cogs: Decimal,
    cash: Decimal | None = None,
) -> dict:
    """
    DSO = (AR / annual_revenue) * 365, DIO = (inventory / annual_cogs) * 365,
    DPO = (AP / annual_cogs) * 365, CCC = DIO + DSO - DPO. Each ratio is None when its
    denominator is zero (§3.2) - never a fabricated 0 or 365. CCC is None if ANY of its three
    inputs is None - composing a "complete" CCC from two real figures and a silently-assumed
    zero for the third would misstate a genuinely important number, not just round it. CCC is
    NOT floored at zero: a negative CCC (paying suppliers after collecting from customers) is a
    real, favourable position and must be shown as negative.

    working_capital_ratio = (AR + inventory + cash) / AP - None whenever cash isn't supplied or
    AP is zero, never computed with an assumed cash=0.
    """
    dso = None if annual_revenue == 0 else round_days(ar / annual_revenue * 365)
    dio = None if annual_cogs == 0 else round_days(inventory / annual_cogs * 365)
    dpo = None if annual_cogs == 0 else round_days(ap / annual_cogs * 365)
    ccc = None if (dio is None or dso is None or dpo is None) else round_days(dio + dso - dpo)
    working_capital_ratio = (
        None if (cash is None or ap == 0) else round_ratio((ar + inventory + cash) / ap)
    )
    return {"dso": dso, "dio": dio, "dpo": dpo, "ccc": ccc, "working_capital_ratio": working_capital_ratio}


class ReconciliationStatus(str, Enum):
    RECONCILED = "reconciled"
    DIVERGENT = "divergent"


def check_inventory_reconciliation(
    control_total: Decimal, sub_ledger_extract: Decimal, tolerance: Decimal = Decimal("0.01"),
) -> dict:
    """
    Gate A core: compares a sub-ledger extract against the reconciled control total (the real,
    verified figure - e.g. a Balance Sheet inventory value) that advanced metrics must actually
    anchor to. Never asserts a real divergence on its own authority - this function only reports
    what it's given; the caller is responsible for supplying real figures, never a fabricated
    "sub-ledger" number dressed up to look reconciled.
    """
    variance = round_currency(control_total - sub_ledger_extract)
    is_reconciled = abs(variance) <= tolerance
    return {
        "control_total": round_currency(control_total),
        "sub_ledger_extract": round_currency(sub_ledger_extract),
        "variance": variance,
        "is_reconciled": is_reconciled,
        "status": ReconciliationStatus.RECONCILED if is_reconciled else ReconciliationStatus.DIVERGENT,
    }


def resolve_gated_inventory_value(
    reconciliation: dict, timing_bridge_documented: bool = False,
) -> Decimal | None:
    """
    The one function every DIO/GMROI/CCC caller must go through instead of picking a figure
    itself. Returns the control_total when reconciled, or when a real human has reviewed the gap
    and documented it as a known timing bridge (timing_bridge_documented=True) - ALWAYS the
    control total in that case too, never the raw sub-ledger figure, even once the divergence is
    explained. Returns None (Gate A closed) when divergent and undocumented - a caller receiving
    None must not proceed to compute DIO/GMROI/CCC at all, not substitute a guess.
    """
    if reconciliation["is_reconciled"]:
        return reconciliation["control_total"]
    if timing_bridge_documented:
        return reconciliation["control_total"]
    return None


def refuse_timing_bridge_allocation(variance: Decimal, entity_reference: str | None) -> None:
    """
    Enforces that an unreconciled timing bridge stays at the tenant/global ledger level and is
    never allocated down to a specific product, customer, or route - doing so would fabricate
    entity-level precision for a gap that is, by definition, not yet attributable to any one
    entity. Raises ValueError if called with a non-zero variance and a specific
    entity_reference; entity_reference=None (tenant/global level) is the only legitimate context
    for a non-zero variance to exist in.
    """
    if variance != 0 and entity_reference is not None:
        raise ValueError(
            f"Refusing to allocate a R{variance} reconciliation timing bridge to entity "
            f"{entity_reference!r} - timing bridges are tenant/global-level facts only, never "
            f"allocated to specific products, customers, or routes."
        )


def validate_reconciliation_bridge_completeness(
    control_total: Decimal, raw_subledger_total: Decimal, bridge_total: Decimal,
) -> dict:
    """
    Migration 0020: checks whether the SUM of real, evidenced bridge line items
    (inventory_reconciliation_bridges rows) actually closes the gap between a sub-ledger extract
    and the reconciled control total. Distinct from check_inventory_reconciliation, which only
    detects THAT a gap exists between two figures - this checks whether a SPECIFIC, independently
    -evidenced bridge amount genuinely explains it.

    reconciled_total = raw_subledger_total + bridge_total is computed here exactly as the DB's
    own CHECK constraint requires (ck_inv_recon_reconciled_identity) - never back-solved from
    "whatever makes final_variance zero," which would make the check tautological and defeat its
    entire purpose. final_variance can be genuinely nonzero, in either direction: bridge evidence
    that under- or over-explains the real gap is an equally real problem, never silently accepted
    just because a bridge record exists.
    """
    reconciled_total = round_currency(raw_subledger_total + bridge_total)
    final_variance = round_currency(reconciled_total - control_total)
    return {
        "reconciled_total": reconciled_total, "final_variance": final_variance,
        "is_fully_explained": final_variance == 0,
    }


def calculate_future_replacement_exposure(
    quantity_on_hand: Decimal, current_replacement_unit_cost: Decimal, recorded_mac_unit_cost: Decimal,
) -> dict:
    """
    CIMA P-pillar: a holding gain/loss on agricultural/perishable inputs under price volatility.
    exposure_per_unit = current_replacement_unit_cost - recorded_mac_unit_cost. Positive means
    replacement cost has risen above what's recorded (real, unrealized cost pressure - restocking
    today would cost more than the books currently reflect). Negative means it's fallen - a real,
    favourable position, never clamped to zero, same discipline as calculate_customer_net_margin.

    The result dict deliberately has NO key resembling cogs/inventory_value/net_margin/dio/dpo/ccc
    (checked structurally in tests_pure) - this is prospective-only and must never become
    realized COGS, inventory valuation, or a working-capital/margin input. Blending an unrealized
    market movement into a realized-cost metric would let a commodity price swing masquerade as
    an operating result.
    """
    exposure_per_unit = round_currency(current_replacement_unit_cost - recorded_mac_unit_cost)
    total_exposure = round_currency(exposure_per_unit * quantity_on_hand)
    return {
        "exposure_per_unit": exposure_per_unit,
        "total_exposure": total_exposure,
        "is_adverse": total_exposure > 0,
    }


def flag_replacement_cost_divergence(
    aggregate_replacement_exposure: Decimal, mac_control_total: Decimal, materiality_threshold_pct: Decimal,
) -> bool:
    """
    Flags when aggregate replacement-cost exposure exceeds a materiality threshold relative to
    the locked MAC control total (Gate A's reconciled anchor - see check_inventory_reconciliation/
    resolve_gated_inventory_value). Reads absolute exposure, since a large favourable swing is
    just as worth surfacing at the control-total level as an adverse one. A zero control total is
    a data gap, not a divergence signal - materiality has no base to measure against, so this
    returns False rather than a fabricated "always material" or a ZeroDivisionError.
    """
    if mac_control_total == 0:
        return False
    ratio = abs(aggregate_replacement_exposure) / mac_control_total
    return ratio > materiality_threshold_pct


def is_rate_stale(rate_effective_date, as_of_date, staleness_threshold_days: int) -> bool:
    """
    Closes a real, named risk: CostAllocationRule.default_unit_rate is a static figure someone
    sets once, with nothing flagging when it's drifted from reality (a 20% fuel spike, for
    instance, leaves an unrefreshed rate silently understating cost-to-serve and overstating
    customer margin for as long as nobody remembers to update it). Inclusive boundary - a rate
    exactly at the threshold is flagged, not given one more day's grace, same posture as
    classify_expiry_risk's own inclusive boundary. A rate with no recorded effective date fails
    closed (always stale) rather than assumed current - never given the benefit of the doubt.
    """
    if rate_effective_date is None:
        return True
    return (as_of_date - rate_effective_date).days >= staleness_threshold_days


def calculate_gmroi(gross_margin: Decimal, average_inventory_value: Decimal) -> Decimal | None:
    """
    Gross Margin Return on Inventory Investment = gross margin / average inventory value.
    None when average inventory is zero (§3.2 - undefined, not a fabricated zero or infinity).
    Never floored at zero - a genuinely loss-making period must show a negative GMROI; hiding it
    would defeat the metric's purpose, same discipline as calculate_customer_net_margin.

    average_inventory_value should be a genuine average (e.g. (opening + closing) / 2) - a single
    point-in-time inventory figure understates or overstates GMROI depending on where in the cycle
    the snapshot falls. This function doesn't compute the average itself; the caller supplies it,
    same "caller owns period boundaries" pattern as calculate_working_capital_metrics.
    """
    if average_inventory_value == 0:
        return None
    return round_ratio(gross_margin / average_inventory_value)


def calculate_markdown_adjusted_gmroi(
    gross_margin: Decimal, average_inventory_value: Decimal,
    at_risk_inventory_value: Decimal, markdown_pct: Decimal,
) -> Decimal | None:
    """
    Gate C: reduces gross_margin by the markdown expected on inventory within the expiry warning
    window (classify_expiry_risk(expiry_date, as_of, warning_window_days=14) ==
    ExpiryRisk.EXPIRING_SOON - reused directly, not reimplemented; 14 is already a real,
    configurable parameter on that function, not a new hardcoded threshold) BEFORE the stock is
    actually written off. This is a diagnostic marker on the GMROI projection, not a realized
    loss - the underlying inventory_value/gross_margin figures this feeds into elsewhere are
    untouched by this function; only its own return value reflects the markdown.

    at_risk_inventory_value is the caller's responsibility to compute (sum of unit_cost *
    quantity_on_hand across every lot classified EXPIRING_SOON) - this function only applies the
    markdown_pct adjustment and reuses calculate_gmroi rather than reimplementing its division or
    its zero-denominator guard.
    """
    markdown_amount = round_currency(at_risk_inventory_value * markdown_pct)
    adjusted_gross_margin = round_currency(gross_margin - markdown_amount)
    return calculate_gmroi(gross_margin=adjusted_gross_margin, average_inventory_value=average_inventory_value)


def flag_zero_mass_risk(recorded_mass_kg: Decimal, has_recorded_sales_or_movement: bool) -> bool:
    """
    True when a stock code has zero recorded mass despite genuine sales/movement - the exact
    real, already-documented pattern (Zero_Mass_Stock_Codes_July2026.xlsx: 323 real stock codes,
    R2,185,479.14 of July 2026 sales with Mass = 0 in SYSPRO, ~37% of that value concentrated in
    temperature-controlled product classes). Gates calculate_allocation_variance: a genuinely
    weightless line (e.g. a service/labour code) with no real movement is not a data-quality
    problem and is never flagged - only the combination that indicates master data was never
    populated, which would otherwise silently misdiagnose as "massively overcosted" rather than
    "unmeasurable" if fed straight into the variance calculation.
    """
    return recorded_mass_kg == 0 and has_recorded_sales_or_movement


def calculate_allocation_variance(
    entity_activity_volume: Decimal, activity_based_rate: Decimal, currently_allocated_cost: Decimal,
    is_fallback_rate: bool,
) -> dict | None:
    """
    Compares what an entity (a route, a truck, a customer) is CURRENTLY allocated against what a
    true activity-based rate would allocate it, given its own real activity volume. Exists
    because a flat or averaged allocation rate (documented, real example: Gourmet_Foods_Cost_to_
    Serve_July2026.xlsx's 30_TRUCK_PROFITABILITY sheet applies one averaged running-cost figure
    to every "unmatched" truck regardless of how much weight it actually moved) systematically
    cross-subsidizes high-volume entities at the expense of low-volume ones, and this makes that
    distortion a real, computed number instead of an implied one.

    variance = currently_allocated_cost - activity_based_cost. Negative means the entity is
    UNDERcosted today (paying less than its real activity would justify - other entities are
    subsidizing it); positive means OVERcosted. is_undercosted is the sign, named explicitly
    rather than left for the caller to infer from a bare negative number.

    is_fallback_rate is now REQUIRED (Chaos Audit Domain 1, this engagement) - it defaulted to
    False, meaning an unclassified rate silently reported as "matched" (high confidence) rather
    than forcing an explicit answer. This compounded with CostAllocationRule.is_fallback_rate's
    own DB-level server_default=false (migration 0015) - both layers would silently agree "matched"
    for a row nobody ever actually classified, which is the exact opposite of what that schema
    extension existed to make visible. Removing the default here forces every caller to state a
    real confidence, closing the calculation-layer half of the compound gap (see migration 0017
    for the DB-level half). is_fallback_rate mirrors the same source file's own green/amber/grey
    distinction (a matched, real cost vs. an averaged stand-in) as a first-class, queryable part
    of the result - rate_confidence is "fallback" or "matched" - rather than something only
    readable from a spreadsheet's cell color.

    None when activity_based_rate is zero - a meaningless comparison, not a zero variance
    (§3.2), same posture as allocate_activity_cost's own zero-denominator handling elsewhere in
    this module.
    """
    if activity_based_rate == 0:
        return None
    activity_based_cost = round_currency(entity_activity_volume * activity_based_rate)
    variance = round_currency(currently_allocated_cost - activity_based_cost)
    return {
        "activity_based_cost": activity_based_cost,
        "currently_allocated_cost": round_currency(currently_allocated_cost),
        "variance": variance,
        "is_undercosted": variance < 0,
        "rate_confidence": "fallback" if is_fallback_rate else "matched",
    }


_EVIDENCE_TIER_BY_STATUS = {
    "unknown": 0, "not_applicable": 0,
    "legacy_unverified": 1,
    "estimated": 2,
    "calculated": 3,
    "confirmed": 4,
}

DOWNGRADE_APPROPRIATE_REASON_CODES = frozenset({"correction", "evidence_withdrawn", "source_data_restated"})


def classify_evidence_tier(status: str) -> int:
    """
    P-03: pure mirror of the DB-level evidence-tier ranking (check_event_chain_integrity's
    tier() function) - unknown/not_applicable = 0 (no evidence), legacy_unverified = 1,
    estimated = 2, calculated = 3, confirmed = 4. Raises on an unrecognised status rather than
    silently defaulting - a typo'd status string should fail loudly here, not rank as tier 0.
    """
    if status not in _EVIDENCE_TIER_BY_STATUS:
        raise ValueError(f"Unrecognised evidence status {status!r}")
    return _EVIDENCE_TIER_BY_STATUS[status]


def is_evidence_downgrade(*, previous_status: str | None, new_status: str) -> bool:
    """
    P-03: a genesis event (previous_status=None) is never a downgrade - there's nothing to
    downgrade from. A transition to the SAME tier (e.g. a recalculation that stays 'calculated')
    is also not a downgrade - a real, legitimate case, not an edge case to special-case away.
    """
    if previous_status is None:
        return False
    return classify_evidence_tier(new_status) < classify_evidence_tier(previous_status)


def calculate_variance_vs_prior(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    """current - prior. None if either side is unavailable (e.g. no prior-period snapshot exists
    yet) - never a fabricated zero implying "no change" when there's actually no baseline to
    compare against. Used for the canvas's DIO/DSO/DPO variance_vs_prior field."""
    if current is None or prior is None:
        return None
    return current - prior


def classify_aging_buckets(invoices: list[dict]) -> dict:
    """
    invoices: [{"amount": Decimal, "days_overdue": int}, ...]. Buckets: current (0-29 days),
    days_30 (30-59), days_60 (60-89), days_90 (90-119), days_120_plus (120+). Boundary is the
    lower bound, inclusive - exactly 30 days overdue lands in days_30, not current. This is the
    more conservative reading of an ambiguous boundary for a metric that flags collection risk -
    same posture as classify_expiry_risk's inclusive expiring_soon boundary (Phase 5b).
    """
    buckets: dict[str, Decimal] = {
        "current": Decimal(0), "days_30": Decimal(0), "days_60": Decimal(0),
        "days_90": Decimal(0), "days_120_plus": Decimal(0),
    }
    for invoice in invoices:
        days = invoice["days_overdue"]
        amount = invoice["amount"]
        if days < 30:
            buckets["current"] += amount
        elif days < 60:
            buckets["days_30"] += amount
        elif days < 90:
            buckets["days_60"] += amount
        elif days < 120:
            buckets["days_90"] += amount
        else:
            buckets["days_120_plus"] += amount
    return {key: round_currency(value) for key, value in buckets.items()}
