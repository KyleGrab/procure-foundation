from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel


class SpendItemRead(BaseModel):
    key: str
    label: str
    amount: Decimal


class ABCResultRead(BaseModel):
    item: SpendItemRead
    cumulative_pct: Decimal
    classification: str


class ParetoResultRead(BaseModel):
    contributors: list[SpendItemRead]
    contributor_count: int
    total_item_count: int
    cumulative_pct_covered: Decimal


class PriceConsistencyRead(BaseModel):
    supplier_public_id: uuid.UUID
    sku_or_description: str
    min_price: Decimal
    max_price: Decimal
    spread: Decimal
    spread_pct: Decimal | None
    is_significant: bool
    observation_count: int
