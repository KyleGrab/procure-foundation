from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OpportunityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    opportunity_type: str = "price_increase_challenge"
    supplier_public_id: uuid.UUID | None = None
    description: str | None = None
    annual_financial_impact: Decimal | None = None
    annual_financial_impact_effective_from: date | None = None
    savings_type: str | None = Field(
        default=None, pattern="^(hard_saving|cost_avoidance|working_capital|margin_protection|efficiency_saving)$"
    )
    baseline_value: Decimal | None = None
    baseline_methodology: str | None = Field(
        default=None,
        pattern="^(historic_average_price|prior_supplier_price|budget|contract_price|approved_quotation)$",
    )
    confidence: str | None = Field(default=None, pattern="^(low|medium|high)$")

    @model_validator(mode="after")
    def _savings_type_requires_baseline_methodology(self) -> "OpportunityCreate":
        # analytics-methodology.md §7: a savings figure with no stated baseline isn't auditable -
        # enforced here, not just left as a documentation convention.
        if self.savings_type in ("hard_saving",) and not self.baseline_methodology:
            raise ValueError(f"savings_type={self.savings_type!r} requires baseline_methodology")
        return self

    @model_validator(mode="after")
    def _annual_financial_impact_requires_effective_period(self) -> "OpportunityCreate":
        # P-03: mirrors the same rule enforced service-side and by the DB combination
        # constraint - an amount with no stated period can't be recorded as a real estimate.
        # Checked here too so the caller gets a clear 422 instead of a 409 from the service.
        if self.annual_financial_impact is not None and self.annual_financial_impact_effective_from is None:
            raise ValueError("annual_financial_impact requires annual_financial_impact_effective_from")
        return self


class OpportunityRead(BaseModel):
    public_id: uuid.UUID
    title: str
    opportunity_type: str
    supplier_public_id: uuid.UUID | None
    description: str | None
    annual_financial_impact: Decimal | None
    annual_financial_impact_status: str
    annual_financial_impact_source_basis: str | None
    annual_financial_impact_effective_from: date | None
    savings_type: str | None
    baseline_value: Decimal | None
    baseline_methodology: str | None
    confidence: str | None
    realised_savings: Decimal | None
    realised_savings_status: str
    realised_savings_source_basis: str | None
    realised_savings_effective_period_start: date | None
    realised_savings_effective_period_end: date | None
    status: str
    approved_at: datetime | None
    algorithm_version: str | None
    calculation_timestamp: datetime | None

    model_config = {"from_attributes": True}


class OpportunityRealise(BaseModel):
    realised_savings: Decimal = Field(ge=0)
    effective_period_start: date
    effective_period_end: date
    documented_baseline_reference: str = Field(min_length=1, max_length=128)
    actual_cost_source_reference: str = Field(min_length=1, max_length=128)
    variance_calculation_reference: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _period_start_not_after_end(self) -> "OpportunityRealise":
        if self.effective_period_start > self.effective_period_end:
            raise ValueError("effective_period_start must not be after effective_period_end")
        return self


class ConsolidationFlagReviewRequest(BaseModel):
    action: Literal["mark_under_review", "recommend_consolidation", "reject"]
    notes: str | None = Field(default=None, max_length=2048)
