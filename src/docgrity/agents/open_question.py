"""Open-question detection: single-page LLM scan for unresolved items.

Deterministic code selects pages; the LLM only reports questions it can back
with a verbatim excerpt (typed output, evidence required).
"""

from __future__ import annotations

from docgrity.agents.base import AgentRun, build_agent, input_hash, run_agent
from docgrity.agents.schemas import OpenQuestionAssessment
from docgrity.core.enums import LLMCapability
from docgrity.core.models import KnowledgeItem

CONTENT_CHAR_LIMIT = 8000


async def assess_open_questions(
    item: KnowledgeItem,
) -> tuple[OpenQuestionAssessment, AgentRun]:
    """Ask the LLM whether a page contains genuinely unresolved questions."""
    payload = (
        f"## Page (external_id={item.external_id})\n"
        f"Title: {item.title}\n"
        f"Last source update: {item.source_updated_at}\n\n"
        f"{item.content[:CONTENT_CHAR_LIMIT]}"
    )
    agent, model_id, prompt_version = build_agent(
        "open_question", LLMCapability.REASONING_FAST, OpenQuestionAssessment
    )
    output = await run_agent(agent, payload)
    run = AgentRun(model=model_id, prompt_version=prompt_version, input_hash=input_hash(payload))
    return output, run
