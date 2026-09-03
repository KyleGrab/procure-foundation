from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.core.constants import Currency


class SupplierCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    trading_name: str | None = None
    supplier_code: str | None = None
    currency: Currency = Currency.ZAR
    category: str | None = None
    email: str | None = None
    phone: str | None = None


class SupplierRead(BaseModel):
    public_id: uuid.UUID
    legal_name: str
    trading_name: str | None
    supplier_code: str | None
    currency: Currency
    category: str | None
    active: bool

    model_config = {"from_attributes": True}
