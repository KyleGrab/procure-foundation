from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.constants import Currency


class RebateBandInput(BaseModel):
    threshold_spend: Decimal
    rate_pct: Decimal = Field(
        ge=Decimal(0), le=Decimal(1),
        description="Fraction (0.025 = 2.5%). A rebate rate can't be negative and can't "
        "plausibly exceed 100% of spend.",
    )


class RebateAgreementCreate(BaseModel):
    supplier_public_id: uuid.UUID
    contract_public_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    rebate_type: str = Field(
        pattern="^(fixed_percentage|tiered|volume|growth|fixed_amount|retrospective)$"
    )
    period_type: str = Field(default="quarterly", pattern="^(quarterly|annual)$")
    flat_rate_pct: Decimal | None = Field(default=None, ge=Decimal(0), le=Decimal(1))
    bands: list[RebateBandInput] | None = None
    fixed_amount: Decimal | None = None
    currency: Currency = Currency.ZAR

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> RebateAgreementCreate:
        # Mirrors the DB CHECK constraints in migration 0005 - validated here too so the error
        # surfaces before a round-trip, not just after (same pattern as ContractCreate).
        if self.rebate_type in ("fixed_percentage", "volume", "growth") and self.flat_rate_pct is None:
            raise ValueError(f"{self.rebate_type} requires flat_rate_pct")
        if self.rebate_type in ("tiered", "retrospective") and not self.bands:
            raise ValueError(f"{self.rebate_type} requires at least one band")
        if self.rebate_type == "fixed_amount" and self.fixed_amount is None:
            raise ValueError("fixed_amount requires fixed_amount")
        return self


class RebateAgreementRead(BaseModel):
    public_id: uuid.UUID
    supplier_public_id: uuid.UUID
    title: str
    rebate_type: str
    period_type: str
    flat_rate_pct: Decimal | None
    bands: list[RebateBandInput] | None
    fixed_amount: Decimal | None
    currency: Currency
    status: str

    model_config = {"from_attributes": True}


class RebatePeriodActualCreate(BaseModel):
    """Phase 4a: manual entry (ADR-012). Phase 4b adds a separate ingestion path that populates
    the same fields with entry_source='transaction_aggregation' instead."""
    period_start: date
    period_end: date
    actual_spend: Decimal = Field(ge=0)
    actual_volume: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_period(self) -> RebatePeriodActualCreate:
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class RebatePeriodActualRead(BaseModel):
    public_id: uuid.UUID
    period_start: date
    period_end: date
    actual_spend: Decimal | None
    actual_volume: Decimal | None
    entry_source: str
    expected_amount: Decimal | None
    expected_amount_status: str
    expected_amount_source_basis: str | None
    earned_amount: Decimal | None
    received_amount: Decimal | None
    received_reference: str | None
    status: str
    status_calculated_at: datetime | None
    next_tier_threshold: Decimal | None  # derived, always alongside the stored fields
    amount_to_next_tier: Decimal | None  # derived

    model_config = {"from_attributes": True}


class RebateReceiptRecord(BaseModel):
    """spec Section 29: received_amount is only ever set from an actual credit-note/payment
    reference - this schema makes that reference mandatory, not optional, so a received amount
    can never be entered without something to trace it back to."""
    received_amount: Decimal = Field(ge=0)
    received_reference: str = Field(min_length=1, max_length=128)


class RebateLeakageResult(BaseModel):
    """P-03: the leakage figure is diagnostic (null + reason_code), never a fabricated number,
    when expected_amount_status can't support a real leakage calculation."""
    leakage: Decimal | None
    status: Literal["ok", "diagnostic"]
    reason_code: str | None


class RebateReceiptRecordResponse(BaseModel):
    period_actual: RebatePeriodActualRead
    leakage_result: RebateLeakageResult
