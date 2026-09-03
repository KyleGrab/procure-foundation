from __future__ import annotations

from pydantic import BaseModel


class CopilotQueryRequest(BaseModel):
    question: str


class CopilotQueryResponse(BaseModel):
    intent: str
    structured_result: dict
    summary: str
    missing_data_notes: list[str] = []
