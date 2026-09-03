"""Purchase order routes (Phase 4c). Thin - logic in services/purchase_ledger_service.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.exceptions import NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import PurchaseOrder, PurchaseOrderLine, Supplier
from app.db.session import get_db
from app.schemas.purchase_order import PurchaseOrderCreate, PurchaseOrderRead
from app.services import purchase_ledger_service

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


@router.post("", response_model=PurchaseOrderRead, status_code=201)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> PurchaseOrderRead:
    order = await purchase_ledger_service.create_purchase_order(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return await _to_read_model(db, order, payload.supplier_public_id)


@router.get("/{order_public_id}", response_model=PurchaseOrderRead)
async def get_purchase_order(
    order_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> PurchaseOrderRead:
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.public_id == order_public_id))
    order = result.scalar_one_or_none()
    if order is None:
        raise NotFoundError("Purchase order not found")
    supplier_result = await db.execute(select(Supplier.public_id).where(Supplier.id == order.supplier_id))
    return await _to_read_model(db, order, supplier_result.scalar_one())


async def _to_read_model(db: AsyncSession, order: PurchaseOrder, supplier_public_id) -> PurchaseOrderRead:
    lines_result = await db.execute(
        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == order.id)
    )
    return PurchaseOrderRead(
        public_id=order.public_id, supplier_public_id=supplier_public_id, po_number=order.po_number,
        order_date=order.order_date, expected_delivery_date=order.expected_delivery_date,
        status=order.status, currency=order.currency,
        lines=[
            {"public_id": l.public_id, "supplier_sku": l.supplier_sku, "description": l.description,
             "quantity_ordered": l.quantity_ordered, "unit_price": l.unit_price, "line_total": l.line_total}
            for l in lines_result.scalars().all()
        ],
    )
