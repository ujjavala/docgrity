"""Capability-based LLM router.

Agents request capabilities (reasoning.high, reasoning.fast, classification,
embedding) — never concrete models. This module maps capability → provider +
model, configurable via settings/environment rather than code constants.
"""

from docgrity.core.llm.providers import build_chat_model, build_embedding_client
from docgrity.core.llm.router import LLMRouter, ModelRoute, get_router

__all__ = ["LLMRouter", "ModelRoute", "build_chat_model", "build_embedding_client", "get_router"]
