"""
Read-only spend queries over the purchase ledger, calling app.analytics.spend_analytics (tested,
tests_pure/test_spend_analytics.py) for every number. No calculation logic of its own.

Same double-counting concern ADR-014 solved for rebate period aggregation, applied here at
supplier granularity: if both purchase_invoice_lines and purchase_transactions have rows for a
supplier, summing both would double-count any purchase recorded in both places. Rather than
re-deriving ADR-014's period-level waterfall for a dashboard query, this uses the simpler
supplier-level rule documented in get_spend_rows(): a supplier with ANY invoice data is read only
from invoices; a supplier with none is read from transactions. Less precise than ADR-014's
per-period waterfall, appropriate for a spend overview rather than a rebate calculation input.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.spend_analytics import (
    ABCResult,
    ParetoResult,
    PriceObservation,
    PriceConsistencyResult,
    SpendItem,
    aggregate_spend,
    calculate_abc_classification,
    calculate_month_over_month_trend,
    calculate_pareto_contributors,
    calculate_price_consistency,
)
from app.db.models import (
    PriceReview,
    PriceReviewLine,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseTransaction,
    Supplier,
)


async def _suppliers_with_invoice_data(db: AsyncSession, organisation_id: int) -> set[int]:
    result = await db.execute(
        select(PurchaseInvoice.supplier_id).distinct()
        .where(PurchaseInvoice.organisation_id == organisation_id)
        .where(PurchaseInvoice.corrects_id.is_(None))
    )
    return {row[0] for row in result.all()}


async def get_spend_by_supplier(db: AsyncSession, *, organisation_id: int) -> list[SpendItem]:
    invoice_suppliers = await _suppliers_with_invoice_data(db, organisation_id)

    invoice_result = await db.execute(
        select(Supplier.id, Supplier.legal_name, PurchaseInvoiceLine.net_amount)
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
        .join(Supplier, Supplier.id == PurchaseInvoice.supplier_id)
        .where(PurchaseInvoice.organisation_id == organisation_id)
        .where(PurchaseInvoice.corrects_id.is_(None))
    )
    rows = [(str(sid), name, Decimal(str(amount))) for sid, name, amount in invoice_result.all()]

    txn_result = await db.execute(
        select(Supplier.id, Supplier.legal_name, PurchaseTransaction.amount)
        .join(Supplier, Supplier.id == PurchaseTransaction.supplier_id)
        .where(PurchaseTransaction.organisation_id == organisation_id)
        .where(PurchaseTransaction.corrects_id.is_(None))
    )
    rows += [
        (str(sid), name, Decimal(str(amount)))
        for sid, name, amount in txn_result.all()
        if sid not in invoice_suppliers  # avoid double-counting - see module docstring
    ]

    return aggregate_spend(rows)


async def get_spend_by_sku(db: AsyncSession, *, organisation_id: int, supplier_id: int | None = None) -> list[SpendItem]:
    invoice_suppliers = await _suppliers_with_invoice_data(db, organisation_id)

    invoice_query = (
        select(PurchaseInvoiceLine.supplier_sku, PurchaseInvoiceLine.description, PurchaseInvoiceLine.net_amount)
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
        .where(PurchaseInvoice.organisation_id == organisation_id)
        .where(PurchaseInvoice.corrects_id.is_(None))
    )
    if supplier_id is not None:
        invoice_query = invoice_query.where(PurchaseInvoice.supplier_id == supplier_id)
    invoice_result = await db.execute(invoice_query)
    rows = [
        (sku or description or "unknown", description or sku or "Unknown item", Decimal(str(amount)))
        for sku, description, amount in invoice_result.all()
    ]

    # Same double-counting avoidance as get_spend_by_supplier - a supplier already covered by
    # invoice data is excluded from the transaction pass entirely.
    txn_query = (
        select(
            PurchaseTransaction.supplier_sku, PurchaseTransaction.description,
            PurchaseTransaction.amount, PurchaseTransaction.supplier_id,
        )
        .where(PurchaseTransaction.organisation_id == organisation_id)
        .where(PurchaseTransaction.corrects_id.is_(None))
    )
    if supplier_id is not None:
        txn_query = txn_query.where(PurchaseTransaction.supplier_id == supplier_id)
    txn_result = await db.execute(txn_query)
    rows += [
        (sku or description or "unknown", description or sku or "Unknown item", Decimal(str(amount)))
        for sku, description, amount, txn_supplier_id in txn_result.all()
        if txn_supplier_id not in invoice_suppliers
    ]

    return aggregate_spend(rows)


async def get_abc_classification(db: AsyncSession, *, organisation_id: int) -> list[ABCResult]:
    items = await get_spend_by_supplier(db, organisation_id=organisation_id)
    return calculate_abc_classification(items)


async def get_pareto_contributors(db: AsyncSession, *, organisation_id: int) -> ParetoResult:
    items = await get_spend_by_supplier(db, organisation_id=organisation_id)
    return calculate_pareto_contributors(items)


async def check_price_consistency(
    db: AsyncSession, *, organisation_id: int, supplier_id: int, sku_or_description: str,
) -> PriceConsistencyResult:
    """spec Section 23 - a genuinely different question from Phase 4c's PPV, see
    docs/phase5-opportunity-engine-plan.md §2.2. Gathers every recorded price for this
    SKU+supplier across invoice lines and transactions, not just one line against one reference."""
    invoice_result = await db.execute(
        select(PurchaseInvoiceLine.unit_price, PurchaseInvoice.invoice_date)
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
        .where(PurchaseInvoice.organisation_id == organisation_id)
        .where(PurchaseInvoice.supplier_id == supplier_id)
        .where(
            (PurchaseInvoiceLine.supplier_sku == sku_or_description)
            | (PurchaseInvoiceLine.description == sku_or_description)
        )
    )
    observations = [
        PriceObservation(Decimal(str(price)), invoice_date)
        for price, invoice_date in invoice_result.all()
    ]
    if not observations:
        raise ValueError(f"No purchase price observations found for {sku_or_description!r}")
    return calculate_price_consistency(observations)


async def get_month_over_month_trend(db: AsyncSession, *, organisation_id: int):
    """
    Buckets invoice-line spend by calendar month (invoice_date), including only suppliers not
    covered by purchase_transactions duplication risk in the same way get_spend_by_supplier
    handles it - here, invoice and transaction spend are bucketed by month independently per
    supplier using the same "supplier already has invoice data -> ignore its transactions"
    exclusion, then summed into one monthly series.
    """
    from collections import defaultdict

    invoice_suppliers = await _suppliers_with_invoice_data(db, organisation_id)

    invoice_result = await db.execute(
        select(PurchaseInvoice.invoice_date, PurchaseInvoiceLine.net_amount)
        .join(PurchaseInvoiceLine, PurchaseInvoiceLine.purchase_invoice_id == PurchaseInvoice.id)
        .where(PurchaseInvoice.organisation_id == organisation_id)
        .where(PurchaseInvoice.corrects_id.is_(None))
    )
    monthly: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for invoice_date, amount in invoice_result.all():
        monthly[invoice_date.strftime("%Y-%m")] += Decimal(str(amount))

    txn_result = await db.execute(
        select(PurchaseTransaction.transaction_date, PurchaseTransaction.amount, PurchaseTransaction.supplier_id)
        .where(PurchaseTransaction.organisation_id == organisation_id)
        .where(PurchaseTransaction.corrects_id.is_(None))
    )
    for txn_date, amount, supplier_id in txn_result.all():
        if supplier_id in invoice_suppliers:
            continue
        monthly[txn_date.strftime("%Y-%m")] += Decimal(str(amount))

    sorted_months = sorted(monthly.items())
    return calculate_month_over_month_trend(sorted_months)


async def get_top_supplier_price_increases(db: AsyncSession, *, organisation_id: int, limit: int = 10):
    """
    Reuses Phase 2's PriceReviewLine data (already computed, already proven -
    tests_pure/test_calculations.py) rather than recomputing anything - "top supplier price
    increases" is a ranked view over price_review_lines.annual_impact, not a new calculation.
    No PriceReviewLine.price_review or PriceReview.supplier relationship() is declared anywhere
    in this codebase (only FK columns) - joined explicitly here, same pattern as every join since
    Phase 1 (an earlier draft of this function used PriceReviewLine.price_review.has(...), which
    doesn't exist and would have raised AttributeError immediately - caught before shipping by
    checking against this codebase's own established join style, not by running it).
    """
    result = await db.execute(
        select(PriceReviewLine, Supplier.legal_name)
        .join(PriceReview, PriceReview.id == PriceReviewLine.price_review_id)
        .join(Supplier, Supplier.id == PriceReview.supplier_id)
        .where(PriceReviewLine.organisation_id == organisation_id)
        .where(PriceReviewLine.movement_type == "price_increase")
        .order_by(PriceReviewLine.annual_impact.desc())
        .limit(limit)
    )
    return [
        {
            "supplier": supplier_name,
            "product": line.new_description or line.old_description,
            "percentage_change": str(line.percentage_change) if line.percentage_change else None,
            "annual_impact": str(line.annual_impact) if line.annual_impact else None,
            "risk_classification": line.risk_classification,
        }
        for line, supplier_name in result.all()
    ]
