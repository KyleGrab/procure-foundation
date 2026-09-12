"""
PROMPT-TEMPLATE-LOADER-R1: proves the two updated consumers (negotiation_brief_service.generate_brief,
contract_extraction_service.extract_terms) render via the shared loader - no LLM/Anthropic/OpenAI/
external call anywhere here. A capturing fake LLMProvider records the exact rendered prompt string
instead of a real API call.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.contract_extraction_service import extract_terms
from app.ai.llm_provider import LLMProvider
from app.ai.schemas import ContractExtractionOutput, ExtractedField, NegotiationBriefOutput
from app.services.negotiation_brief_service import NegotiationBriefContext, generate_brief


class _CapturingProvider(LLMProvider):
    """Never makes a real call - complete() is a tripwire (never legitimately reached, since
    complete_structured is overridden directly below); complete_structured captures the exact
    rendered prompt and returns a canned, schema-valid output."""

    def __init__(self, canned_output):
        self.captured_prompt: str | None = None
        self._canned_output = canned_output

    async def complete(self, *, system: str, prompt: str, max_tokens: int = 1500) -> str:
        raise AssertionError("complete() should never be called - complete_structured is overridden directly")

    async def complete_structured(self, *, system: str, prompt: str, output_model, max_tokens: int = 1500):
        self.captured_prompt = prompt
        return self._canned_output


_CONTEXT = NegotiationBriefContext(
    supplier_name="Gourmet Cape Distributors", annual_spend=Decimal("355848477.03"),
    weighted_increase_pct=Decimal("0.08"), total_annual_impact=Decimal("28467878.16"),
    top_sku_impacts=[("Frozen Chicken Portions 2kg", Decimal("1200000"))],
    negotiation_targets=[("Frozen Chicken Portions 2kg", Decimal("45.00"))],
    supplier_performance_note="on-time delivery 94% over the last 12 months",
)

_NEGOTIATION_OUTPUT = NegotiationBriefOutput(
    summary="Test summary", priority_items=["item"], questions_to_ask=["question"],
    challenge_points=["point"], requested_supporting_information=["info"],
    concession_strategy="strategy", batna_considerations="batna", negotiation_checklist=["check"],
)

_EXTRACTION_OUTPUT = ContractExtractionOutput(
    fields={"title": ExtractedField(value="Supply Agreement", confidence=0.95)},
    unresolved_notes=["escalation_rate_pct not stated"],
)


class TestNegotiationBriefRendering:
    async def test_all_seven_runtime_substitutions_render_successfully(self):
        provider = _CapturingProvider(_NEGOTIATION_OUTPUT)
        result = await generate_brief(provider, _CONTEXT)
        assert result is _NEGOTIATION_OUTPUT
        prompt = provider.captured_prompt
        assert "Gourmet Cape Distributors" in prompt
        assert "355848477.03" in prompt
        assert "0.08" in prompt
        assert "28467878.16" in prompt
        assert "Frozen Chicken Portions 2kg: R1200000" in prompt
        assert "Frozen Chicken Portions 2kg: R45.00" in prompt
        assert "on-time delivery 94% over the last 12 months" in prompt

    async def test_literal_placeholder_in_developer_header_is_never_evaluated(self):
        """This is the exact defect (KeyError: 'placeholder') the loader closes - reaching this
        point at all (no KeyError raised by .format()) is itself the primary proof."""
        provider = _CapturingProvider(_NEGOTIATION_OUTPUT)
        await generate_brief(provider, _CONTEXT)  # would raise KeyError: 'placeholder' if unfixed
        assert "{placeholder}" not in provider.captured_prompt

    async def test_rendered_prompt_excludes_the_developer_header_entirely(self):
        provider = _CapturingProvider(_NEGOTIATION_OUTPUT)
        await generate_brief(provider, _CONTEXT)
        prompt = provider.captured_prompt
        assert "negotiation_brief_service.generate_brief" not in prompt  # dev-only header text
        assert "spec Section" not in prompt  # header-only internal cross-reference
        assert "You are helping a South African food-distribution procurement team" in prompt


class TestContractClauseExtractionRendering:
    async def test_uses_shared_loader_and_renders_valid_substitution_excluding_header(self):
        provider = _CapturingProvider(_EXTRACTION_OUTPUT)
        document_text = "This Supply Agreement is entered into between Buyer and Supplier..."
        result = await extract_terms(provider, document_text)
        assert result is _EXTRACTION_OUTPUT
        prompt = provider.captured_prompt
        assert document_text in prompt
        assert "contract_extraction_service.extract_terms" not in prompt  # dev-only header text
        assert "You are extracting structured contract terms" in prompt
