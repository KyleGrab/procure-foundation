"""
LLM provider interface. Anthropic and OpenAI implementations are both written (spec's own
request for provider abstraction, docs/architecture.md §38). Neither has ever been executed in
this sandbox - no network, no API keys configured here. Written as real implementations, not
stubs, because the shape of the call is what matters for review: every prompt this codebase sends
receives only pre-computed, verified figures (see negotiation_brief_service.py and
contract_extraction_service.py) - the model is never asked to compute or recall a financial number.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.exceptions import ProcureIQError

T = TypeVar("T", bound=BaseModel)


class LLMOutputParsingError(ProcureIQError):
    """The model's response didn't match the expected structured schema. Callers must treat this
    as 'the AI step failed', never fall back to inventing the missing fields themselves - a
    parsing failure is a signal to retry or escalate to a human, not a gap to paper over."""
    code = "llm_output_parsing_failed"
    status_code = 502


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, *, system: str, prompt: str, max_tokens: int = 1500) -> str: ...

    async def complete_structured(
        self, *, system: str, prompt: str, output_model: type[T], max_tokens: int = 1500
    ) -> T:
        """
        Asks for JSON matching output_model's schema and parses it with Pydantic - the "output
        parser" the brief requested. Raises LLMOutputParsingError rather than returning a
        partially-filled or guessed model on a malformed response; a caller silently accepting
        an invalid parse is exactly the kind of AI-fabrication risk docs/architecture.md §1 exists
        to prevent, just one layer further down.
        """
        schema_instructions = (
            f"\n\nRespond with ONLY valid JSON matching this schema (no prose, no markdown "
            f"fences): {output_model.model_json_schema()}"
        )
        raw = await self.complete(system=system, prompt=prompt + schema_instructions, max_tokens=max_tokens)
        try:
            payload = json.loads(_strip_markdown_fences(raw))
            return output_model.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMOutputParsingError(
                f"Model response did not match {output_model.__name__} schema: {exc}"
            ) from exc


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return stripped


class AnthropicProvider(LLMProvider):
    async def complete(self, *, system: str, prompt: str, max_tokens: int = 1500) -> str:
        import anthropic  # local import: optional dependency until this path actually runs

        settings = get_settings()
        client = anthropic.AsyncAnthropic(api_key=settings.llm_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


class OpenAIProvider(LLMProvider):
    """Written to satisfy the multi-provider abstraction the spec asks for
    (docs/architecture.md §38: "allow future providers"). Never executed here - see module
    docstring."""

    async def complete(self, *, system: str, prompt: str, max_tokens: int = 1500) -> str:
        import openai  # local import: optional dependency until this path actually runs

        settings = get_settings()
        client = openai.AsyncOpenAI(api_key=settings.llm_api_key)
        response = await client.chat.completions.create(
            model="gpt-4.1",
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""


_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    provider_cls = _PROVIDERS.get(settings.llm_provider)
    if provider_cls is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r} - configured options: "
            f"{sorted(_PROVIDERS)}"
        )
    return provider_cls()

