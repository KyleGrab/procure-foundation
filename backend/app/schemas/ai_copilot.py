from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CopilotQueryRequest(BaseModel):
    question: str


class CopilotQueryResponse(BaseModel):
    intent: str
    structured_result: dict[str, Any]
    summary: str
    missing_data_notes: list[str] = []
