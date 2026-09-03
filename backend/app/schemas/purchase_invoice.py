from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.constants import Currency

from app.analytics.purchase_ledger_calculations import ReferencePriceSource


class PurchaseInvoiceLineInput(BaseModel):
    supplier_sku: str | None = None
    description: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_pct: Decimal | None = None
    tax_pct: Decimal | None = None
    # PPV inputs - both optional; if reference_price is given, source must be too (spec Section
    # 24 / analytics-methodology.md §5: a variance with no stated baseline isn't auditable).
    reference_price: Decimal | None = None
    reference_price_source: ReferencePriceSource | None = None


class PurchaseInvoiceIngest(BaseModel):
    """Append-only ingestion (ADR-006) - there is no update endpoint for a posted invoice, only
    this creation path and a separate correction path that references corrects_id."""
    supplier_public_id: uuid.UUID
    purchase_order_public_id: uuid.UUID | None = None
    invoice_number: str = Field(min_length=1, max_length=64)
    invoice_date: date
    currency: Currency = Currency.ZAR
    lines: list[PurchaseInvoiceLineInput] = Field(min_length=1)


class PurchaseInvoiceLineRead(BaseModel):
    public_id: uuid.UUID
    supplier_sku: str | None
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    discount_pct: Decimal | None
    tax_pct: Decimal | None
    net_amount: Decimal
    price_variance: Decimal | None = None  # populated only when a reference price was supplied

    model_config = {"from_attributes": True}


class PurchaseInvoiceRead(BaseModel):
    public_id: uuid.UUID
    supplier_public_id: uuid.UUID
    invoice_number: str
    invoice_date: date
    currency: Currency
    corrects_public_id: uuid.UUID | None
    lines: list[PurchaseInvoiceLineRead]

    model_config = {"from_attributes": True}
