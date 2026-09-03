from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class GoodsReceiptLineInput(BaseModel):
    purchase_order_line_public_id: uuid.UUID | None = None
    supplier_sku: str | None = None
    description: str | None = None
    quantity_ordered: Decimal | None = None
    quantity_received: Decimal = Field(ge=0)


class GoodsReceiptCreate(BaseModel):
    supplier_public_id: uuid.UUID
    purchase_order_public_id: uuid.UUID | None = None
    location_public_id: uuid.UUID | None = None
    receipt_number: str | None = None
    receipt_date: date
    lines: list[GoodsReceiptLineInput] = Field(min_length=1)


class GoodsReceiptLineRead(BaseModel):
    public_id: uuid.UUID
    supplier_sku: str | None
    description: str | None
    quantity_ordered: Decimal | None
    quantity_received: Decimal
    variance_quantity: Decimal | None  # derived, populated only when quantity_ordered is known
    variance_status: str | None  # 'complete' | 'short' | 'over'

    model_config = {"from_attributes": True}


class GoodsReceiptRead(BaseModel):
    public_id: uuid.UUID
    supplier_public_id: uuid.UUID
    receipt_number: str | None
    receipt_date: date
    lines: list[GoodsReceiptLineRead]

    model_config = {"from_attributes": True}
