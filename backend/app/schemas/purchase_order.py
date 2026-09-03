from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.constants import Currency


class PurchaseOrderLineInput(BaseModel):
    supplier_sku: str | None = None
    description: str | None = None
    quantity_ordered: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    vat_rate_pct: Decimal | None = None


class PurchaseOrderCreate(BaseModel):
    supplier_public_id: uuid.UUID
    location_public_id: uuid.UUID | None = None
    po_number: str = Field(min_length=1, max_length=64)
    order_date: date
    expected_delivery_date: date | None = None
    currency: Currency = Currency.ZAR
    lines: list[PurchaseOrderLineInput] = Field(min_length=1)


class PurchaseOrderLineRead(BaseModel):
    public_id: uuid.UUID
    supplier_sku: str | None
    description: str | None
    quantity_ordered: Decimal
    unit_price: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class PurchaseOrderRead(BaseModel):
    public_id: uuid.UUID
    supplier_public_id: uuid.UUID
    po_number: str
    order_date: date
    expected_delivery_date: date | None
    status: str
    currency: Currency
    lines: list[PurchaseOrderLineRead]

    model_config = {"from_attributes": True}
