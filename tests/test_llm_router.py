"""Unit tests for the LLM capability router (no network)."""

import pytest

from docgrity.core.enums import LLMCapability
from docgrity.core.llm.router import LLMRouter, ModelRoute


def test_parse_provider_and_model():
    route = ModelRoute.parse("gemini:gemini-3.5-flash")
    assert route.provider == "gemini"
    assert route.model == "gemini-3.5-flash"


def test_parse_bare_model_defaults_to_openai():
    route = ModelRoute.parse("gpt-4o-mini")
    assert route.provider == "openai"
    assert route.model == "gpt-4o-mini"


def test_resolve_returns_configured_route():
    router = LLMRouter(routes={LLMCapability.REASONING_HIGH: ModelRoute("anthropic", "claude-x")})
    route = router.resolve(LLMCapability.REASONING_HIGH)
    assert (route.provider, route.model) == ("anthropic", "claude-x")


def test_resolve_missing_capability_raises():
    router = LLMRouter(routes={})
    with pytest.raises(ValueError, match="No route configured"):
        router.resolve(LLMCapability.EMBEDDING)
