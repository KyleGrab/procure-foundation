"""
Visual analysis canvas routes. Three lenses - 'procurement', 'operations', and 'management'.
'management' reads from working_capital_snapshots/cost_to_serve_ledger (migration 0014) - an
organisation with no data ingested into those tables yet gets an empty graph, not an error and
not a fabricated one. RLS via get_db (claims.active_org_id -> app.current_org_id session
variable), RBAC via require_permission - same pattern as every other route in this codebase.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.exceptions import ValidationFailedError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.session import get_db
from app.services import canvas_service

router = APIRouter(prefix="/canvas", tags=["canvas"])


def _serialize_graph(graph) -> dict:
    return {
        "nodes": [
            {
                "id": n.id, "type": "customLensNode",
                "data": {
                    "label": n.label, "nodeType": n.node_type, "metricValue": str(n.metric_value),
                    "status": n.status.value, "trend": n.trend, "details": n.details,
                },
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "id": e.id, "source": e.source_id, "target": e.target_id,
                "animated": e.status.value != "positive",
                "style": {"stroke": {"positive": "#34D399", "warning": "#FBBF24", "critical": "#F87171"}[e.status.value]},
            }
            for e in graph.edges
        ],
    }


@router.get("/nodes")
async def get_canvas_nodes(
    lens: Literal["procurement", "operations", "management"] = Query(...),
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if lens == "procurement":
        graph = await canvas_service.build_procurement_lens(db, organisation_id=claims.active_org_id)
    elif lens == "operations":
        graph = await canvas_service.build_inventory_lens(db, organisation_id=claims.active_org_id)
    elif lens == "management":
        graph = await canvas_service.build_management_lens(db, organisation_id=claims.active_org_id)
    else:
        # Unreachable given Literal[...] validation above rejects anything else with a 422 before
        # this function body runs - kept as an explicit raise rather than silently falling
        # through, matching §5.2 (never fail silently) even for a case FastAPI itself guards.
        raise ValidationFailedError(f"Unsupported lens: {lens!r}")

    return _serialize_graph(graph)
