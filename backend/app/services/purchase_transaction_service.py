"""
Phase 4b: persists uploaded purchase transactions (append-only, ADR-006). Recalculation of
affected rebate periods delegates entirely to app.services.rebate_aggregation_service (ADR-014's
shared waterfall - invoice data takes precedence over transaction data over manual entry) rather
than aggregating transactions directly here. An earlier version of this module did its own
aggregation before Phase 4c introduced purchase_invoices as a competing data source for the same
periods - exactly the kind of duplicated-logic drift ADR-014 was written to prevent, fixed by
this refactor rather than left as a second, slowly-diverging copy.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationFailedError
from app.db.models import PurchaseTransaction
from app.services import audit_service, rebate_aggregation_service


async def ingest_transactions(
    db: AsyncSession, *, organisation_id: int, user_id: int, supplier_id: int,
    mapped_rows: list[dict], source_file_storage_key: str,
) -> list[PurchaseTransaction]:
    """
    mapped_rows are already through app.ingestion.purchase_transaction_mapping +
    app.ingestion.purchase_transaction_validation (Phase 4b) - this function only parses into
    typed values and persists as append-only rows. A row with an unparseable date/amount is
    rejected individually (raises), matching Phase 2's "one bad row doesn't take down the batch"
    principle - the caller (route) is expected to validate before calling this, same division of
    responsibility as price_review's ingestion path.
    """
    transactions: list[PurchaseTransaction] = []
    for row in mapped_rows:
        try:
            transaction_date = date.fromisoformat(str(row["transaction_date"]))
            amount = Decimal(str(row["amount"]))
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise ValidationFailedError(f"Could not parse transaction row: {row!r}") from exc
        quantity = Decimal(str(row["quantity"])) if row.get("quantity") else None

        transactions.append(PurchaseTransaction(
            organisation_id=organisation_id, supplier_id=supplier_id,
            supplier_sku=row.get("supplier_sku"), description=row.get("description"),
            transaction_date=transaction_date, amount=amount, quantity=quantity,
            reference=row.get("reference"), source_file_storage_key=source_file_storage_key,
            uploaded_by_user_id=user_id,
        ))
    db.add_all(transactions)
    await db.flush()

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="purchase_transactions_ingested",
        entity_type="purchase_transaction", entity_id=None,
        context={"count": len(transactions), "supplier_id": supplier_id},
    )

    if transactions:
        dates = [t.transaction_date for t in transactions]
        await rebate_aggregation_service.recalculate_affected_periods(
            db, supplier_id=supplier_id, min_date=min(dates), max_date=max(dates),
        )

    await db.commit()
    return transactions
