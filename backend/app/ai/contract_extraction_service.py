"""
AI-assisted contract term extraction (spec Section 31). Writes ONLY to `contract_extractions`
(staging) - never to `contracts`' verified fields directly. Promotion is an explicit, itemized,
audited human action - see app.services.contract_service.promote_extraction_fields. Never
executed in this sandbox (no network, no LLM_API_KEY) - same honesty pattern as
negotiation_brief_service.py.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm_provider import LLMProvider
from app.ai.schemas import ContractExtractionOutput
from app.db.models import ContractExtraction

_PROMPT_TEMPLATE_PATH = "app/ai/prompts/contract_clause_extraction.md"
_PROMPT_VERSION = "v1"


async def extract_terms(provider: LLMProvider, document_text: str) -> ContractExtractionOutput:
    with open(_PROMPT_TEMPLATE_PATH) as f:
        template = f.read()
    prompt = template.format(document_text=document_text)
    return await provider.complete_structured(
        system="Contract term extraction assistant - never a source of legal advice.",
        prompt=prompt,
        output_model=ContractExtractionOutput,
    )


async def stage_extraction(
    db: AsyncSession, *, organisation_id: int, contract_id: int | None,
    source_file_storage_key: str, extraction_model: str, result: ContractExtractionOutput,
) -> ContractExtraction:
    """
    Persists the raw model output to staging, untouched - the shape written here is exactly what
    promote_extraction_fields() later reads field-by-field. contract_id is nullable: an
    extraction can be run before a draft Contract row exists yet (e.g. "upload a document and
    let the system propose a new contract"), in which case contract creation happens as part of
    promotion, not before extraction.
    """
    extraction = ContractExtraction(
        organisation_id=organisation_id,
        contract_id=contract_id,
        source_file_storage_key=source_file_storage_key,
        extracted_fields={
            name: {"value": field.value, "confidence": field.confidence}
            for name, field in result.fields.items()
        },
        extraction_model=extraction_model,
        prompt_version=_PROMPT_VERSION,
        verification_status="pending",
    )
    db.add(extraction)
    await db.flush()
    return extraction
