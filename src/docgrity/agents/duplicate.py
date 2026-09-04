"""Duplicate detection: pgvector candidate pairs + LLM confirmation.

Deterministic code finds candidate pairs by embedding similarity; the LLM only
judges the shortlisted pairs (typed output, evidence required).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from docgrity.agents.base import AgentRun, build_agent, input_hash, run_agent
from docgrity.agents.schemas import DuplicateAssessment
from docgrity.core.enums import LLMCapability
from docgrity.core.models import KnowledgeItem

# Cosine distance below which a pair is worth an LLM look (config-tunable later).
CANDIDATE_DISTANCE_THRESHOLD = 0.35
CONTENT_CHAR_LIMIT = 6000


@dataclass(frozen=True)
class CandidatePair:
    item_a_id: uuid.UUID
    item_b_id: uuid.UUID
    distance: float


async def find_candidate_pairs(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    threshold: float = CANDIDATE_DISTANCE_THRESHOLD,
    limit: int = 50,
    space_id: str | None = None,
) -> list[CandidatePair]:
    """Find candidate duplicate pairs by pgvector cosine distance (deterministic)."""
    space_filter = (
        "AND a.metadata->>'space_id' = :space_id AND b.metadata->>'space_id' = :space_id"
        if space_id
        else ""
    )
    params: dict = {"tenant_id": str(tenant_id), "threshold": threshold, "limit": limit}
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
              AND (a.embedding <=> b.embedding) < :threshold
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


async def assess_pair(
    session: AsyncSession,
    pair: CandidatePair,
) -> tuple[DuplicateAssessment, AgentRun, KnowledgeItem, KnowledgeItem]:
    """Ask the LLM whether a candidate pair is a true duplicate."""
    items = (
        await session.scalars(
            select(KnowledgeItem).where(KnowledgeItem.id.in_([pair.item_a_id, pair.item_b_id]))
        )
    ).all()
    by_id = {item.id: item for item in items}
    item_a, item_b = by_id[pair.item_a_id], by_id[pair.item_b_id]

    payload = _render_pair(item_a, item_b)
    agent, model_id, prompt_version = build_agent(
        "duplicate", LLMCapability.REASONING_HIGH, DuplicateAssessment
    )
    output = await run_agent(agent, payload)
    run = AgentRun(model=model_id, prompt_version=prompt_version, input_hash=input_hash(payload))
    return output, run, item_a, item_b


def _render_pair(item_a: KnowledgeItem, item_b: KnowledgeItem) -> str:
    return (
        f"## Page A (external_id={item_a.external_id})\n"
        f"Title: {item_a.title}\n"
        f"Last source update: {item_a.source_updated_at}\n\n"
        f"{item_a.content[:CONTENT_CHAR_LIMIT]}\n\n"
        f"## Page B (external_id={item_b.external_id})\n"
        f"Title: {item_b.title}\n"
        f"Last source update: {item_b.source_updated_at}\n\n"
        f"{item_b.content[:CONTENT_CHAR_LIMIT]}"
    )
