"""Scan orchestration (deterministic pipeline; LLM only inside agents).

Checks: duplicates (pgvector pairs → duplicate agent), contradictions (related
pairs → contradiction agent), open questions (per-page agent). Each check:
confidence gate → finding + evidence + potential owners → (policy-gated)
Confluence comment. Every step records audit events; thresholds come from
settings.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docgrity.agents.action import comment_to_storage_html, draft_comment
from docgrity.agents.contradiction import assess_contradiction, find_related_pairs
from docgrity.agents.duplicate import assess_pair, find_candidate_pairs
from docgrity.agents.open_question import assess_open_questions
from docgrity.agents.ownership import assess_ownership
from docgrity.core.config import get_settings
from docgrity.core.db import get_session_factory
from docgrity.core.enums import (
    ActionType,
    FindingSeverity,
    FindingStatus,
    FindingType,
    ScanStatus,
)
from docgrity.core.models import (
    AuditEvent,
    CommentAction,
    Finding,
    FindingAction,
    FindingEvidence,
    FindingPerson,
    KnowledgeItem,
    Scan,
    User,
)
from docgrity.ingestion.confluence import page_web_url
from docgrity.mcp.confluence.client import ConfluenceClient, ConfluenceError

logger = logging.getLogger("docgrity.scan")


def _as_app_client(app_token: str | None, cloud_id: str | None) -> ConfluenceClient | None:
    """Client that posts as the Forge app (Docgrity) when a token is available."""
    if not (app_token and cloud_id):
        return None
    return ConfluenceClient(
        base_url=f"https://api.atlassian.com/ex/confluence/{cloud_id}",
        access_token=app_token,
    )


async def scan_duplicates(
    ctx: dict,
    tenant_id: str,
    post_comments: bool = False,
    space_id: str | None = None,
    app_token: str | None = None,
    cloud_id: str | None = None,
) -> dict[str, Any]:
    """Run a duplicate scan for a tenant. Comments only posted when enabled + allowed."""
    tenant_uuid = uuid.UUID(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        scan = Scan(
            tenant_id=tenant_uuid,
            status=ScanStatus.RUNNING,
            started_at=datetime.now(UTC),
            checks=["duplicates"],
            actions={"post_comments": post_comments, "space_id": space_id},
        )
        session.add(scan)
        await session.commit()
        scan_id = scan.id

    logger.info("scan.started", extra={"scan_id": str(scan_id), "tenant_id": tenant_id})
    findings_created = 0
    pairs_assessed = 0
    error: str | None = None
    try:
        async with session_factory() as session:
            pairs = await find_candidate_pairs(session, tenant_uuid, space_id=space_id)
            for pair in pairs:
                if await _already_reported(session, tenant_uuid, pair):
                    continue
                assessment, run, item_a, item_b = await assess_pair(session, pair)
                pairs_assessed += 1
                if not assessment.is_duplicate or not assessment.evidence:
                    continue
                if assessment.confidence < settings.duplicate_confidence_threshold:
                    continue
                finding = await _create_finding(
                    session, tenant_uuid, scan_id, pair, assessment, run, item_a, item_b
                )
                await _attach_potential_owners(session, tenant_uuid, finding, item_a, item_b)
                if post_comments:
                    await _post_comment(
                        session,
                        tenant_uuid,
                        finding,
                        item_a,
                        item_b,
                        client=_as_app_client(app_token, cloud_id),
                    )
                # Commit per finding so partial progress survives a provider
                # failure (rate limit / overload) later in the loop.
                await session.commit()
                findings_created += 1
    except Exception as exc:  # noqa: BLE001 - recorded on the scan row
        error = str(exc)
        logger.exception("scan.failed", extra={"scan_id": str(scan_id)})

    async with session_factory() as session:
        scan = await session.get(Scan, scan_id)
        scan.status = ScanStatus.FAILED if error else ScanStatus.COMPLETED
        scan.completed_at = datetime.now(UTC)
        scan.error = error
        scan.stats = {"pairs_assessed": pairs_assessed, "findings_created": findings_created}
        await session.commit()

    logger.info(
        "scan.completed",
        extra={
            "scan_id": str(scan_id),
            "status": "FAILED" if error else "COMPLETED",
            "pairs_assessed": pairs_assessed,
            "findings_created": findings_created,
        },
    )
    return {
        "scan_id": str(scan_id),
        "pairs_assessed": pairs_assessed,
        "findings_created": findings_created,
        "error": error,
    }


async def scan_contradictions(
    ctx: dict,
    tenant_id: str,
    post_comments: bool = False,
    space_id: str | None = None,
    app_token: str | None = None,
    cloud_id: str | None = None,
) -> dict[str, Any]:
    """Run a contradiction scan: related pairs → conflict judgement → finding."""
    tenant_uuid = uuid.UUID(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()

    scan_id = await _start_scan(
        session_factory, tenant_uuid, "contradictions", post_comments, space_id
    )
    findings_created = 0
    pairs_assessed = 0
    error: str | None = None
    try:
        async with session_factory() as session:
            pairs = await find_related_pairs(session, tenant_uuid, space_id=space_id)
            for pair in pairs:
                if await _already_reported(session, tenant_uuid, pair, FindingType.CONTRADICTION):
                    continue
                assessment, run, item_a, item_b = await assess_contradiction(session, pair)
                pairs_assessed += 1
                if not assessment.is_contradiction or not assessment.evidence:
                    continue
                if assessment.confidence < settings.contradiction_confidence_threshold:
                    continue
                finding = Finding(
                    tenant_id=tenant_uuid,
                    type=FindingType.CONTRADICTION,
                    severity=FindingSeverity(assessment.severity),
                    status=FindingStatus.NEW,
                    title=f"Contradiction: “{item_a.title}” vs “{item_b.title}”",
                    summary=assessment.summary,
                    confidence=assessment.confidence,
                    recommended_action="REVIEW",
                    detail={
                        "item_a_id": str(pair.item_a_id),
                        "item_b_id": str(pair.item_b_id),
                        "distance": pair.distance,
                        "conflicting_claims": assessment.conflicting_claims,
                        "pages": _pages_detail(item_a, item_b),
                    },
                    model=run.model,
                    prompt_version=run.prompt_version,
                    input_hash=run.input_hash,
                    scan_id=scan_id,
                )
                session.add(finding)
                await session.flush()
                _add_evidence(session, tenant_uuid, finding, assessment.evidence, item_a, item_b)
                _add_audit(session, tenant_uuid, "agent:contradiction", finding, scan_id)
                await _attach_potential_owners(session, tenant_uuid, finding, item_a, item_b)
                if post_comments:
                    await _post_comment(
                        session,
                        tenant_uuid,
                        finding,
                        item_a,
                        item_b,
                        client=_as_app_client(app_token, cloud_id),
                    )
                await session.commit()
                findings_created += 1
    except Exception as exc:  # noqa: BLE001 - recorded on the scan row
        error = str(exc)
        logger.exception("scan.failed", extra={"scan_id": str(scan_id)})

    await _finish_scan(
        session_factory,
        scan_id,
        error,
        {"pairs_assessed": pairs_assessed, "findings_created": findings_created},
    )
    return {
        "scan_id": str(scan_id),
        "pairs_assessed": pairs_assessed,
        "findings_created": findings_created,
        "error": error,
    }


async def scan_open_questions(
    ctx: dict,
    tenant_id: str,
    post_comments: bool = False,
    space_id: str | None = None,
    app_token: str | None = None,
    cloud_id: str | None = None,
) -> dict[str, Any]:
    """Run an open-question scan: per-page LLM check for unresolved items."""
    tenant_uuid = uuid.UUID(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()

    scan_id = await _start_scan(
        session_factory, tenant_uuid, "open_questions", post_comments, space_id
    )
    findings_created = 0
    pages_assessed = 0
    error: str | None = None
    try:
        async with session_factory() as session:
            query = select(KnowledgeItem).where(
                KnowledgeItem.tenant_id == tenant_uuid,
                KnowledgeItem.content.isnot(None),
            )
            if space_id:
                query = query.where(KnowledgeItem.meta["space_id"].astext == str(space_id))
            items = (await session.scalars(query)).all()
            for item in items:
                if await _open_question_reported(session, tenant_uuid, item.id):
                    continue
                assessment, run = await assess_open_questions(item)
                pages_assessed += 1
                questions = [
                    q
                    for q in assessment.questions
                    if q.confidence >= settings.open_question_confidence_threshold and q.excerpt
                ]
                if not questions:
                    continue
                finding = Finding(
                    tenant_id=tenant_uuid,
                    type=FindingType.OPEN_QUESTION,
                    severity=FindingSeverity(assessment.severity),
                    status=FindingStatus.NEW,
                    title=f"Open questions in “{item.title}”",
                    summary=assessment.summary or f"{len(questions)} unresolved question(s) found.",
                    confidence=max(q.confidence for q in questions),
                    recommended_action="REVIEW",
                    detail={
                        "item_id": str(item.id),
                        "questions": [q.question for q in questions],
                        "pages": [_page_detail(item)],
                    },
                    model=run.model,
                    prompt_version=run.prompt_version,
                    input_hash=run.input_hash,
                    scan_id=scan_id,
                )
                session.add(finding)
                await session.flush()
                for q in questions:
                    session.add(
                        FindingEvidence(
                            tenant_id=tenant_uuid,
                            finding_id=finding.id,
                            knowledge_item_id=item.id,
                            excerpt=q.excerpt,
                            source_label=item.title,
                        )
                    )
                _add_audit(session, tenant_uuid, "agent:open_question", finding, scan_id)
                await _attach_potential_owners(session, tenant_uuid, finding, item, item)
                if post_comments:
                    await _post_comment(
                        session,
                        tenant_uuid,
                        finding,
                        item,
                        item,
                        client=_as_app_client(app_token, cloud_id),
                    )
                await session.commit()
                findings_created += 1
    except Exception as exc:  # noqa: BLE001 - recorded on the scan row
        error = str(exc)
        logger.exception("scan.failed", extra={"scan_id": str(scan_id)})

    await _finish_scan(
        session_factory,
        scan_id,
        error,
        {"pages_assessed": pages_assessed, "findings_created": findings_created},
    )
    return {
        "scan_id": str(scan_id),
        "pages_assessed": pages_assessed,
        "findings_created": findings_created,
        "error": error,
    }


async def _start_scan(
    session_factory,
    tenant_id: uuid.UUID,
    check: str,
    post_comments: bool,
    space_id: str | None = None,
):
    async with session_factory() as session:
        scan = Scan(
            tenant_id=tenant_id,
            status=ScanStatus.RUNNING,
            started_at=datetime.now(UTC),
            checks=[check],
            actions={"post_comments": post_comments, "space_id": space_id},
        )
        session.add(scan)
        await session.commit()
        logger.info(
            "scan.started",
            extra={"scan_id": str(scan.id), "tenant_id": str(tenant_id), "check": check},
        )
        return scan.id


async def _finish_scan(session_factory, scan_id, error: str | None, stats: dict) -> None:
    async with session_factory() as session:
        scan = await session.get(Scan, scan_id)
        scan.status = ScanStatus.FAILED if error else ScanStatus.COMPLETED
        scan.completed_at = datetime.now(UTC)
        scan.error = error
        scan.stats = stats
        await session.commit()
    logger.info(
        "scan.completed",
        extra={"scan_id": str(scan_id), "status": "FAILED" if error else "COMPLETED", **stats},
    )


def _pages_detail(item_a: KnowledgeItem, item_b: KnowledgeItem) -> list[dict]:
    return [_page_detail(item_a), _page_detail(item_b)]


def _page_detail(item: KnowledgeItem) -> dict:
    return {
        "id": str(item.id),
        "external_id": item.external_id,
        "title": item.title,
        "url": page_web_url(item.url),
    }


def _add_evidence(session, tenant_id, finding, evidence, item_a, item_b) -> None:
    items_by_ext = {item_a.external_id: item_a, item_b.external_id: item_b}
    for ev in evidence:
        item = items_by_ext.get(ev.knowledge_item_external_id)
        session.add(
            FindingEvidence(
                tenant_id=tenant_id,
                finding_id=finding.id,
                knowledge_item_id=item.id if item else None,
                excerpt=ev.excerpt,
                source_label=ev.source_label,
            )
        )


def _add_audit(session, tenant_id, actor: str, finding, scan_id) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor=actor,
            event_type="FINDING_CREATED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="ALLOWED",
            detail={"scan_id": str(scan_id), "confidence": finding.confidence},
        )
    )


async def _open_question_reported(
    session: AsyncSession, tenant_id: uuid.UUID, item_id: uuid.UUID
) -> bool:
    existing = await session.scalar(
        select(Finding.id).where(
            Finding.tenant_id == tenant_id,
            Finding.type == FindingType.OPEN_QUESTION,
            # RESOLVED findings may legitimately recur; DISMISSED / FALSE_POSITIVE
            # are human "ignore" decisions and must never be re-reported.
            Finding.status != FindingStatus.RESOLVED,
            Finding.detail["item_id"].astext == str(item_id),
        )
    )
    return existing is not None


async def _already_reported(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    pair,
    finding_type: FindingType = FindingType.DUPLICATE,
) -> bool:
    existing = await session.scalar(
        select(Finding.id).where(
            Finding.tenant_id == tenant_id,
            Finding.type == finding_type,
            # RESOLVED findings may legitimately recur; DISMISSED / FALSE_POSITIVE
            # are human "ignore" decisions and must never be re-reported.
            Finding.status != FindingStatus.RESOLVED,
            Finding.detail["item_a_id"].astext == str(pair.item_a_id),
            Finding.detail["item_b_id"].astext == str(pair.item_b_id),
        )
    )
    return existing is not None


async def _create_finding(
    session, tenant_id, scan_id, pair, assessment, run, item_a, item_b
) -> Finding:
    finding = Finding(
        tenant_id=tenant_id,
        type=FindingType.DUPLICATE,
        severity=FindingSeverity(assessment.severity),
        status=FindingStatus.NEW,
        title=f"Possible duplicate: “{item_a.title}” / “{item_b.title}”",
        summary=assessment.summary,
        confidence=assessment.confidence,
        recommended_action=assessment.recommended_action.value,
        detail={
            "item_a_id": str(pair.item_a_id),
            "item_b_id": str(pair.item_b_id),
            "distance": pair.distance,
            "differences": assessment.differences,
            "pages": _pages_detail(item_a, item_b),
        },
        model=run.model,
        prompt_version=run.prompt_version,
        input_hash=run.input_hash,
        scan_id=scan_id,
    )
    session.add(finding)
    await session.flush()

    items_by_ext = {item_a.external_id: item_a, item_b.external_id: item_b}
    for ev in assessment.evidence:
        item = items_by_ext.get(ev.knowledge_item_external_id)
        session.add(
            FindingEvidence(
                tenant_id=tenant_id,
                finding_id=finding.id,
                knowledge_item_id=item.id if item else None,
                excerpt=ev.excerpt,
                source_label=ev.source_label,
            )
        )
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor="agent:duplicate",
            event_type="FINDING_CREATED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="ALLOWED",
            detail={"scan_id": str(scan_id), "confidence": assessment.confidence},
        )
    )
    return finding


async def _attach_potential_owners(session, tenant_id, finding, item_a, item_b) -> None:
    for item in (item_a, item_b):
        signals = {
            "owner_id": item.meta.get("owner_id"),
            "author_id": item.meta.get("author_id"),
            "recent_editor_ids": item.meta.get("recent_editor_ids", []),
            "source_updated_at": item.source_updated_at,
        }
        if not any(v for v in signals.values()):
            continue
        assessment, _run = await assess_ownership(item.title, signals)
        for candidate in assessment.candidates[:2]:
            user = await _get_or_create_user(session, tenant_id, candidate.account_id)
            session.add(
                FindingPerson(
                    tenant_id=tenant_id,
                    finding_id=finding.id,
                    user_id=user.id,
                    confidence=candidate.confidence,
                    authoritative=False,  # inferred ownership is always potential
                    evidence=candidate.evidence,
                )
            )


async def _get_or_create_user(session, tenant_id, account_id: str) -> User:
    user = await session.scalar(
        select(User).where(User.tenant_id == tenant_id, User.external_id == account_id)
    )
    if user is None:
        display_name = account_id
        try:
            async with ConfluenceClient.from_settings(get_settings()) as client:
                data = await client.get_user(account_id)
                display_name = data.get("displayName") or data.get("publicName") or account_id
        except Exception:  # noqa: BLE001 - name resolution is best-effort
            logger.warning("Could not resolve display name for account %s", account_id)
        user = User(tenant_id=tenant_id, external_id=account_id, display_name=display_name)
        session.add(user)
        await session.flush()
    return user


async def _post_comment(session, tenant_id, finding, item_a, item_b, client=None) -> None:
    """Draft and post the Docgrity comment on page A. Policy-gated + audited.

    When ``client`` is provided (e.g. an as-app Forge client so the comment
    shows as Docgrity), it is used instead of the settings-based client.
    Falls back to the settings client if the app token was rejected (expired).
    """
    persons = (
        await session.scalars(select(FindingPerson).where(FindingPerson.finding_id == finding.id))
    ).all()
    owner_ids = []
    for person in persons:
        user = await session.get(User, person.user_id)
        owner_ids.append({"account_id": user.external_id, "confidence": person.confidence})

    evidence_rows = (
        await session.scalars(
            select(FindingEvidence).where(FindingEvidence.finding_id == finding.id)
        )
    ).all()
    draft, run = await draft_comment(
        {
            "finding_type": finding.type.value,
            "summary": finding.summary,
            "evidence": [{"excerpt": e.excerpt, "source": e.source_label} for e in evidence_rows],
            "potential_owners": owner_ids,
            "pages": [
                {"title": item_a.title, "url": page_web_url(item_a.url)},
                {"title": item_b.title, "url": page_web_url(item_b.url)},
            ],
            "recommended_action": finding.recommended_action,
        }
    )
    pages = [
        {"title": item_a.title, "url": page_web_url(item_a.url)},
        {"title": item_b.title, "url": page_web_url(item_b.url)},
    ]
    comment_html = comment_to_storage_html(draft, pages=pages)

    action = FindingAction(
        tenant_id=tenant_id,
        finding_id=finding.id,
        action_type=ActionType.ADD_CONFLUENCE_COMMENT,
        status="REQUESTED",
        detail={"page_external_id": item_a.external_id, "model": run.model},
    )
    session.add(action)
    await session.flush()

    settings = get_settings()
    comment_client = client if client is not None else ConfluenceClient.from_settings(settings)
    try:
        async with comment_client as active_client:
            response = await active_client.add_footer_comment(item_a.external_id, comment_html)
    except ConfluenceError as exc:
        # App token expired mid-scan → fall back to the configured API token
        # so the comment still lands (authored as the integration user).
        if client is None or exc.status_code not in (401, 403):
            raise
        logger.warning("post_comment.as_app_rejected", extra={"status": exc.status_code})
        async with ConfluenceClient.from_settings(settings) as active_client:
            response = await active_client.add_footer_comment(item_a.external_id, comment_html)
    action.status = "EXECUTED"
    action.executed_at = datetime.now(UTC)
    session.add(
        CommentAction(
            tenant_id=tenant_id,
            finding_id=finding.id,
            knowledge_item_id=item_a.id,
            external_comment_id=str(response.get("id", "")),
            state="CREATED",
        )
    )
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor="agent:action",
            event_type="COMMENT_POSTED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="ALLOWED",
            detail={"page": item_a.external_id, "comment_id": str(response.get("id", ""))},
        )
    )
    finding.status = FindingStatus.AWAITING_OWNER


async def notify_owner(
    ctx: dict,
    tenant_id: str,
    finding_id: str,
    app_token: str | None = None,
    cloud_id: str | None = None,
) -> dict:
    """Background task: draft + post the owner-notification comment.

    Runs in the worker so the Forge frontend call returns instantly (Forge
    caps invokeRemote at 25s; comment drafting uses an LLM and can exceed it).
    When app_token/cloud_id are supplied the comment is posted as the app.
    """
    tenant_uuid = uuid.UUID(tenant_id)
    session_factory = get_session_factory()
    async with session_factory() as session:
        finding = await session.scalar(
            select(Finding).where(
                Finding.id == uuid.UUID(finding_id), Finding.tenant_id == tenant_uuid
            )
        )
        if finding is None:
            return {"ok": False, "reason": "finding not found"}
        detail = finding.detail or {}
        a_id = uuid.UUID(detail.get("item_a_id") or detail.get("item_id"))
        b_id = uuid.UUID(detail.get("item_b_id") or detail.get("item_id"))
        items = (
            await session.scalars(
                select(KnowledgeItem).where(
                    KnowledgeItem.id.in_([a_id, b_id]),
                    KnowledgeItem.tenant_id == tenant_uuid,
                )
            )
        ).all()
        by_id = {i.id: i for i in items}
        if a_id not in by_id or b_id not in by_id:
            return {"ok": False, "reason": "referenced pages no longer exist"}

        client = _as_app_client(app_token, cloud_id)
        await _post_comment(session, tenant_uuid, finding, by_id[a_id], by_id[b_id], client=client)
        await session.commit()
    return {"ok": True}
