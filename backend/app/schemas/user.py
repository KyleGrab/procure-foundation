from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class UserInvite(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(min_length=1, max_length=128)
    role: str


class MembershipRead(BaseModel):
    public_id: uuid.UUID
    user_public_id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    role: str
    status: str

    model_config = {"from_attributes": True}


class MembershipUpdate(BaseModel):
    role: str | None = None
    status: str | None = None
