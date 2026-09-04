"""Provider registry: build chat models and embedding clients from routes.

Adding a provider is configuration + one registry entry — agents and the router
never reference concrete providers. Any OpenAI-compatible endpoint (GitHub
Models, Ollama, OpenRouter, vLLM, ...) is supported via base_url; other
providers with native PydanticAI support (google, groq, mistral, cohere,
bedrock) fall through to PydanticAI's model-string inference, which reads the
provider's standard environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docgrity.core.config import Settings, get_settings

if TYPE_CHECKING:
    from openai import AsyncOpenAI


@dataclass(frozen=True)
class OpenAICompatible:
    base_url: str | None
    api_key: str
    key_setting: str = ""  # settings field to name in error messages


def _openai(s: Settings) -> OpenAICompatible:
    return OpenAICompatible(None, s.openai_api_key, "openai_api_key")


def _gemini(s: Settings) -> OpenAICompatible:
    return OpenAICompatible(s.gemini_base_url, s.gemini_api_key, "gemini_api_key")


def _github(s: Settings) -> OpenAICompatible:
    return OpenAICompatible(s.github_models_base_url, s.github_token, "github_token")


def _ollama(s: Settings) -> OpenAICompatible:
    return OpenAICompatible(s.ollama_base_url, "ollama")


def _custom(s: Settings) -> OpenAICompatible:
    if not s.llm_custom_base_url:
        raise ValueError("llm_custom_base_url must be set to use the 'custom' provider")
    # Keyless local endpoints (e.g. vLLM) are fine — use a placeholder.
    return OpenAICompatible(s.llm_custom_base_url, s.llm_custom_api_key or "unused")


# provider name → OpenAI-compatible endpoint config
OPENAI_COMPATIBLE_PROVIDERS = {
    "openai": _openai,
    "gemini": _gemini,
    "github": _github,
    "ollama": _ollama,
    "custom": _custom,
}


def _resolve(provider: str) -> OpenAICompatible:
    cfg = OPENAI_COMPATIBLE_PROVIDERS[provider](get_settings())
    if not cfg.api_key:
        raise ValueError(
            f"Provider {provider!r} requires the {cfg.key_setting!r} setting "
            "(set it in .env / environment)"
        )
    return cfg


def build_chat_model(provider: str, model: str) -> Any:
    """Return a PydanticAI model (or model string) for provider:model.

    API keys come from Settings, never hardcoded. Unknown providers are passed
    through as PydanticAI model strings so any provider PydanticAI supports
    (google-gla, groq, mistral, cohere, bedrock, ...) works via its standard
    environment variables.
    """
    settings = get_settings()
    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        if not settings.anthropic_api_key:
            raise ValueError("Provider 'anthropic' requires the 'anthropic_api_key' setting")
        return AnthropicModel(model, provider=AnthropicProvider(api_key=settings.anthropic_api_key))
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        cfg = _resolve(provider)
        kwargs: dict[str, Any] = {"api_key": cfg.api_key}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        return OpenAIChatModel(model, provider=OpenAIProvider(**kwargs))
    # Fall through to PydanticAI's provider inference (keys from env vars).
    return f"{provider}:{model}"


def build_embedding_client(provider: str) -> AsyncOpenAI:
    """Return an AsyncOpenAI client for any OpenAI-compatible embedding provider."""
    if provider not in OPENAI_COMPATIBLE_PROVIDERS:
        raise ValueError(
            f"Embedding provider {provider!r} is not OpenAI-compatible; "
            f"supported: {sorted(OPENAI_COMPATIBLE_PROVIDERS)}"
        )
    from openai import AsyncOpenAI

    cfg = _resolve(provider)
    kwargs: dict[str, Any] = {"api_key": cfg.api_key}
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    return AsyncOpenAI(**kwargs)
