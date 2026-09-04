"""Agent factory: capability-routed, prompt-versioned PydanticAI agents.

Agents request LLM capabilities, never concrete models; the router in core/llm
maps capability → provider/model, and this module bridges that to PydanticAI.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior

from docgrity.agents.prompts import load_prompt
from docgrity.core.config import get_settings
from docgrity.core.enums import LLMCapability
from docgrity.core.llm import build_chat_model, get_router

logger = logging.getLogger("docgrity.agents")

# Transient provider errors (rate limits, overload) worth retrying.
_RETRYABLE_STATUS = {429, 500, 502, 503, 529}


async def run_agent[T: BaseModel](agent: Agent[None, T], payload: str, attempts: int = 4) -> T:
    """Run an agent with exponential backoff on transient provider errors."""
    delay = 2.0
    for attempt in range(attempts):
        try:
            result = await agent.run(payload)
            return result.output
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            retryable = status in _RETRYABLE_STATUS or isinstance(exc, UnexpectedModelBehavior)
            if not retryable or attempt == attempts - 1:
                raise
            logger.warning(
                "agent.retry",
                extra={"attempt": attempt + 1, "status_code": status, "delay_s": delay},
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


@dataclass(frozen=True)
class AgentRun:
    """Reproducibility metadata recorded on findings and agent tasks."""

    model: str
    prompt_version: str
    input_hash: str


def input_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def build_agent[T: BaseModel](
    prompt_name: str,
    capability: LLMCapability,
    output_type: type[T],
) -> tuple[Agent[None, T], str, str]:
    """Return (agent, model_id, prompt_version) for a named prompt + capability.

    When LLM_FALLBACK_MODEL is configured, the agent transparently falls back
    to that provider if the primary errors (PydanticAI FallbackModel).
    """
    route = get_router().resolve(capability)
    model_id = f"{route.provider}:{route.model}"
    prompt_text, prompt_version = load_prompt(prompt_name)
    model = build_chat_model(route.provider, route.model)
    fallback_spec = get_settings().llm_fallback_model
    if fallback_spec and fallback_spec != model_id:
        from pydantic_ai.models.fallback import FallbackModel

        provider, _, fb_model = fallback_spec.partition(":")
        model = FallbackModel(model, build_chat_model(provider, fb_model))
    agent = Agent(model, output_type=output_type, instructions=prompt_text, retries=3)
    return agent, model_id, prompt_version
