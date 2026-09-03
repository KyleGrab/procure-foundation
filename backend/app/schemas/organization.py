from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.core.constants import Currency


class OrganisationRead(BaseModel):
    public_id: uuid.UUID
    name: str
    legal_name: str | None
    default_currency: Currency
    country: str
    timezone: str
    industry: str | None
    fiscal_year_start: date | None
    active: bool

    model_config = {"from_attributes": True}


class OrganisationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = None
    industry: str | None = None
    fiscal_year_start: date | None = None
