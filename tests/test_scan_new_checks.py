"""Contradiction and open-question scan tests: agents mocked, DB real."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from docgrity.agents.base import AgentRun
from docgrity.agents.duplicate import CandidatePair
from docgrity.agents.schemas import (
    ContradictionAssessment,
    EvidenceItem,
    OpenQuestion,
    OpenQuestionAssessment,
    OwnershipAssessment,
)
from docgrity.core.db import get_session_factory
from docgrity.core.enums import (
    FindingSeverity,
    FindingType,
    KnowledgeItemType,
    ScanStatus,
    SourceType,
)
from docgrity.core.models import (
    Finding,
    FindingEvidence,
    KnowledgeItem,
    Scan,
    Source,
    Tenant,
)
from docgrity.workflows.scan import scan_contradictions, scan_open_questions

pytestmark = pytest.mark.integration

RUN = AgentRun(model="test:model", prompt_version="v1", input_hash="y" * 64)

NO_OWNERS = OwnershipAssessment(candidates=[], reasoning="none")


async def _seed_tenant_with_pages() -> tuple[uuid.UUID, KnowledgeItem, KnowledgeItem]:
    factory = get_session_factory()
    async with factory() as session:
        tenant = Tenant(name=f"scan-{uuid.uuid4().hex[:8]}")
        session.add(tenant)
        await session.flush()
        source = Source(tenant_id=tenant.id, type=SourceType.CONFLUENCE, name="test")
        session.add(source)
        await session.flush()
        items = []
        for ext, title in (("c1", "SLA policy"), ("c2", "Support handbook")):
            item = KnowledgeItem(
                tenant_id=tenant.id,
                source_type=SourceType.CONFLUENCE,
                source_id=source.id,
                external_id=ext,
                type=KnowledgeItemType.CONFLUENCE_PAGE,
                title=title,
                content=f"content of {title}",
                content_hash=uuid.uuid4().hex,
                meta={},
                source_updated_at=datetime.now(UTC),
            )
            session.add(item)
            items.append(item)
        await session.commit()
        return tenant.id, items[0], items[1]


def _contradiction(confidence: float = 0.9, is_contradiction: bool = True):
    return ContradictionAssessment(
        is_contradiction=is_contradiction,
        confidence=confidence,
        severity=FindingSeverity.HIGH,
        summary="SLA response times disagree.",
        conflicting_claims=["A says 4h SLA; B says 24h SLA."],
        evidence=[
            EvidenceItem(
                knowledge_item_external_id="c1", excerpt="respond within 4h", source_label="SLA"
            ),
            EvidenceItem(
                knowledge_item_external_id="c2",
                excerpt="respond within 24h",
                source_label="Handbook",
            ),
        ],
    )


async def _run_contradiction_scan(tenant_id, pair, assessment):
    factory = get_session_factory()
    async with factory() as session:
        items = (
            await session.scalars(
                select(KnowledgeItem).where(KnowledgeItem.id.in_([pair.item_a_id, pair.item_b_id]))
            )
        ).all()
        by_id = {i.id: i for i in items}
    with (
        patch(
            "docgrity.workflows.scan.find_related_pairs",
            new=AsyncMock(return_value=[pair]),
        ),
        patch(
            "docgrity.workflows.scan.assess_contradiction",
            new=AsyncMock(
                return_value=(assessment, RUN, by_id[pair.item_a_id], by_id[pair.item_b_id])
            ),
        ),
        patch(
            "docgrity.workflows.scan.assess_ownership",
            new=AsyncMock(return_value=(NO_OWNERS, RUN)),
        ),
    ):
        return await scan_contradictions({}, str(tenant_id), post_comments=False)


async def test_contradiction_scan_creates_finding_with_evidence():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.3)

    result = await _run_contradiction_scan(tenant_id, pair, _contradiction(0.9))
    assert result["error"] is None
    assert result["findings_created"] == 1

    factory = get_session_factory()
    async with factory() as session:
        finding = await session.scalar(select(Finding).where(Finding.tenant_id == tenant_id))
        assert finding.type == FindingType.CONTRADICTION
        assert finding.detail["conflicting_claims"] == ["A says 4h SLA; B says 24h SLA."]
        assert len(finding.detail["pages"]) == 2
        evidence = (
            await session.scalars(
                select(FindingEvidence).where(FindingEvidence.finding_id == finding.id)
            )
        ).all()
        assert len(evidence) == 2
        scan = await session.scalar(select(Scan).where(Scan.tenant_id == tenant_id))
        assert scan.status == ScanStatus.COMPLETED
        assert scan.stats == {"pairs_assessed": 1, "findings_created": 1}


async def test_contradiction_scan_gates_on_confidence():
    tenant_id, item_a, item_b = await _seed_tenant_with_pages()
    pair = CandidatePair(item_a_id=item_a.id, item_b_id=item_b.id, distance=0.3)

    result = await _run_contradiction_scan(tenant_id, pair, _contradiction(0.5))
    assert result["findings_created"] == 0

    factory = get_session_factory()
    async with factory() as session:
        finding = await session.scalar(select(Finding).where(Finding.tenant_id == tenant_id))
        assert finding is None


async def _run_open_question_scan(tenant_id, assessment):
    with (
        patch(
            "docgrity.workflows.scan.assess_open_questions",
            new=AsyncMock(return_value=(assessment, RUN)),
        ),
        patch(
            "docgrity.workflows.scan.assess_ownership",
            new=AsyncMock(return_value=(NO_OWNERS, RUN)),
        ),
    ):
        return await scan_open_questions({}, str(tenant_id), post_comments=False)


async def test_open_question_scan_creates_finding_per_page():
    tenant_id, _, _ = await _seed_tenant_with_pages()
    assessment = OpenQuestionAssessment(
        questions=[
            OpenQuestion(
                question="Who owns rollbacks?", excerpt="TBD: rollback owner", confidence=0.8
            ),
            OpenQuestion(question="Low-confidence one", excerpt="maybe?", confidence=0.2),
        ],
        severity=FindingSeverity.LOW,
        summary="One unresolved question.",
    )

    result = await _run_open_question_scan(tenant_id, assessment)
    assert result["error"] is None
    assert result["pages_assessed"] == 2
    assert result["findings_created"] == 2  # both seeded pages get the mocked assessment

    factory = get_session_factory()
    async with factory() as session:
        findings = (
            await session.scalars(select(Finding).where(Finding.tenant_id == tenant_id))
        ).all()
        assert all(f.type == FindingType.OPEN_QUESTION for f in findings)
        # low-confidence question filtered out by the gate
        assert all(f.detail["questions"] == ["Who owns rollbacks?"] for f in findings)
        evidence = (
            await session.scalars(
                select(FindingEvidence).where(FindingEvidence.tenant_id == tenant_id)
            )
        ).all()
        assert len(evidence) == 2  # one gated question per page


async def test_open_question_scan_skips_when_no_confident_questions():
    tenant_id, _, _ = await _seed_tenant_with_pages()
    assessment = OpenQuestionAssessment(
        questions=[OpenQuestion(question="?", excerpt="", confidence=0.9)],
        severity=FindingSeverity.LOW,
        summary="",
    )
    result = await _run_open_question_scan(tenant_id, assessment)
    assert result["findings_created"] == 0
