"""Verification agent: is a previously reported finding now resolved?"""

from __future__ import annotations

import json

from docgrity.agents.base import AgentRun, build_agent, input_hash, run_agent
from docgrity.agents.schemas import VerificationResult
from docgrity.core.enums import LLMCapability

CONTENT_CHAR_LIMIT = 6000


async def verify_finding(
    finding_summary: str,
    original_evidence: list[dict],
    current_pages: list[dict],
) -> tuple[VerificationResult, AgentRun]:
    """Check a finding against the current state of the affected pages.

    current_pages: [{"external_id", "title", "content", "exists": bool}]
    Missing/deleted pages should be passed with exists=False and empty content.
    """
    trimmed = [
        {**page, "content": (page.get("content") or "")[:CONTENT_CHAR_LIMIT]}
        for page in current_pages
    ]
    payload = json.dumps(
        {
            "finding_summary": finding_summary,
            "original_evidence": original_evidence,
            "current_pages": trimmed,
        },
        indent=2,
        default=str,
    )
    agent, model_id, prompt_version = build_agent(
        "verification", LLMCapability.REASONING_HIGH, VerificationResult
    )
    output = await run_agent(agent, payload)
    run = AgentRun(model=model_id, prompt_version=prompt_version, input_hash=input_hash(payload))
    return output, run
