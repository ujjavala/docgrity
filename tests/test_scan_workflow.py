"""Scan-workflow tests: agents mocked, DB real.

Covers the deterministic orchestration in workflows/scan.py — finding creation
with evidence, multi-candidate potential ownership (fake users), the
confidence gate, dedupe, and failure recording — per the architectural
principles (evidence required, ownership always potential, auditability).
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from docgrity.agents.base import AgentRun
from docgrity.agents.duplicate import CandidatePair
from docgrity.agents.schemas import (
    DuplicateAssessment,
    EvidenceItem,
    OwnerCandidate,
    OwnershipAssessment,
)
from docgrity.core.db import get_session_factory
from docgrity.core.enums import (
    DuplicateAction,
    FindingSeverity,
    FindingStatus,
    FindingType,
    KnowledgeItemType,
    ScanStatus,
    SourceType,
)
from docgrity.core.models import (
    AuditEvent,
    Finding,
    FindingEvidence,
    FindingPerson,
    KnowledgeItem,
    Scan,
    Source,
    Tenant,
    User,
)
from docgrity.workflows.scan import scan_duplicates

pytestmark = pytest.mark.integration

RUN = AgentRun(model="test:model", prompt_version="v1", input_hash="x" * 64)


async def _seed_tenant_with_pages() -> tuple[uuid.UUID, KnowledgeItem, KnowledgeItem]:
    factory = get_session_factory()
    async with factory() as session:
        tenant = Tenant(name=f"scan-{uuid.uuid4().hex[:8]}")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            type=SourceType.CONFLUENCE,
            name="test",
        )
        session.add(source)
        await session.flush()
        items = []
        for ext, title in (("p1", "Deploy guide"), ("p2", "How we ship")):
            item = KnowledgeItem(
                tenant_id=tenant.id,
                source_type=SourceType.CONFLUENCE,
                source_id=source.id,
                external_id=ext,
                type=KnowledgeItemType.CONFLUENCE_PAGE,
                title=title,
                content=f"content of {title}",
                content_hash=uuid.uuid4().hex,
                meta={
                    "owner_id": "acc-owner",
                    "author_id": "acc-author",
                    "recent_editor_ids": ["acc-editor-1", "acc-editor-2"],
                },
                source_updated_at=datetime.now(UTC),
            )
            session.add(item)
            items.append(item)
        await session.commit()
        return tenant.id, items[0], items[1]


def _assessment(confidence: float = 0.9, is_duplicate: bool = True) -> DuplicateAssessment:
    return DuplicateAssessment(
        is_duplicate=is_duplicate,
        confidence=confidence,
        severity=FindingSeverity.MEDIUM,
        summary="Both pages describe the same deploy process.",
        differences=["Page B mentions rollbacks."],
        recommended_action=DuplicateAction.MERGE,
        evidence=[
            EvidenceItem(
                knowledge_item_external_id="p1", excerpt="run deploy", source_label="Deploy guide"
            ),
            EvidenceItem(
                knowledge_item_external_id="p2", excerpt="run deploy", source_label="How we ship"
            ),
        ],
    )


def _ownership(*account_ids: str) -> OwnershipAssessment:
    return OwnershipAssessment(
        candidates=[
            OwnerCandidate(account_id=acc, confidence=0.8 - i * 0.1, evidence=[f"signal for {acc}"])
            for i, acc in enumerate(account_ids)
        ],
        reasoning="ranked by ownership signals",
    )


async def _run_scan(tenant_id, pair, assessment_result, ownership_result):
    item_ids = [pair.item_a_id, pair.item_b_id]
    factory = get_session_factory()
    async with factory() as session:
        items = (
            await session.scalars(select(KnowledgeItem).where(KnowledgeItem.id.in_(item_ids)))
        ).all()
        by_id = {i.id: i for i in items}
    with (
        patch(
            "docgrity.workflows.scan.find_candidate_pairs",
            new=AsyncMock(return_value=[pair]),
        ),
        patch(
            "docgrity.workflows.scan.assess_pair",
            new=AsyncMock(
                return_value=(
                    assessment_result,
                    RUN,
                    by_id[pair.item_a_id],
                    by_id[pair.item_b_id],
                )
            ),
        ),
        patch(
            "docgrity.workflows.scan.assess_ownership",
            new=AsyncMock(return_value=(ownership_result, RUN)),
        ),
    ):
        return await scan_duplicates({}, str(tenant_id), post_comments=False)


async def test_scan_creates_finding_with_evidence_and_potential_owners():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.1)

    result = await _run_scan(
        tenant_id, pair, _assessment(0.9), _ownership("acc-owner", "acc-editor-1", "acc-editor-2")
    )
    assert result["error"] is None
    assert result["findings_created"] == 1

    factory = get_session_factory()
    async with factory() as session:
        finding = await session.scalar(select(Finding).where(Finding.tenant_id == tenant_id))
        assert finding.type == FindingType.DUPLICATE
        assert finding.model == "test:model"
        assert finding.prompt_version == "v1"
        assert finding.input_hash == "x" * 64

        evidence = (
            await session.scalars(
                select(FindingEvidence).where(FindingEvidence.finding_id == finding.id)
            )
        ).all()
        assert len(evidence) == 2  # excerpts from BOTH pages

        persons = (
            await session.scalars(
                select(FindingPerson).where(FindingPerson.finding_id == finding.id)
            )
        ).all()
        # Two items × top-2 candidates each; all inferred ownership is potential.
        assert len(persons) == 4
        assert all(p.authoritative is False for p in persons)
        owner_users = {(await session.get(User, p.user_id)).external_id for p in persons}
        assert owner_users == {"acc-owner", "acc-editor-1"}

        audit = (
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.event_type == "FINDING_CREATED",
                )
            )
        ).all()
        assert len(audit) == 1

        scan = await session.scalar(select(Scan).where(Scan.tenant_id == tenant_id))
        assert scan.status == ScanStatus.COMPLETED
        assert scan.stats == {"pairs_assessed": 1, "findings_created": 1}


async def test_confidence_below_threshold_creates_no_finding():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.1)

    result = await _run_scan(tenant_id, pair, _assessment(0.5), _ownership("acc-owner"))
    assert result["findings_created"] == 0
    assert result["pairs_assessed"] == 1


async def test_no_evidence_means_no_finding():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.1)
    assessment = _assessment(0.95)
    assessment = assessment.model_copy(update={"evidence": []})

    result = await _run_scan(tenant_id, pair, assessment, _ownership("acc-owner"))
    assert result["findings_created"] == 0


async def test_existing_open_finding_is_not_duplicated():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.1)

    first = await _run_scan(tenant_id, pair, _assessment(0.9), _ownership("acc-owner"))
    assert first["findings_created"] == 1
    second = await _run_scan(tenant_id, pair, _assessment(0.9), _ownership("acc-owner"))
    assert second["findings_created"] == 0
    assert second["pairs_assessed"] == 0  # skipped before the LLM call

    factory = get_session_factory()
    async with factory() as session:
        findings = (
            await session.scalars(select(Finding).where(Finding.tenant_id == tenant_id))
        ).all()
        assert len(findings) == 1


async def test_agent_failure_marks_scan_failed():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.1)

    with (
        patch(
            "docgrity.workflows.scan.find_candidate_pairs",
            new=AsyncMock(return_value=[pair]),
        ),
        patch(
            "docgrity.workflows.scan.assess_pair",
            new=AsyncMock(side_effect=RuntimeError("provider exploded")),
        ),
    ):
        result = await scan_duplicates({}, str(tenant_id), post_comments=False)

    assert result["error"] == "provider exploded"
    factory = get_session_factory()
    async with factory() as session:
        scan = await session.scalar(select(Scan).where(Scan.tenant_id == tenant_id))
        assert scan.status == ScanStatus.FAILED
        assert scan.error == "provider exploded"


async def test_finding_status_new_after_scan_never_auto_resolved():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.1)
    await _run_scan(tenant_id, pair, _assessment(0.9), _ownership("acc-owner"))

    factory = get_session_factory()
    async with factory() as session:
        finding = await session.scalar(select(Finding).where(Finding.tenant_id == tenant_id))
        assert finding.status == FindingStatus.NEW  # humans/verification move it, never the scan
