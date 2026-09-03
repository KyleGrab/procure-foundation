"""Purchase invoice ingestion routes (Phase 4c, append-only per ADR-006)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.constants import Permission
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.session import get_db
from app.schemas.purchase_invoice import PurchaseInvoiceIngest
from app.services import purchase_ledger_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/purchase-invoices", tags=["purchase-invoices"])


@router.post("", status_code=201)
async def ingest_purchase_invoice(
    payload: PurchaseInvoiceIngest,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Append-only - there is no PATCH/PUT route for a posted invoice, on purpose (ADR-006). A wrong
    invoice needs a correction endpoint referencing corrects_id - not built in this delivery
    (noted, not silently missing): the ingest path itself, and the PPV it triggers per line when
    a reference_price is supplied, is what Phase 4c's "financial calculation engine" framing was
    actually about.
    """
    invoice, ppv_results = await purchase_ledger_service.ingest_purchase_invoice(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return {
        "invoice_public_id": str(invoice.public_id),
        "invoice_number": invoice.invoice_number,
        "line_count": len(payload.lines),
        "price_variance_lines": [
            {
                "supplier_sku": r["supplier_sku"],
                "reference_price_source": r["reference_price_source"].value if r["reference_price_source"] else None,
                "expected_cost": str(r["expected_cost"]), "actual_cost": str(r["actual_cost"]),
                "variance": str(r["variance"]),
                "variance_pct": str(r["variance_pct"]) if r["variance_pct"] is not None else None,
            }
            for r in ppv_results
        ],
    }
