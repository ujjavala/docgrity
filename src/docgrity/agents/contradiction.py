"""Contradiction detection: pgvector candidate pairs + LLM conflict judgement.

Same shape as duplicate detection: deterministic code shortlists semantically
related pairs; the LLM only judges whether their claims conflict (typed output,
evidence required from both pages).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from docgrity.agents.base import AgentRun, build_agent, input_hash, run_agent
from docgrity.agents.duplicate import CandidatePair, _render_pair
from docgrity.agents.schemas import ContradictionAssessment
from docgrity.core.enums import LLMCapability
from docgrity.core.models import KnowledgeItem

__all__ = ["find_related_pairs", "assess_contradiction"]

# Related-but-not-near-identical band: close enough to discuss the same subject,
# far enough that it is not just a duplicate (those are handled by the duplicate
# check). Config-tunable later.
RELATED_DISTANCE_MIN = 0.05
RELATED_DISTANCE_MAX = 0.55


async def find_related_pairs(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    minimum: float = RELATED_DISTANCE_MIN,
    maximum: float = RELATED_DISTANCE_MAX,
    limit: int = 50,
    space_id: str | None = None,
) -> list[CandidatePair]:
    """Find semantically related pairs worth checking for contradictions."""
    space_filter = (
        "AND a.metadata->>'space_id' = :space_id AND b.metadata->>'space_id' = :space_id"
        if space_id
        else ""
    )
    params: dict = {
        "tenant_id": str(tenant_id),
        "minimum": minimum,
        "maximum": maximum,
        "limit": limit,
    }
    if space_id:
        params["space_id"] = str(space_id)
    rows = await session.execute(
        text(
            f"""
            SELECT a.id AS id_a, b.id AS id_b,
                   a.embedding <=> b.embedding AS distance
            FROM knowledge_item a
            JOIN knowledge_item b
              ON a.tenant_id = b.tenant_id
             AND a.id < b.id
            WHERE a.tenant_id = :tenant_id
              AND a.embedding IS NOT NULL
              AND b.embedding IS NOT NULL
              AND (a.embedding <=> b.embedding) BETWEEN :minimum AND :maximum
              {space_filter}
            ORDER BY distance
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        CandidatePair(item_a_id=row.id_a, item_b_id=row.id_b, distance=row.distance) for row in rows
    ]


async def assess_contradiction(
    session: AsyncSession,
    pair: CandidatePair,
) -> tuple[ContradictionAssessment, AgentRun, KnowledgeItem, KnowledgeItem]:
    """Ask the LLM whether a related pair makes conflicting claims."""
    items = (
        await session.scalars(
            select(KnowledgeItem).where(KnowledgeItem.id.in_([pair.item_a_id, pair.item_b_id]))
        )
    ).all()
    by_id = {item.id: item for item in items}
    item_a, item_b = by_id[pair.item_a_id], by_id[pair.item_b_id]

    payload = _render_pair(item_a, item_b)
    agent, model_id, prompt_version = build_agent(
        "contradiction", LLMCapability.REASONING_HIGH, ContradictionAssessment
    )
    output = await run_agent(agent, payload)
    run = AgentRun(model=model_id, prompt_version=prompt_version, input_hash=input_hash(payload))
    return output, run, item_a, item_b
