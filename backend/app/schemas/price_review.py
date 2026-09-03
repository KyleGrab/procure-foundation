from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.constants import Currency


class PriceReviewCreate(BaseModel):
    supplier_public_id: uuid.UUID
    effective_date: datetime | None = None
    currency: Currency = Currency.ZAR
    price_basis: str = Field(default="tax_exclusive", pattern="^(tax_inclusive|tax_exclusive)$")


class PriceReviewRead(BaseModel):
    public_id: uuid.UUID
    supplier_public_id: uuid.UUID
    status: str
    effective_date: datetime | None
    currency: Currency
    price_basis: str
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ColumnMappingConfirm(BaseModel):
    """spec Section 3: the system suggests a mapping, the user confirms (or overrides) it before
    any row is processed - this schema is that confirmation, never auto-applied server-side."""
    file_public_id: uuid.UUID
    column_mapping: dict[str, str | None]
    save_as_template_name: str | None = None


class PriceReviewLineRead(BaseModel):
    public_id: uuid.UUID
    old_supplier_sku: str | None
    old_description: str | None
    old_pack_raw: str | None
    old_price: Decimal | None
    new_supplier_sku: str | None
    new_description: str | None
    new_pack_raw: str | None
    new_price: Decimal | None
    match_status: str
    match_method: str | None
    match_confidence: Decimal | None
    movement_type: str | None
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    pack_changed: bool
    comparison_basis: str | None
    risk_classification: str | None
    annual_quantity: Decimal | None
    quantity_source: str | None
    quantity_confidence: str | None
    annual_impact: Decimal | None
    buyer_decision: str | None
    target_price: Decimal | None
    potential_cost_avoidance: Decimal | None
    final_negotiated_price: Decimal | None
    actual_cost_avoidance: Decimal | None

    model_config = {"from_attributes": True}


class MatchDecision(BaseModel):
    """spec Section 10's match-review actions."""
    action: str = Field(pattern="^(confirm|choose_different|mark_new|mark_discontinued|ignore)$")
    chosen_new_line_public_id: uuid.UUID | None = None  # required when action == choose_different


class BuyerDecisionUpdate(BaseModel):
    """spec Section 22."""
    decision: str = Field(pattern="^(accept|challenge|negotiate|investigate|ignore)$")
    notes: str | None = None


class NegotiationTargetUpdate(BaseModel):
    """spec Section 23."""
    target_price: Decimal


class NegotiationOutcomeUpdate(BaseModel):
    """spec Section 24."""
    final_negotiated_price: Decimal


class ManualQuantityUpdate(BaseModel):
    """spec Section 13/32 + ADR-008: manual annual-quantity entry for this phase."""
    annual_quantity: Decimal = Field(gt=0)
    selling_price: Decimal | None = None  # enables margin-impact calc (spec Section 17) if provided


class SupplierSummaryRead(BaseModel):
    total_previous_skus: int
    total_new_skus: int
    matched_skus: int
    unmatched_skus: int
    new_skus: int
    discontinued_skus: int
    increasing_skus: int
    decreasing_skus: int
    unchanged_skus: int
    pack_changes: int
    weighted_average_price_increase_pct: Decimal | None
    annual_cost_impact: Decimal
    products_requiring_manual_review: int
