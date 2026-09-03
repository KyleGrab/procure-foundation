"""Goods receipt routes (Phase 4c, append-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.session import get_db
from app.schemas.goods_receipt import GoodsReceiptCreate
from app.services import purchase_ledger_service

router = APIRouter(prefix="/goods-receipts", tags=["goods-receipts"])


@router.post("", status_code=201)
async def record_goods_receipt(
    payload: GoodsReceiptCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    receipt, variance_results = await purchase_ledger_service.record_goods_receipt(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return {
        "receipt_public_id": str(receipt.public_id),
        "line_count": len(payload.lines),
        "variance": [
            {
                "supplier_sku": r["supplier_sku"], "variance_quantity": str(r["variance_quantity"]),
                "variance_pct": str(r["variance_pct"]) if r["variance_pct"] is not None else None,
                "status": r["status"],
            }
            for r in variance_results
        ],
    }
