"""
ADR-014's waterfall, as the one place it's actually implemented. Both the purchase_transactions
ingestion path (Phase 4b, app.services.purchase_transaction_service) and the purchase_invoices
ingestion path (Phase 4c, app.services.purchase_ledger_service) call
recalculate_affected_periods() here instead of each computing their own precedence - the
refactor that makes ADR-014's "one function, one source of truth" claim true rather than aspirational.

Precedence per period: invoice_aggregation > transaction_aggregation > manual. Once a period has
been upgraded to a more authoritative source, a later upload from a less authoritative source
must never downgrade it back - see _should_use_invoice_data's early-exit logic.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.rebate_calculations import aggregate_transactions_for_period, EntrySource
from app.db.models import PurchaseInvoice, PurchaseInvoiceLine, PurchaseTransaction, RebateAgreement, RebatePeriodActual
from app.services.rebate_service import recalculate_expected


async def recalculate_affected_periods(
    db: AsyncSession, *, supplier_id: int, min_date: date, max_date: date,
) -> list[RebatePeriodActual]:
    """
    Finds every open rebate period for this supplier overlapping [min_date, max_date] and
    re-aggregates each from the best available source. Called after either a purchase_transaction
    batch or a purchase_invoice is ingested - the caller doesn't need to know which source it just
    added, this function figures out per-period which source is authoritative.
    """
    agreements_result = await db.execute(
        select(RebateAgreement).where(RebateAgreement.supplier_id == supplier_id)
    )
    agreements = list(agreements_result.scalars().all())
    if not agreements:
        return []
    agreement_ids = [a.id for a in agreements]
    agreements_by_id = {a.id: a for a in agreements}

    periods_result = await db.execute(
        select(RebatePeriodActual)
        .where(RebatePeriodActual.rebate_agreement_id.in_(agreement_ids))
        .where(RebatePeriodActual.earned_amount.is_(None))  # closed periods are never re-touched
        .where(RebatePeriodActual.period_start <= max_date)
        .where(RebatePeriodActual.period_end >= min_date)
    )
    periods = list(periods_result.scalars().all())
    if not periods:
        return []

    updated: list[RebatePeriodActual] = []
    for period in periods:
        # Once invoice_aggregation, always invoice_aggregation for this period (ADR-014) - never
        # re-check transactions for a period that already has real invoice data.
        if period.entry_source == EntrySource.INVOICE_AGGREGATION.value:
            source_tuples = await _invoice_tuples(db, supplier_id, period.period_start, period.period_end)
            entry_source = EntrySource.INVOICE_AGGREGATION.value
        else:
            invoice_tuples = await _invoice_tuples(db, supplier_id, period.period_start, period.period_end)
            if invoice_tuples:
                source_tuples, entry_source = invoice_tuples, EntrySource.INVOICE_AGGREGATION.value
            else:
                source_tuples = await _transaction_tuples(db, supplier_id, period.period_start, period.period_end)
                entry_source = EntrySource.TRANSACTION_AGGREGATION.value if source_tuples else period.entry_source

        if entry_source in (EntrySource.INVOICE_AGGREGATION.value, EntrySource.TRANSACTION_AGGREGATION.value):
            aggregate = aggregate_transactions_for_period(source_tuples, period.period_start, period.period_end)
            period.actual_spend = aggregate.total_spend
            period.actual_volume = aggregate.total_volume
            period.entry_source = entry_source
            await recalculate_expected(
                db, agreement=agreements_by_id[period.rebate_agreement_id], period_actual=period,
                actor_user_id=None,  # automated path - no human actor
                change_reference=f"rebate_aggregation_recalc:{period.id}:{entry_source}",
                change_reason_code="recalculation",
            )
            updated.append(period)

    return updated


async def _invoice_tuples(
    db: AsyncSession, supplier_id: int, period_start: date, period_end: date,
) -> list[tuple[Decimal, Decimal, date]]:
    """
    No ORM relationship() is declared between PurchaseInvoiceLine and PurchaseInvoice anywhere in
    this codebase (only FK columns) - every join this session uses an explicit
    .join(Target, Target.id == Source.other_id) form instead (see api/v1/contracts.py's
    list_contracts for the same pattern). An earlier draft of this function referenced
    PurchaseInvoiceLine.purchase_invoice, which doesn't exist and would have raised
    AttributeError the first time this ran - caught before shipping by checking against how
    every other join in this codebase is actually written, not by executing it (no DB here).
    """
    result = await db.execute(
        select(PurchaseInvoiceLine.net_amount, PurchaseInvoiceLine.quantity, PurchaseInvoice.invoice_date)
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
        .where(PurchaseInvoice.supplier_id == supplier_id)
        .where(PurchaseInvoice.corrects_id.is_(None))  # superseded invoices excluded from totals
    )
    return [
        (Decimal(str(net_amount)), Decimal(str(qty)) if qty is not None else Decimal("0"), invoice_date)
        for net_amount, qty, invoice_date in result.all()
    ]


async def _transaction_tuples(
    db: AsyncSession, supplier_id: int, period_start: date, period_end: date,
) -> list[tuple[Decimal, Decimal, date]]:
    result = await db.execute(
        select(PurchaseTransaction.amount, PurchaseTransaction.quantity, PurchaseTransaction.transaction_date)
        .where(PurchaseTransaction.supplier_id == supplier_id)
        .where(PurchaseTransaction.corrects_id.is_(None))
    )
    return [
        (Decimal(str(amount)), Decimal(str(qty)) if qty is not None else Decimal("0"), txn_date)
        for amount, qty, txn_date in result.all()
    ]
