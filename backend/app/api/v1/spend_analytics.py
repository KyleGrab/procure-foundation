"""Spend analytics routes (Phase 5). Read-only, thin - logic in services/spend_analytics_service.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.exceptions import NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import Supplier
from app.db.session import get_db
from app.schemas.spend_analytics import (
    ABCResultRead,
    ParetoResultRead,
    PriceConsistencyRead,
    SpendItemRead,
)
from app.services import spend_analytics_service

router = APIRouter(prefix="/spend-analytics", tags=["spend-analytics"])


@router.get("/trend")
async def month_over_month_trend(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    points = await spend_analytics_service.get_month_over_month_trend(db, organisation_id=claims.active_org_id)
    return [
        {"month": p.month_label, "amount": str(p.amount),
         "change_pct": str(p.change_pct) if p.change_pct is not None else None}
        for p in points
    ]


@router.get("/top-price-increases")
async def top_price_increases(
    limit: int = 10,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await spend_analytics_service.get_top_supplier_price_increases(
        db, organisation_id=claims.active_org_id, limit=limit
    )


@router.get("/by-supplier", response_model=list[SpendItemRead])
async def spend_by_supplier(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[SpendItemRead]:
    items = await spend_analytics_service.get_spend_by_supplier(db, organisation_id=claims.active_org_id)
    return [SpendItemRead(key=i.key, label=i.label, amount=i.amount) for i in items]


@router.get("/by-sku", response_model=list[SpendItemRead])
async def spend_by_sku(
    supplier_public_id: str | None = None,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[SpendItemRead]:
    supplier_id = None
    if supplier_public_id:
        result = await db.execute(select(Supplier.id).where(Supplier.public_id == supplier_public_id))
        supplier_id = result.scalar_one_or_none()
        if supplier_id is None:
            raise NotFoundError("Supplier not found")
    items = await spend_analytics_service.get_spend_by_sku(
        db, organisation_id=claims.active_org_id, supplier_id=supplier_id
    )
    return [SpendItemRead(key=i.key, label=i.label, amount=i.amount) for i in items]


@router.get("/abc-classification", response_model=list[ABCResultRead])
async def abc_classification(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[ABCResultRead]:
    results = await spend_analytics_service.get_abc_classification(db, organisation_id=claims.active_org_id)
    return [
        ABCResultRead(
            item=SpendItemRead(key=r.item.key, label=r.item.label, amount=r.item.amount),
            cumulative_pct=r.cumulative_pct, classification=r.classification.value,
        )
        for r in results
    ]


@router.get("/pareto", response_model=ParetoResultRead)
async def pareto_contributors(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> ParetoResultRead:
    result = await spend_analytics_service.get_pareto_contributors(db, organisation_id=claims.active_org_id)
    return ParetoResultRead(
        contributors=[SpendItemRead(key=c.key, label=c.label, amount=c.amount) for c in result.contributors],
        contributor_count=result.contributor_count, total_item_count=result.total_item_count,
        cumulative_pct_covered=result.cumulative_pct_covered,
    )


@router.get("/price-variance/{supplier_public_id}", response_model=PriceConsistencyRead)
async def price_variance_check(
    supplier_public_id: str, sku_or_description: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> PriceConsistencyRead:
    result_supplier = await db.execute(select(Supplier).where(Supplier.public_id == supplier_public_id))
    supplier = result_supplier.scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier not found")

    result = await spend_analytics_service.check_price_consistency(
        db, organisation_id=claims.active_org_id, supplier_id=supplier.id, sku_or_description=sku_or_description,
    )
    return PriceConsistencyRead(
        supplier_public_id=supplier.public_id, sku_or_description=sku_or_description,
        min_price=result.min_price, max_price=result.max_price, spread=result.spread,
        spread_pct=result.spread_pct, is_significant=result.is_significant,
        observation_count=result.observation_count,
    )
