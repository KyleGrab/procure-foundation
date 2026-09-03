from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.core.constants import Currency


class ContractCreate(BaseModel):
    supplier_public_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    contract_number: str | None = None
    start_date: date
    expiry_date: date
    notice_period_days: int = Field(default=90, ge=0)
    auto_renew: bool = False
    renewal_term_months: int | None = Field(default=None, gt=0)
    payment_terms_days: int | None = None
    currency: Currency = Currency.ZAR
    escalation_type: str = Field(default="none", pattern="^(none|fixed_percentage|cpi_linked|tiered|negotiated)$")
    escalation_rate_pct: Decimal | None = Field(
        default=None, ge=Decimal("-1"), le=Decimal("1"),
        description="Stored as a fraction (0.05 = 5%). Bounded to [-1, 1]: a de-escalation clause "
        "can't reduce price below zero (-1 = -100%), and a single-step increase beyond 100% is "
        "almost certainly a data-entry error, not a real clause.",
    )
    rebate_terms_summary: str | None = None
    sla_terms_summary: str | None = None
    minimum_spend_commitment: Decimal | None = None

    @model_validator(mode="after")
    def _validate_dates_and_renewal(self) -> "ContractCreate":
        if self.expiry_date <= self.start_date:
            raise ValueError("expiry_date must be after start_date")
        if self.auto_renew and not self.renewal_term_months:
            raise ValueError("auto_renew requires renewal_term_months")
        if self.escalation_type == "fixed_percentage" and self.escalation_rate_pct is None:
            raise ValueError("fixed_percentage escalation requires escalation_rate_pct")
        return self


class ContractRead(BaseModel):
    public_id: uuid.UUID
    supplier_public_id: uuid.UUID
    title: str
    contract_number: str | None
    start_date: date
    expiry_date: date
    notice_period_days: int
    notice_deadline: date  # derived, always returned alongside the stored fields it comes from
    auto_renew: bool
    renewal_term_months: int | None
    next_renewal_date: date | None  # derived
    currency: Currency
    escalation_type: str
    escalation_rate_pct: Decimal | None
    status: str
    status_calculated_at: datetime | None

    model_config = {"from_attributes": True}


class EscalatedPriceRequest(BaseModel):
    """ADR-009: external_index_value_pct is required for cpi_linked contracts and rejected
    (via the service layer, which knows the contract's escalation_type) for anything else -
    the API never lets a client silently supply an index value that gets ignored."""
    base_price: Decimal
    periods_elapsed: int = Field(default=1, ge=1)
    external_index_value_pct: Decimal | None = None


class ContractExtractionRead(BaseModel):
    public_id_placeholder: str | None = None  # ContractExtraction has no public_id (internal staging only)
    extracted_fields: dict
    extraction_model: str | None
    verification_status: str
    verified_at: datetime | None


class ContractExtractionVerify(BaseModel):
    """Promotes specific fields from a staged extraction into the contract's verified columns -
    an explicit, itemized action (spec Section 31), never a blanket 'accept everything' click."""
    field_names_to_promote: list[str] = Field(min_length=1)
