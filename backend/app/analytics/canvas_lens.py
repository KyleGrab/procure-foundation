"""
Canvas graph builders for the two approved lenses (Lens 1: Procurement, Lens 3: Warehouse &
Inventory - Lens 2 "Management Accounting" was dropped, no revenue/COGS data exists anywhere in
this codebase). Pure `Decimal`/`dataclass` - no SQLAlchemy, no FastAPI - same §2.1 boundary as
domain_graph.py. Not built on domain_graph.py's GraphNode/GraphEdge - this canvas's node shape
(metric_value, status, trend, details) is a genuinely different concept from that graph's topology
-plus-provenance shape, same "different concept, different name" reasoning as RebateBand vs
TieredEscalationBand (rebate_calculations.py's own docstring).

x/y coordinates are never computed here - same boundary as domain_graph.py: this engine produces
relationships and metrics, the frontend's dagre layout decides where to draw them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class NodeStatus(str, Enum):
    POSITIVE = "positive"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class CanvasNode:
    id: str
    node_type: str  # 'supplier' | 'category' | 'rebate_leakage' | 'contract_renewal' |
    # 'location' | 'inventory_aging'
    label: str
    metric_value: Decimal
    status: NodeStatus
    trend: str | None
    details: dict


@dataclass(frozen=True)
class CanvasEdge:
    id: str
    source_id: str
    target_id: str
    status: NodeStatus


@dataclass(frozen=True)
class CanvasGraph:
    nodes: list[CanvasNode]
    edges: list[CanvasEdge]


# ---------------------------------------------------------------------------
# Lens 1: Procurement Analysis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SupplierSpendInput:
    id: int
    public_id: str
    name: str
    category: str | None
    total_spend: Decimal


@dataclass(frozen=True)
class ContractRenewalInput:
    contract_public_id: str
    supplier_id: int
    title: str
    expiry_date: date
    status: str  # ContractStatus value - 'expiring_soon' | 'notice_period_open'


def build_procurement_lens_graph(
    suppliers: list[SupplierSpendInput], *, aggregate_leakage: Decimal, contract_renewals: list[ContractRenewalInput],
) -> CanvasGraph:
    """
    Supplier -> Category -> Rebate Leakage (single org-wide rollup node, every category feeds
    into it) & Contract Renewal (per-contract, connects to its supplier directly - a renewal
    event belongs to one specific relationship, not a whole category).
    """
    nodes: list[CanvasNode] = []
    edges: list[CanvasEdge] = []
    if not suppliers:
        return CanvasGraph(nodes=[], edges=[])

    category_totals: dict[str, Decimal] = {}
    supplier_by_id: dict[int, SupplierSpendInput] = {}

    for supplier in suppliers:
        supplier_by_id[supplier.id] = supplier
        category_key = supplier.category or "Uncategorised"
        nodes.append(CanvasNode(
            id=supplier.public_id, node_type="supplier", label=supplier.name,
            metric_value=supplier.total_spend, status=NodeStatus.POSITIVE, trend=None,
            details={"category": category_key},
        ))
        category_totals[category_key] = category_totals.get(category_key, Decimal("0")) + supplier.total_spend
        edges.append(CanvasEdge(
            id=f"{supplier.public_id}->category:{category_key}", source_id=supplier.public_id,
            target_id=f"category:{category_key}", status=NodeStatus.POSITIVE,
        ))

    for category_key, total in category_totals.items():
        nodes.append(CanvasNode(
            id=f"category:{category_key}", node_type="category", label=category_key,
            metric_value=total, status=NodeStatus.POSITIVE, trend=None, details={},
        ))
        edges.append(CanvasEdge(
            id=f"category:{category_key}->rebate_leakage", source_id=f"category:{category_key}",
            target_id="rebate_leakage", status=NodeStatus.POSITIVE,
        ))

    nodes.append(CanvasNode(
        id="rebate_leakage", node_type="rebate_leakage", label="Rebate Leakage",
        metric_value=aggregate_leakage,
        status=NodeStatus.CRITICAL if aggregate_leakage > 0 else NodeStatus.POSITIVE,
        trend=None, details={},
    ))

    for renewal in contract_renewals:
        supplier = supplier_by_id.get(renewal.supplier_id)
        if supplier is None:
            continue  # a renewal for a supplier not in this spend snapshot - not this graph's concern
        node_id = f"contract:{renewal.contract_public_id}"
        nodes.append(CanvasNode(
            id=node_id, node_type="contract_renewal", label=renewal.title,
            metric_value=Decimal("0"),
            status=NodeStatus.CRITICAL if renewal.status == "notice_period_open" else NodeStatus.WARNING,
            trend=None, details={"expiry_date": renewal.expiry_date.isoformat(), "status": renewal.status},
        ))
        edges.append(CanvasEdge(
            id=f"{supplier.public_id}->{node_id}", source_id=supplier.public_id, target_id=node_id,
            status=NodeStatus.WARNING,
        ))

    return CanvasGraph(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Lens 3: Warehouse & Inventory Performance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LocationInput:
    id: int
    public_id: str
    name: str


@dataclass(frozen=True)
class InventorySummaryInput:
    location_id: int
    description: str
    expiry_status: str  # ExpiryRisk value, already classified by the caller via
    # app.analytics.inventory_calculations.classify_expiry_risk - this module doesn't reclassify
    last_movement_days: int | None  # already computed via calculate_days_since_last_movement


def build_inventory_lens_graph(
    locations: list[LocationInput], summaries: list[InventorySummaryInput], *, stale_threshold_days: int,
) -> CanvasGraph:
    """
    Location -> Inventory Aging (one summary node per location, only for locations with real
    summary data - a location with zero inventory rows gets its own node but no aging node,
    since there's nothing honest to summarize). stale_threshold_days is a parameter (§2.4), not
    hardcoded - what counts as "stale" varies by what an organisation stocks.
    """
    nodes: list[CanvasNode] = []
    edges: list[CanvasEdge] = []
    if not locations:
        return CanvasGraph(nodes=[], edges=[])

    summaries_by_location: dict[int, list[InventorySummaryInput]] = {}
    for row in summaries:
        summaries_by_location.setdefault(row.location_id, []).append(row)

    for location in locations:
        nodes.append(CanvasNode(
            id=location.public_id, node_type="location", label=location.name,
            metric_value=Decimal(len(summaries_by_location.get(location.id, []))),
            status=NodeStatus.POSITIVE, trend=None, details={},
        ))

        location_rows = summaries_by_location.get(location.id, [])
        if not location_rows:
            continue

        expired_count = sum(1 for r in location_rows if r.expiry_status == "expired")
        expiring_soon_count = sum(1 for r in location_rows if r.expiry_status == "expiring_soon")
        stale_count = sum(
            1 for r in location_rows if r.last_movement_days is not None and r.last_movement_days > stale_threshold_days
        )
        flagged_count = expired_count + expiring_soon_count + stale_count

        if expired_count > 0:
            status = NodeStatus.CRITICAL
        elif expiring_soon_count > 0 or stale_count > 0:
            status = NodeStatus.WARNING
        else:
            status = NodeStatus.POSITIVE

        aging_node_id = f"aging:{location.public_id}"
        nodes.append(CanvasNode(
            id=aging_node_id, node_type="inventory_aging", label=f"{location.name} - Aging",
            metric_value=Decimal(flagged_count), status=status, trend=None,
            details={"expired": expired_count, "expiring_soon": expiring_soon_count, "stale": stale_count},
        ))
        edges.append(CanvasEdge(
            id=f"{location.public_id}->{aging_node_id}", source_id=location.public_id,
            target_id=aging_node_id, status=status,
        ))

    return CanvasGraph(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Lens: Management Accounting
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ManagementSummaryInput:
    gross_revenue: Decimal
    cogs: Decimal
    warehouse_abc_cost: Decimal
    logistics_cost: Decimal
    net_margin: Decimal
    dso: Decimal | None
    dio: Decimal | None
    dpo: Decimal | None
    ccc: Decimal | None
    dso_variance: Decimal | None
    dio_variance: Decimal | None
    dpo_variance: Decimal | None


_WC_FORMULAS = {
    "node-dso": "(Accounts Receivable / Annual Revenue) x 365",
    "node-dio": "(Inventory Value / Annual COGS) x 365",
    "node-dpo": "(Accounts Payable / Annual COGS) x 365",
}


def _wc_node(node_id: str, label: str, value: Decimal | None, variance: Decimal | None) -> CanvasNode:
    # CCC threshold judgment call, stated as one: lower is better, negative is excellent - no
    # established precedent for exact cutoffs anywhere in this codebase, so these are a
    # reasonable, documented default (not a fabricated universal truth) rather than left
    # unclassified. Adjustable if a real organisation's benchmark differs.
    if value is None:
        status = NodeStatus.POSITIVE  # no data yet is neutral, not alarming
    elif value <= 60:
        status = NodeStatus.POSITIVE
    elif value <= 90:
        status = NodeStatus.WARNING
    else:
        status = NodeStatus.CRITICAL
    return CanvasNode(
        id=node_id, node_type="working_capital_metric", label=label,
        metric_value=value if value is not None else Decimal("0"), status=status, trend=None,
        details={
            "value_days": str(value) if value is not None else None,
            "formula": _WC_FORMULAS.get(node_id),
            "variance_vs_prior": str(variance) if variance is not None else None,
        },
    )


def build_management_lens_graph(summary: ManagementSummaryInput) -> CanvasGraph:
    """
    Fixed node chain (this lens summarizes one organisation, not a per-entity breakdown like
    Lens 1/3 - there's exactly one Gross Revenue figure per org per period, not one per
    supplier). Gross Revenue -> COGS -> Warehouse ABC Costs -> Logistics & CTS ->
    Net Customer Profitability -> Working Capital Summary -> {DIO, DSO, DPO} -> CCC, with
    DIO/DSO/DPO fanning into CCC (matching the CCC = DIO + DSO - DPO formula's real inputs).
    """
    nodes = [
        CanvasNode(id="gross_revenue", node_type="revenue", label="Gross Revenue",
                   metric_value=summary.gross_revenue, status=NodeStatus.POSITIVE, trend=None, details={}),
        CanvasNode(id="cogs", node_type="cogs", label="COGS & Direct Materials",
                   metric_value=summary.cogs, status=NodeStatus.POSITIVE, trend=None, details={}),
        CanvasNode(id="warehouse_abc", node_type="warehouse_abc_cost", label="Warehouse ABC Costs",
                   metric_value=summary.warehouse_abc_cost, status=NodeStatus.POSITIVE, trend=None, details={}),
        CanvasNode(id="logistics_cts", node_type="logistics_cost", label="Logistics & CTS",
                   metric_value=summary.logistics_cost, status=NodeStatus.POSITIVE, trend=None, details={}),
        CanvasNode(
            id="net_profitability", node_type="net_margin", label="Net Customer Profitability",
            metric_value=summary.net_margin,
            status=NodeStatus.CRITICAL if summary.net_margin < 0 else NodeStatus.POSITIVE,
            trend=None, details={},
        ),
        CanvasNode(id="working_capital_summary", node_type="working_capital_summary", label="Working Capital Summary",
                   metric_value=Decimal("0"), status=NodeStatus.POSITIVE, trend=None, details={}),
        _wc_node("node-dso", "Days Sales Outstanding", summary.dso, summary.dso_variance),
        _wc_node("node-dio", "Days Inventory Outstanding", summary.dio, summary.dio_variance),
        _wc_node("node-dpo", "Days Payables Outstanding", summary.dpo, summary.dpo_variance),
        CanvasNode(
            id="node-ccc", node_type="cash_conversion_cycle", label="Cash Conversion Cycle",
            metric_value=summary.ccc if summary.ccc is not None else Decimal("0"),
            status=(
                NodeStatus.POSITIVE if summary.ccc is None or summary.ccc <= 60
                else NodeStatus.WARNING if summary.ccc <= 90 else NodeStatus.CRITICAL
            ),
            trend=None,
            details={"total_ccc_days": str(summary.ccc) if summary.ccc is not None else None},
        ),
    ]

    chain = ["gross_revenue", "cogs", "warehouse_abc", "logistics_cts", "net_profitability", "working_capital_summary"]
    edges = [
        CanvasEdge(id=f"{a}->{b}", source_id=a, target_id=b, status=NodeStatus.POSITIVE)
        for a, b in zip(chain, chain[1:])
    ]
    edges += [
        CanvasEdge(id="working_capital_summary->node-dso", source_id="working_capital_summary",
                   target_id="node-dso", status=NodeStatus.POSITIVE),
        CanvasEdge(id="working_capital_summary->node-dio", source_id="working_capital_summary",
                   target_id="node-dio", status=NodeStatus.POSITIVE),
        CanvasEdge(id="working_capital_summary->node-dpo", source_id="working_capital_summary",
                   target_id="node-dpo", status=NodeStatus.POSITIVE),
        # DSO and DIO add into CCC, DPO subtracts - both rendered as animated edges per the
        # request; sign is carried in the formula the CCC node's own value already reflects
        # (CCC = DIO + DSO - DPO), not re-encoded a second time in edge metadata that could drift.
        CanvasEdge(id="node-dio->node-ccc", source_id="node-dio", target_id="node-ccc", status=NodeStatus.WARNING),
        CanvasEdge(id="node-dso->node-ccc", source_id="node-dso", target_id="node-ccc", status=NodeStatus.WARNING),
        CanvasEdge(id="node-dpo->node-ccc", source_id="node-dpo", target_id="node-ccc", status=NodeStatus.WARNING),
    ]

    return CanvasGraph(nodes=nodes, edges=edges)
