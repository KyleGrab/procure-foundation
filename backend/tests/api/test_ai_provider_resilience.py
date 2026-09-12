"""
AI-PROVIDER-RESILIENCE-R1: focused proofs for the Anthropic optional-dependency failure repair
in app/ai/llm_provider.py.

Root cause (AI-AUTH-DEP-R1): the ACCESS_AI permission check already correctly runs before any
provider resolution or SDK import - confirmed structurally (require_permission is a FastAPI
Depends, resolved before the route body) and empirically (an authorised owner's request reaches
AnthropicProvider.complete()'s `import anthropic` line). The actual gap was purely a resilience/
packaging one: `anthropic` is an optional, lazily-imported dependency by design, but was never
declared as an installable extra, and a genuinely-missing SDK produced a raw, unhandled
ModuleNotFoundError instead of a stable HTTP response - crashing the request rather than failing
closed with a structured error.

These tests make zero Anthropic/network/model calls and install no package - `anthropic` is
genuinely absent from this test environment throughout, which is exactly what proves the 503
path is real, not mocked.
"""
from unittest.mock import Mock

import pytest

from app.core.security import create_access_token


@pytest.mark.integration
async def test_viewer_without_access_ai_denied_before_provider_construction(client, monkeypatch):
    """A caller without ACCESS_AI gets a plain 403, and get_llm_provider() is never even called -
    the tripwire proves provider resolution (and therefore client construction, any SDK import,
    and any network activity) is unreachable for a denied caller, not merely absent by chance.
    Patched where it's looked up (app.api.v1.ai_copilot's own imported name), matching how the
    route actually calls it."""
    import app.api.v1.ai_copilot as ai_copilot_module

    tripwire = Mock(side_effect=AssertionError(
        "get_llm_provider() must never be called for a caller lacking ACCESS_AI"
    ))
    monkeypatch.setattr(ai_copilot_module, "get_llm_provider", tripwire)

    # A well-formed but otherwise arbitrary token - require_permission decodes and checks the
    # role's permission set directly, no database lookup involved, so no real user/org is needed
    # to prove the denial itself.
    token = create_access_token(user_id=999999, active_org_id=999999, role="viewer")

    resp = await client.post(
        "/ai/query", json={"question": "What is our total spend by supplier?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    tripwire.assert_not_called()


@pytest.mark.integration
async def test_authorised_caller_with_anthropic_unavailable_receives_structured_503(client):
    """Anthropic is genuinely not installed in this test environment - no mock, no monkeypatch on
    the provider itself. An authorised (owner) caller's request must reach the real
    AnthropicProvider.complete() and fail closed with a stable 503, not a raw exception."""
    register_resp = await client.post(
        "/auth/register",
        json={"first_name": "O", "last_name": "User", "email": "ai-resilience-owner@example.com",
              "password": "correct-horse-battery-staple", "organisation_name": "AI Resilience Org"},
    )
    assert register_resp.status_code == 201
    token = register_resp.json()["access_token"]

    resp = await client.post(
        "/ai/query", json={"question": "What is our total spend by supplier?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "ai_provider_unavailable"
    assert body["error"]["message"] == "AI provider is currently unavailable"


@pytest.mark.integration
async def test_503_response_leaks_no_import_path_or_traceback(client):
    """The response body (and raw response text) must never expose the Python import path,
    module name, credentials, provider configuration, or a stack trace - only the generic,
    stable message and code."""
    register_resp = await client.post(
        "/auth/register",
        json={"first_name": "O", "last_name": "User", "email": "ai-resilience-leak-check@example.com",
              "password": "correct-horse-battery-staple", "organisation_name": "AI Resilience Leak Check Org"},
    )
    assert register_resp.status_code == 201
    token = register_resp.json()["access_token"]

    resp = await client.post(
        "/ai/query", json={"question": "What is our total spend by supplier?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503
    body_text = resp.text
    for leaked in (
        "ModuleNotFoundError", "Traceback", "import anthropic", "llm_provider.py",
        "api_key", "AsyncAnthropic", "site-packages",
    ):
        assert leaked not in body_text, f"response body leaked internal detail: {leaked!r}"
