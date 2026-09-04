"""Editor agent: drafts precise text-replacement patches for contradictions.

Drafting is LLM work (typed EditDraft); application is 100% deterministic in
workflows/actions.py — the exact find_text must match or the patch is rejected.
"""

from __future__ import annotations

from docgrity.agents.base import AgentRun, build_agent, input_hash, run_agent
from docgrity.agents.duplicate import _render_pair
from docgrity.agents.schemas import EditDraft
from docgrity.core.enums import LLMCapability
from docgrity.core.models import KnowledgeItem


async def draft_edit(
    item_a: KnowledgeItem,
    item_b: KnowledgeItem,
    finding_summary: str,
    conflicting_claims: list[str],
) -> tuple[EditDraft, AgentRun]:
    """Draft patch(es) that would resolve a contradiction between two pages."""
    claims = "\n".join(f"- {claim}" for claim in conflicting_claims) or "- (none recorded)"
    payload = (
        f"# Finding summary\n{finding_summary}\n\n"
        f"# Conflicting claims\n{claims}\n\n"
        f"{_render_pair(item_a, item_b)}"
    )
    agent, model_id, prompt_version = build_agent("editor", LLMCapability.REASONING_HIGH, EditDraft)
    output = await run_agent(agent, payload)
    run = AgentRun(model=model_id, prompt_version=prompt_version, input_hash=input_hash(payload))
    return output, run
