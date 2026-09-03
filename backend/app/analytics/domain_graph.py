"""
Supplier Consolidation Graph (Candidate A, approved). Pure `Decimal`/`dataclass` - no SQLAlchemy,
no FastAPI - same §2.1 boundary as every analytics module in this codebase. The service layer
(not built yet) is responsible for fetching Supplier/SupplierConsolidationFlag rows and mapping
them into the Input dataclasses below; this module only transforms already-fetched plain data
into a node-edge graph payload.

Deliberately no timestamp/`generated_at` field and no `datetime`/`time` import anywhere in this
module - a pure function calling `datetime.now()` internally is non-deterministic and breaks the
byte-identical-output guarantee §7.3 requires (tests_pure/test_domain_graph.py checks this
structurally, not just functionally). If a caller needs a generation timestamp, it's added by the
service layer after this function returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.core.exceptions import ProcureIQError


class UnknownSupplierError(ProcureIQError):
    """A flag referenced a supplier_id not present in the supplied supplier list - a caller bug
    (real FK-backed data can't produce this), not a data condition to silently skip. See §5.2."""
    code = "unknown_supplier_in_consolidation_flag"
    status_code = 500


class InvalidConsolidationTransitionError(ProcureIQError):
    """Raised for any transition not in _ALLOWED_TRANSITIONS below - including an unrecognized
    current_status and an action targeting a terminal state. Same posture as
    UnknownSupplierError: raise clearly (§5.2), never silently no-op or clamp to a nearby valid
    state."""
    code = "invalid_consolidation_flag_transition"
    status_code = 409


class ConsolidationReviewAction(str, Enum):
    MARK_UNDER_REVIEW = "mark_under_review"
    RECOMMEND_CONSOLIDATION = "recommend_consolidation"
    REJECT = "reject"


_ACTION_TARGET_STATUS: dict[ConsolidationReviewAction, str] = {
    ConsolidationReviewAction.MARK_UNDER_REVIEW: "under_review",
    ConsolidationReviewAction.RECOMMEND_CONSOLIDATION: "consolidation_recommended",
    ConsolidationReviewAction.REJECT: "rejected",
}

# SupplierConsolidationFlag.status's real vocabulary (app/db/models/opportunity_flags.py) -
# consolidation_recommended and rejected are terminal (empty target sets): a human decision,
# per that model's own comment, "never set by the flagging process itself" - once made, final.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "flagged": {"under_review", "consolidation_recommended", "rejected"},
    "under_review": {"consolidation_recommended", "rejected"},
    "consolidation_recommended": set(),
    "rejected": set(),
}


def determine_consolidation_flag_transition(current_status: str, action: ConsolidationReviewAction) -> str:
    """Pure state-machine check for the SupplierConsolidationFlag review workflow. Returns the
    new status, or raises InvalidConsolidationTransitionError - never returns an invalid status,
    never silently keeps the current one."""
    if current_status not in _ALLOWED_TRANSITIONS:
        raise InvalidConsolidationTransitionError(f"Unknown current status: {current_status!r}")
    target_status = _ACTION_TARGET_STATUS[action]
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise InvalidConsolidationTransitionError(
            f"Cannot go from {current_status!r} to {target_status!r} via action {action.value!r}"
        )
    return target_status


@dataclass(frozen=True)
class SupplierInput:
    id: int          # internal PK - used only to match flags to suppliers, never exposed
    public_id: str    # the externally-safe identifier, matching ADR-005's public_id convention
    name: str


@dataclass(frozen=True)
class ConsolidationFlagInput:
    supplier_a_id: int
    supplier_b_id: int
    description_a: str
    description_b: str
    similarity_score: Decimal
    combined_spend: Decimal | None
    status: str  # verbatim from SupplierConsolidationFlag.status - never relabeled (§2.7)
    match_method: str = "unknown"  # defaulted, not required positionally - see this module's
    # test file for why: adding this as a required field would have meant touching all 10
    # existing ConsolidationFlagInput(...) call sites in tests_pure/test_domain_graph.py, each
    # one a risk of the exact kind of mistake a prior line-numbered edit already made once this
    # session. The service layer always passes a real value explicitly; this default is a
    # test-convenience fallback only, never hit in the real ingestion path.


@dataclass(frozen=True)
class GraphNode:
    id: str           # supplier.public_id
    label: str         # supplier.name
    node_type: str      # 'supplier'
    source: str          # which table produced this node - 'suppliers'
    metadata: dict


@dataclass(frozen=True)
class GraphEdge:
    source_id: str     # supplier_a.public_id
    target_id: str      # supplier_b.public_id
    weight: Decimal       # resolved for layout/sizing: combined_spend if known, else similarity_score
    similarity_score: Decimal      # raw, always present - kept alongside weight, not folded away
    combined_spend: Decimal | None   # raw, may be unknown - never fabricated when absent
    match_method: str                  # verbatim from the flag - how the match was actually derived
    status: str             # the flag's real status column, copied verbatim
    source: str               # 'supplier_consolidation_flags'


@dataclass(frozen=True)
class DomainGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def build_supplier_consolidation_graph(
    suppliers: list[SupplierInput], flags: list[ConsolidationFlagInput],
) -> DomainGraph:
    """
    One node per unique supplier touched by any flag (de-duplicated, first-seen order - so output
    is deterministic given deterministic input order, without needing an explicit sort). One edge
    per flag, in input order. Empty flags -> empty graph, not an error.
    """
    suppliers_by_id = {s.id: s for s in suppliers}

    nodes: list[GraphNode] = []
    seen_supplier_ids: set[int] = set()
    edges: list[GraphEdge] = []

    for flag in flags:
        for supplier_id in (flag.supplier_a_id, flag.supplier_b_id):
            if supplier_id not in suppliers_by_id:
                raise UnknownSupplierError(
                    f"Consolidation flag references supplier_id={supplier_id}, "
                    f"which was not in the supplied supplier list"
                )
            if supplier_id not in seen_supplier_ids:
                supplier = suppliers_by_id[supplier_id]
                nodes.append(GraphNode(
                    id=supplier.public_id, label=supplier.name, node_type="supplier",
                    source="suppliers", metadata={},
                ))
                seen_supplier_ids.add(supplier_id)

        weight = flag.combined_spend if flag.combined_spend is not None else flag.similarity_score
        edges.append(GraphEdge(
            source_id=suppliers_by_id[flag.supplier_a_id].public_id,
            target_id=suppliers_by_id[flag.supplier_b_id].public_id,
            weight=weight, similarity_score=flag.similarity_score, combined_spend=flag.combined_spend,
            match_method=flag.match_method, status=flag.status, source="supplier_consolidation_flags",
        ))

    return DomainGraph(nodes=nodes, edges=edges)
