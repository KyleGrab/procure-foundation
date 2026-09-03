"""Purchase transaction upload API (Phase 4b). Thin route - ingestion + recalculation logic in
services/purchase_transaction_service.py, mapping/validation reused from Phase 2's
app.ingestion.* per docs/decisions/ADR-013."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.exceptions import NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import Supplier
from app.db.session import get_db
from app.ingestion.excel_reader import read_xlsx_rows
from app.ingestion.mapping import apply_mapping
from app.ingestion.purchase_transaction_mapping import suggest_purchase_transaction_mapping
from app.ingestion.purchase_transaction_validation import validate_purchase_transaction_rows
from app.integrations.object_storage import get_storage
from app.services import purchase_transaction_service

router = APIRouter(prefix="/purchase-transactions", tags=["purchase-transactions"])


@router.post("/{supplier_public_id}/upload", status_code=201)
async def upload_purchase_transactions(
    supplier_public_id: str, file: UploadFile,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Reads the file, suggests a mapping (spec Section 3's confirm-before-processing rule still
    applies - suggested_mapping is not auto-applied; a follow-up confirm step mirroring
    price_reviews' /mapping route belongs here before a production rollout, omitted in this
    delivery for the same reason price_reviews' matching-orchestration route stayed thin). Row
    validation uses a purpose-built purchase-transaction validator, not price_review's
    validate_rows - see app/ingestion/purchase_transaction_validation.py's docstring for why that
    reuse would have silently rejected every row.
    """
    supplier_result = await db.execute(select(Supplier).where(Supplier.public_id == supplier_public_id))
    supplier = supplier_result.scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier not found")

    file_bytes = await file.read()
    extension = Path(file.filename or "upload.xlsx").suffix.lstrip(".") or "xlsx"
    storage_key = await get_storage().put(claims.active_org_id, file_bytes, extension)

    raw_path = Path(f"/tmp/{storage_key.split('/')[-1]}")
    raw_path.write_bytes(file_bytes)
    raw_rows = read_xlsx_rows(raw_path)
    if not raw_rows:
        return {"row_count": 0, "ingested": 0}

    mapping = suggest_purchase_transaction_mapping(list(raw_rows[0].keys()))
    mapped_rows = [apply_mapping(r, mapping) for r in raw_rows]
    # Purpose-built validator, not app.ingestion.validation.validate_rows - that one is
    # price-review-specific (checks a `price`/`pack_size` field neither of which exists on a
    # transaction row) and was confirmed, by actually running it, to reject every row with a
    # fabricated "Missing price" error. See app/ingestion/purchase_transaction_validation.py.
    validated = validate_purchase_transaction_rows(mapped_rows)
    valid_rows = [mapped_rows[i] for i, v in enumerate(validated) if v["is_valid"]]

    transactions = await purchase_transaction_service.ingest_transactions(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, supplier_id=supplier.id,
        mapped_rows=valid_rows, source_file_storage_key=storage_key,
    )
    return {
        "row_count": len(raw_rows),
        "ingested": len(transactions),
        "rejected": len(raw_rows) - len(valid_rows),
        "suggested_mapping": mapping,
    }
