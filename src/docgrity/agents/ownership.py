"""Ownership inference: Confluence signals → potential owner candidates.

Signal gathering is deterministic (via the Confluence client's owner/history
data already ingested or fetched through MCP); the LLM ranks candidates and
must return evidence per candidate. All output is *potential* ownership.
"""

from __future__ import annotations

import json

from docgrity.agents.base import AgentRun, build_agent, input_hash, run_agent
from docgrity.agents.schemas import OwnershipAssessment
from docgrity.core.enums import LLMCapability


async def assess_ownership(
    page_title: str,
    owner_signals: dict,
) -> tuple[OwnershipAssessment, AgentRun]:
    """Rank potential owners for a page from its ownership signals.

    owner_signals is the payload from the Confluence MCP get_owner tool plus
    optional edit-count aggregation, e.g.:
    {"owner_id": ..., "author_id": ..., "recent_editor_ids": [...],
     "edit_counts": {"acc-1": 5}, "last_edited_at": {...}}
    """
    payload = f"Page: {page_title}\nSignals:\n{json.dumps(owner_signals, indent=2, default=str)}"
    agent, model_id, prompt_version = build_agent(
        "ownership", LLMCapability.REASONING_FAST, OwnershipAssessment
    )
    output = await run_agent(agent, payload)
    run = AgentRun(model=model_id, prompt_version=prompt_version, input_hash=input_hash(payload))
    return output, run
