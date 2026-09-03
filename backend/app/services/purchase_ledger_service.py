"""
Phase 4c: purchase orders (mutable), invoice ingestion (append-only, ADR-006, triggers PPV per
line when a reference price is supplied), goods receipt recording (append-only, computes
ordered-vs-delivered variance). No calculation logic of its own -
app.analytics.purchase_ledger_calculations (tested, tests_pure/test_purchase_ledger_calculations.py)
does every number; invoice ingestion also triggers the same ADR-014 rebate-aggregation waterfall
purchase_transaction_service.py uses, via app.services.rebate_aggregation_service.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.purchase_ledger_calculations import (
    calculate_invoice_line_net_amount,
    calculate_purchase_price_variance,
    calculate_receipt_variance,
)
from app.core.exceptions import NotFoundError
from app.db.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    Location,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.schemas.goods_receipt import GoodsReceiptCreate
from app.schemas.purchase_invoice import PurchaseInvoiceIngest
from app.schemas.purchase_order import PurchaseOrderCreate
from app.services import audit_service, rebate_aggregation_service


async def _get_supplier_id(db: AsyncSession, supplier_public_id) -> int:
    result = await db.execute(select(Supplier.id).where(Supplier.public_id == supplier_public_id))
    supplier_id = result.scalar_one_or_none()
    if supplier_id is None:
        raise NotFoundError("Supplier not found")
    return supplier_id


async def create_purchase_order(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: PurchaseOrderCreate,
) -> PurchaseOrder:
    supplier_id = await _get_supplier_id(db, payload.supplier_public_id)
    location_id = None
    if payload.location_public_id:
        loc_result = await db.execute(
            select(Location.id).where(Location.public_id == payload.location_public_id)
        )
        location_id = loc_result.scalar_one_or_none()

    order = PurchaseOrder(
        organisation_id=organisation_id, supplier_id=supplier_id, location_id=location_id,
        po_number=payload.po_number, order_date=payload.order_date,
        expected_delivery_date=payload.expected_delivery_date, status="draft",
        currency=payload.currency, created_by_user_id=user_id,
    )
    db.add(order)
    await db.flush()

    for line_input in payload.lines:
        line_total = line_input.quantity_ordered * line_input.unit_price
        db.add(PurchaseOrderLine(
            organisation_id=organisation_id, purchase_order_id=order.id,
            supplier_sku=line_input.supplier_sku, description=line_input.description,
            quantity_ordered=line_input.quantity_ordered, unit_price=line_input.unit_price,
            vat_rate_pct=line_input.vat_rate_pct, line_total=line_total,
        ))

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="purchase_order_created",
        entity_type="purchase_order", entity_id=str(order.id),
    )
    await db.commit()
    await db.refresh(order)
    return order


async def ingest_purchase_invoice(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: PurchaseInvoiceIngest,
) -> tuple[PurchaseInvoice, list[dict]]:
    """
    Append-only (ADR-006) - there is no update path for a posted invoice. Returns the invoice
    plus a list of per-line PPV results (dicts, not persisted as their own column - PPV is
    computed from stored fields on demand, not stored as if it were itself a fact, since the
    "reference price" a variance is measured against can reasonably change definition over time
    e.g. a renegotiated contract price - the net_amount that was actually invoiced never does).
    """
    supplier_id = await _get_supplier_id(db, payload.supplier_public_id)
    purchase_order_id = None
    if payload.purchase_order_public_id:
        po_result = await db.execute(
            select(PurchaseOrder.id).where(PurchaseOrder.public_id == payload.purchase_order_public_id)
        )
        purchase_order_id = po_result.scalar_one_or_none()

    invoice = PurchaseInvoice(
        organisation_id=organisation_id, supplier_id=supplier_id, purchase_order_id=purchase_order_id,
        invoice_number=payload.invoice_number, invoice_date=payload.invoice_date,
        currency=payload.currency, uploaded_by_user_id=user_id,
    )
    db.add(invoice)
    await db.flush()

    ppv_results: list[dict] = []
    for line_input in payload.lines:
        net_amount = calculate_invoice_line_net_amount(
            line_input.quantity, line_input.unit_price, line_input.discount_pct
        )
        line = PurchaseInvoiceLine(
            organisation_id=organisation_id, purchase_invoice_id=invoice.id,
            supplier_sku=line_input.supplier_sku, description=line_input.description,
            quantity=line_input.quantity, unit_price=line_input.unit_price,
            discount_pct=line_input.discount_pct, tax_pct=line_input.tax_pct, net_amount=net_amount,
        )
        db.add(line)

        if line_input.reference_price is not None:
            variance = calculate_purchase_price_variance(
                line_input.reference_price, line_input.unit_price, line_input.quantity
            )
            ppv_results.append({
                "supplier_sku": line_input.supplier_sku,
                "reference_price_source": line_input.reference_price_source,
                "expected_cost": variance.expected_cost, "actual_cost": variance.actual_cost,
                "variance": variance.variance, "variance_pct": variance.variance_pct,
            })

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="purchase_invoice_ingested",
        entity_type="purchase_invoice", entity_id=str(invoice.id),
        context={"line_count": len(payload.lines), "ppv_lines": len(ppv_results)},
    )

    dates = [payload.invoice_date]
    await rebate_aggregation_service.recalculate_affected_periods(
        db, supplier_id=supplier_id, min_date=min(dates), max_date=max(dates),
    )

    await db.commit()
    await db.refresh(invoice)
    return invoice, ppv_results


async def record_goods_receipt(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: GoodsReceiptCreate,
) -> tuple[GoodsReceipt, list[dict]]:
    """Append-only. Returns the receipt plus per-line variance results (computed, not stored as
    a separate persisted figure - same reasoning as PPV above)."""
    supplier_id = await _get_supplier_id(db, payload.supplier_public_id)
    purchase_order_id = None
    if payload.purchase_order_public_id:
        po_result = await db.execute(
            select(PurchaseOrder.id).where(PurchaseOrder.public_id == payload.purchase_order_public_id)
        )
        purchase_order_id = po_result.scalar_one_or_none()

    receipt = GoodsReceipt(
        organisation_id=organisation_id, supplier_id=supplier_id, purchase_order_id=purchase_order_id,
        receipt_number=payload.receipt_number, receipt_date=payload.receipt_date,
        created_by_user_id=user_id,
    )
    db.add(receipt)
    await db.flush()

    variance_results: list[dict] = []
    for line_input in payload.lines:
        db.add(GoodsReceiptLine(
            organisation_id=organisation_id, goods_receipt_id=receipt.id,
            supplier_sku=line_input.supplier_sku, description=line_input.description,
            quantity_ordered=line_input.quantity_ordered, quantity_received=line_input.quantity_received,
        ))
        if line_input.quantity_ordered is not None:
            variance = calculate_receipt_variance(line_input.quantity_ordered, line_input.quantity_received)
            variance_results.append({
                "supplier_sku": line_input.supplier_sku,
                "variance_quantity": variance.variance_quantity,
                "variance_pct": variance.variance_pct, "status": variance.status.value,
            })

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="goods_receipt_recorded",
        entity_type="goods_receipt", entity_id=str(receipt.id),
        context={"line_count": len(payload.lines)},
    )
    await db.commit()
    await db.refresh(receipt)
    return receipt, variance_results
