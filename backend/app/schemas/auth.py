from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    organisation_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class SwitchOrgRequest(BaseModel):
    organisation_public_id: uuid.UUID


class MembershipSummary(BaseModel):
    organisation_public_id: uuid.UUID
    organisation_name: str
    role: str
    status: str


class CurrentUser(BaseModel):
    public_id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr
    memberships: list[MembershipSummary]
