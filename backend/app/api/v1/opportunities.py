"""Opportunity register routes (Phase 2 minimal CRUD, Phase 5 waterfall/savings-type extension)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.domain_graph import ConsolidationReviewAction
from app.core.constants import Permission
from app.core.exceptions import NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import DuplicateSkuFlag, Opportunity, Supplier, SupplierConsolidationFlag
from app.db.session import get_db
from app.schemas.opportunity import (
    ConsolidationFlagReviewRequest,
    OpportunityCreate,
    OpportunityRead,
    OpportunityRealise,
)
from app.services import duplicate_detection_service, opportunity_service

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


async def _get_opportunity(db: AsyncSession, public_id: str) -> Opportunity:
    result = await db.execute(select(Opportunity).where(Opportunity.public_id == public_id))
    opportunity = result.scalar_one_or_none()
    if opportunity is None:
        raise NotFoundError("Opportunity not found")
    return opportunity


@router.post("", response_model=OpportunityRead, status_code=201)
async def create_opportunity(
    payload: OpportunityCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_OPPORTUNITIES)),
    db: AsyncSession = Depends(get_db),
) -> OpportunityRead:
    opportunity = await opportunity_service.create_opportunity(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return OpportunityRead.model_validate(opportunity)


@router.get("", response_model=list[OpportunityRead])
async def list_opportunities(
    savings_type: str | None = None, status: str | None = None,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[OpportunityRead]:
    opportunities = await opportunity_service.list_opportunities(
        db, organisation_id=claims.active_org_id, savings_type=savings_type, status=status
    )
    return [OpportunityRead.model_validate(o) for o in opportunities]


@router.post("/{opportunity_public_id}/advance", response_model=OpportunityRead)
async def advance_opportunity_stage(
    opportunity_public_id: str, target_status: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_OPPORTUNITIES)),
    db: AsyncSession = Depends(get_db),
) -> OpportunityRead:
    opportunity = await _get_opportunity(db, opportunity_public_id)
    updated = await opportunity_service.advance_waterfall_stage(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id,
        opportunity=opportunity, target_status=target_status,
    )
    return OpportunityRead.model_validate(updated)


@router.post("/{opportunity_public_id}/realise", response_model=OpportunityRead)
async def realise_opportunity(
    opportunity_public_id: str, payload: OpportunityRealise,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_SAVINGS)),
    db: AsyncSession = Depends(get_db),
) -> OpportunityRead:
    opportunity = await _get_opportunity(db, opportunity_public_id)
    updated = await opportunity_service.record_realised_savings(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id,
        opportunity=opportunity, realised_savings=payload.realised_savings,
        effective_period_start=payload.effective_period_start, effective_period_end=payload.effective_period_end,
        documented_baseline_reference=payload.documented_baseline_reference,
        actual_cost_source_reference=payload.actual_cost_source_reference,
        variance_calculation_reference=payload.variance_calculation_reference,
        change_reference=f"api_realise_opportunity:{opportunity_public_id}",
    )
    return OpportunityRead.model_validate(updated)


@router.post("/duplicate-sku-scan/{supplier_public_id}")
async def scan_duplicate_skus(
    supplier_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.EDIT_SUPPLIERS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """spec §107. Reuses Phase 2's matching engine (app.matching.scorer) - never auto-merges,
    only flags for human review (see app.services.duplicate_detection_service)."""
    result = await db.execute(select(Supplier.id).where(Supplier.public_id == supplier_public_id))
    supplier_id = result.scalar_one_or_none()
    if supplier_id is None:
        raise NotFoundError("Supplier not found")
    flags = await duplicate_detection_service.scan_supplier_for_duplicate_skus(
        db, organisation_id=claims.active_org_id, supplier_id=supplier_id
    )
    return {"new_flags": len(flags)}


@router.get("/duplicate-sku-flags")
async def list_duplicate_sku_flags(
    status: str | None = None,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(DuplicateSkuFlag)
    if status:
        query = query.where(DuplicateSkuFlag.status == status)
    result = await db.execute(query)
    return [
        {"public_id": str(f.public_id), "sku_a": f.sku_a, "description_a": f.description_a,
         "sku_b": f.sku_b, "description_b": f.description_b,
         "similarity_score": str(f.similarity_score), "match_method": f.match_method, "status": f.status}
        for f in result.scalars().all()
    ]


@router.post("/consolidation-scan")
async def scan_supplier_consolidation(
    claims: AccessTokenClaims = Depends(require_permission(Permission.EDIT_SUPPLIERS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """spec §22 - flags only, never an auto-recommendation. See
    app.services.duplicate_detection_service.scan_for_supplier_consolidation's docstring for why."""
    flags = await duplicate_detection_service.scan_for_supplier_consolidation(
        db, organisation_id=claims.active_org_id
    )
    return {"new_flags": len(flags)}


@router.get("/consolidation-flags")
async def list_consolidation_flags(
    status: str | None = None,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(SupplierConsolidationFlag)
    if status:
        query = query.where(SupplierConsolidationFlag.status == status)
    result = await db.execute(query)
    return [
        {"public_id": str(f.public_id), "description_a": f.description_a, "description_b": f.description_b,
         "similarity_score": str(f.similarity_score), "combined_spend": str(f.combined_spend) if f.combined_spend else None,
         "status": f.status}
        for f in result.scalars().all()
    ]


@router.post("/duplicate-sku-flags/{flag_public_id}/review")
async def review_duplicate_sku_flag_route(
    flag_public_id: str, confirmed: bool,
    claims: AccessTokenClaims = Depends(require_permission(Permission.EDIT_SUPPLIERS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wires up app.services.duplicate_detection_service.review_duplicate_sku_flag - the
    never-silently-merge human-confirmation gate. Was left unrouted when the service function was
    first written; added here rather than left as a frontend TODO, since the service logic
    already existed and exposing it is a small, low-risk addition."""
    result = await db.execute(select(DuplicateSkuFlag).where(DuplicateSkuFlag.public_id == flag_public_id))
    flag = result.scalar_one_or_none()
    if flag is None:
        raise NotFoundError("Duplicate SKU flag not found")
    updated = await duplicate_detection_service.review_duplicate_sku_flag(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, flag=flag, confirmed=confirmed,
    )
    return {"public_id": str(updated.public_id), "status": updated.status}


@router.get("/consolidation-graph")
async def get_consolidation_graph(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Node-edge payload for the React Flow consolidation graph view
    (dashboard/opportunities/consolidation-graph). All orchestration in
    app.services.duplicate_detection_service.build_consolidation_graph_payload - this route does
    nothing but the permission check and the call."""
    return await duplicate_detection_service.build_consolidation_graph_payload(
        db, organisation_id=claims.active_org_id
    )


@router.post("/consolidation-flags/{flag_public_id}/review")
async def review_consolidation_flag_route(
    flag_public_id: str, payload: ConsolidationFlagReviewRequest,
    claims: AccessTokenClaims = Depends(require_permission(Permission.EDIT_SUPPLIERS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Same permission level and minimal-dict response shape as the duplicate-SKU flag review
    route above, for parity. InvalidConsolidationTransitionError (e.g. reviewing an already-
    terminal flag) is a ProcureIQError -> propagates as a 409 via app.main's exception handler,
    not caught here."""
    result = await db.execute(
        select(SupplierConsolidationFlag).where(SupplierConsolidationFlag.public_id == flag_public_id)
    )
    flag = result.scalar_one_or_none()
    if flag is None:
        raise NotFoundError("Consolidation flag not found")

    updated = await duplicate_detection_service.review_consolidation_flag(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, flag=flag,
        action=ConsolidationReviewAction(payload.action), notes=payload.notes,
    )
    return {
        "public_id": str(updated.public_id), "status": updated.status,
        "review_notes": updated.review_notes,
        "reviewed_at": updated.reviewed_at.isoformat() if updated.reviewed_at else None,
    }
