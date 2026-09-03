"""
DB orchestration for FX transaction snapshots. No calculation logic of its own -
app.analytics.treasury_engine.calculate_fx_transaction_exposure (real, tested,
tests_pure/test_treasury_engine.py) does every number. Matches
route_profitability_service.py's shape - no period-locking (multiple real FX transactions
genuinely happen on the same date for the same organisation), corrects_id for genuine
re-ingestion of a specific transaction's corrected figures.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.treasury_engine import calculate_fx_transaction_exposure
from app.db.models import FXTransactionSnapshot
from app.services import audit_service


async def ingest_fx_transaction(
    db: AsyncSession, *, organisation_id: int, user_id: int, transaction_date: date, reporting_date: date,
    currency_code: str, foreign_currency_amount: Decimal, transaction_date_spot_rate: Decimal,
    reporting_date_spot_rate: Decimal, fec_contract_rate: Decimal | None = None,
    supplier_id: int | None = None, customer_id: str | None = None, corrects_id: int | None = None,
) -> dict:
    """
    Calls calculate_fx_transaction_exposure (raises ValueError/TypeError on any invalid or
    missing input - never reaches this function's DB write on bad data) and persists the
    mutually-exclusive result exactly as computed - is_hedged, and exactly one of
    unrealized_variance/hedging_gain_loss, matching the DB-level CHECK constraint precisely.
    """
    result = calculate_fx_transaction_exposure(
        foreign_currency_amount=foreign_currency_amount, transaction_date_spot_rate=transaction_date_spot_rate,
        reporting_date_spot_rate=reporting_date_spot_rate, fec_contract_rate=fec_contract_rate,
    )

    snapshot = FXTransactionSnapshot(
        organisation_id=organisation_id, transaction_date=transaction_date, reporting_date=reporting_date,
        supplier_id=supplier_id, customer_id=customer_id, currency_code=currency_code,
        foreign_currency_amount=foreign_currency_amount, transaction_date_spot_rate=transaction_date_spot_rate,
        reporting_date_spot_rate=reporting_date_spot_rate, fec_contract_rate=result["fec_contract_rate"],
        is_hedged=result["is_hedged"], unrealized_variance=result["unrealized_variance"],
        hedging_gain_loss=result["hedging_gain_loss"], corrects_id=corrects_id, uploaded_by_user_id=user_id,
    )
    db.add(snapshot)
    await db.flush()

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id,
        action="fx_transaction_corrected" if corrects_id else "fx_transaction_ingested",
        entity_type="fx_transaction_snapshot", entity_id=snapshot.id,
        context={"currency_code": currency_code, "is_hedged": result["is_hedged"]},
    )
    await db.commit()

    return {"snapshot_id": snapshot.id, "snapshot_public_id": str(snapshot.public_id), **result}
