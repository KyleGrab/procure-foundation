"""
Treasury FX exposure endpoint. Follows app/api/v1/logistics.py's established pattern exactly -
JWT-derived active_org_id, the global 503 DatabaseUnavailableError wrapping (automatic via
Depends(get_db)), 422 via ValidationFailedError with a structured details array.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.exceptions import ValidationFailedError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.session import get_db
from app.services.treasury_service import ingest_fx_transaction

router = APIRouter(prefix="/treasury", tags=["treasury"])


class FxExposureRequest(BaseModel):
    transaction_date: date
    reporting_date: date
    customer_id: str | None = None
    currency_code: str
    foreign_currency_amount: Decimal
    transaction_date_spot_rate: Decimal
    reporting_date_spot_rate: Decimal
    fec_contract_rate: Decimal | None = None


@router.post("/calculate-exposure", status_code=201)
async def calculate_exposure(
    payload: FxExposureRequest,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # calculate_fx_transaction_exposure's own ValueError/TypeError (missing/non-positive rates)
    # is caught here and mapped to a structured 422 - main.py's generic handler only recognizes
    # ProcureIQError subclasses, not raw ValueError/TypeError, so this mapping is explicit.
    try:
        result = await ingest_fx_transaction(
            db, organisation_id=claims.active_org_id, user_id=claims.user_id,
            transaction_date=payload.transaction_date, reporting_date=payload.reporting_date,
            currency_code=payload.currency_code, foreign_currency_amount=payload.foreign_currency_amount,
            transaction_date_spot_rate=payload.transaction_date_spot_rate,
            reporting_date_spot_rate=payload.reporting_date_spot_rate,
            fec_contract_rate=payload.fec_contract_rate, customer_id=payload.customer_id,
        )
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError(
            "FX exposure calculation failed validation", details=[{"field": "spot_rate", "message": str(exc)}],
        ) from exc

    # Shaped to plug directly into build_management_canvas_payload as a dedicated treasury risk
    # widget - that orchestrator's signature is already generic (four callables), so no change
    # to canvas_payload.py is needed; a caller wires this in as
    # risk_layer_fn=lambda: calculate_exposure_result_from_this_route(...), same pattern as
    # route profitability was wired into the operations layer last turn.
    return {
        "snapshot_id": result["snapshot_id"], "snapshot_public_id": result["snapshot_public_id"],
        "is_hedged": result["is_hedged"],
        "unrealized_variance": str(result["unrealized_variance"]) if result["unrealized_variance"] is not None else None,
        "hedging_gain_loss": str(result["hedging_gain_loss"]) if result["hedging_gain_loss"] is not None else None,
    }
