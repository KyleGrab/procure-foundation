"""
Pydantic output models for structured LLM responses (LLMProvider.complete_structured). These are
the "Pydantic output parsers for brief JSON payloads" - the contract between what the model is
asked to produce and what the service layer is willing to accept. A response that doesn't
validate against these raises LLMOutputParsingError rather than being coerced/guessed into shape.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class NegotiationBriefOutput(BaseModel):
    summary: str
    priority_items: list[str] = Field(description="Ranked, highest priority first")
    questions_to_ask: list[str]
    challenge_points: list[str] = Field(description="Grounded only in the verified figures supplied")
    requested_supporting_information: list[str]
    concession_strategy: str
    batna_considerations: str
    negotiation_checklist: list[str]
    missing_data_notes: list[str] = Field(
        default_factory=list,
        description="Explicit call-outs of anything the model was asked for but not given "
        "(e.g. no supplier performance data) - per spec Section 26, gaps must be stated, not filled",
    )


class ExtractedField(BaseModel):
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class IntentClassificationOutput(BaseModel):
    """Output of the copilot's classification step (app/ai/copilot_service.py). `intent` is
    validated against app.ai.intent_router.Intent by the router itself, not trusted here - this
    schema only guarantees the model returned *a string*, never that it's a safe one to act on."""
    intent: str
    entities: dict[str, str] = Field(
        default_factory=dict,
        description="Extracted values only (e.g. a supplier name as written) - never an ID, "
        "never a query fragment. Resolving a name to an ID is a deterministic DB lookup done "
        "after classification, not something the model does.",
    )
    reasoning: str = Field(description="Brief explanation of why this intent was chosen")


class ContractExtractionOutput(BaseModel):
    """One entry per contract term the model located in the source document. Fields it could not
    find are simply absent from `fields` - never populated with a guessed value (spec Section 31's
    'every extracted field must have... confidence' implies a field with no confidence wasn't
    extracted, not that it was extracted at confidence 0)."""
    fields: dict[str, ExtractedField]
    unresolved_notes: list[str] = Field(
        default_factory=list,
        description="Terms the prompt asked for but the model could not locate in the document",
    )
