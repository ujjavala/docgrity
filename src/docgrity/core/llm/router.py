"""Capability → provider/model routing for LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from docgrity.core.config import get_settings
from docgrity.core.enums import LLMCapability


@dataclass(frozen=True)
class ModelRoute:
    provider: str  # any provider name understood by core.llm.providers
    model: str

    @classmethod
    def parse(cls, spec: str) -> ModelRoute:
        """Parse a 'provider:model' spec (bare model defaults to openai)."""
        provider, sep, model = spec.partition(":")
        if not sep:
            return cls("openai", spec)
        return cls(provider, model)


class LLMRouter:
    """Resolves capabilities to providers and executes embedding calls.

    Chat/completion execution lives with the agents (PydanticAI); the router's
    job is deciding *which* provider+model serves a capability, plus providing
    the shared embedding entrypoint used by ingestion.
    """

    def __init__(self, routes: dict[LLMCapability, ModelRoute]) -> None:
        self._routes = routes
        self._embedding_client = None

    def resolve(self, capability: LLMCapability) -> ModelRoute:
        try:
            return self._routes[capability]
        except KeyError as exc:
            raise ValueError(f"No route configured for capability {capability!r}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via any OpenAI-compatible provider (openai/gemini/github/...)."""
        route = self.resolve(LLMCapability.EMBEDDING)
        if self._embedding_client is None:
            from docgrity.core.llm.providers import build_embedding_client

            self._embedding_client = build_embedding_client(route.provider)
        kwargs: dict = {"model": route.model, "input": texts}
        dims = get_settings().llm_embedding_dimensions
        if dims:
            kwargs["dimensions"] = dims
        response = await self._embedding_client.embeddings.create(**kwargs)
        return [item.embedding for item in response.data]


@lru_cache
def get_router() -> LLMRouter:
    settings = get_settings()
    return LLMRouter(
        routes={
            LLMCapability.REASONING_HIGH: ModelRoute.parse(settings.llm_reasoning_high_model),
            LLMCapability.REASONING_FAST: ModelRoute.parse(settings.llm_reasoning_fast_model),
            LLMCapability.CLASSIFICATION: ModelRoute.parse(settings.llm_classification_model),
            LLMCapability.EMBEDDING: ModelRoute.parse(settings.llm_embedding_model),
        }
    )
