"""
AI copilot routes (Phase 5): /ai/query implements docs/architecture.md §1's pipeline for real
(app.ai.copilot_service), and /ai/negotiation-brief is the general-purpose sibling of
/price-reviews/{id}/negotiation-brief (ADR-016 - same generator, a spend-sourced context builder
instead of a price-review one). Neither has ever been executed in this sandbox - no network, no
LLM_API_KEY - same constraint as every AI-touching route since Phase 2.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.copilot_service import answer_query
from app.ai.llm_provider import get_llm_provider
from app.core.constants import Permission
from app.core.exceptions import NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import Supplier
from app.db.session import get_db
from app.schemas.ai_copilot import CopilotQueryRequest, CopilotQueryResponse
from app.services.negotiation_brief_service import (
    build_negotiation_brief_context_from_spend,
    generate_brief,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/query", response_model=CopilotQueryResponse)
async def query_copilot(
    payload: CopilotQueryRequest,
    claims: AccessTokenClaims = Depends(require_permission(Permission.ACCESS_AI)),
    db: AsyncSession = Depends(get_db),
) -> CopilotQueryResponse:
    """
    Permission check here is deliberately loose (ACCESS_AI - "can use the copilot at all") - the
    real, per-question permission check happens inside answer_query against whichever specific
    intent gets classified (a VIEWER might have ACCESS_AI but not VIEW_CONTRACTS, and must still
    be refused a contract-expiry question even though they're allowed to ask spend questions).
    UnsupportedIntentError (a question outside the fixed intent set) becomes a normal 422
    response via ProcureIQError's exception handler (app/main.py) - never a 500, and never a
    fallback that tries to answer anyway.
    """
    result = await answer_query(
        db, get_llm_provider(), organisation_id=claims.active_org_id, role=claims.role,
        question=payload.question,
    )
    return CopilotQueryResponse(**result)


@router.post("/negotiation-brief")
async def generate_general_negotiation_brief(
    supplier_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.ACCESS_AI)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """ADR-016: the general-purpose sibling of /price-reviews/{id}/negotiation-brief - same
    generator, sourced from spend analytics + contracts instead of a price review."""
    result = await db.execute(select(Supplier).where(Supplier.public_id == supplier_public_id))
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier not found")

    context = await build_negotiation_brief_context_from_spend(
        db, organisation_id=claims.active_org_id, supplier=supplier
    )
    brief = await generate_brief(get_llm_provider(), context)
    return {"brief": brief.model_dump()}
