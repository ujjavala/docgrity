"""Finding endpoints: list, inspect, and update status (human-in-the-loop)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from docgrity.agents.editor import draft_edit
from docgrity.api.auth import AuthContext, get_auth
from docgrity.api.schemas import (
    ActionResultResponse,
    ApplyFixRequest,
    DraftFixResponse,
    EditPatchResponse,
    EvidenceResponse,
    FindingDetailResponse,
    FindingResponse,
    FindingStatsResponse,
    FindingStatusUpdate,
    MergeRedirectRequest,
    PageRef,
    PersonResponse,
)
from docgrity.core.config import get_settings
from docgrity.core.db import get_session
from docgrity.core.enums import FindingStatus, FindingType, ScanStatus
from docgrity.core.models import AuditEvent, Finding, KnowledgeItem, Scan, User
from docgrity.ingestion.confluence import page_web_url
from docgrity.workflows.actions import ActionError, apply_patch, merge_and_redirect

logger = logging.getLogger("docgrity.findings")

router = APIRouter(prefix="/api/v1/findings", tags=["findings"])

# Status transitions a human may apply via the API.
ALLOWED_MANUAL_STATUSES = {
    FindingStatus.RESOLVED,
    FindingStatus.DISMISSED,
    FindingStatus.FALSE_POSITIVE,
}


@router.get("", response_model=list[FindingResponse])
async def list_findings(
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
    finding_status: FindingStatus | None = Query(default=None, alias="status"),
    finding_type: FindingType | None = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[FindingResponse]:
    query = (
        select(Finding)
        .where(Finding.tenant_id == auth.tenant_id)
        .options(selectinload(Finding.persons))
        .order_by(Finding.created_at.desc())
        .limit(limit)
    )
    if finding_status:
        query = query.where(Finding.status == finding_status)
    if finding_type:
        query = query.where(Finding.type == finding_type)
    findings = list(await session.scalars(query))

    user_ids = {p.user_id for f in findings for p in f.persons}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        users = {u.id: u for u in await session.scalars(select(User).where(User.id.in_(user_ids)))}
    responses: list[FindingResponse] = []
    for f in findings:
        resp = FindingResponse.model_validate(f)
        seen: set[uuid.UUID] = set()
        names: list[str] = []
        for person in f.persons:
            if person.user_id in seen:
                continue
            seen.add(person.user_id)
            user = users.get(person.user_id)
            if user is not None:
                names.append(user.display_name)
        resp.owner_names = names
        responses.append(resp)
    return responses


_OPEN_STATUSES = [
    s
    for s in FindingStatus
    if s not in (FindingStatus.RESOLVED, FindingStatus.DISMISSED, FindingStatus.FALSE_POSITIVE)
]


@router.get("/stats", response_model=FindingStatsResponse)
async def finding_stats(
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> FindingStatsResponse:
    """Aggregate open-finding counts for the dashboard landing page."""
    rows = (
        await session.execute(
            select(Finding.type, Finding.severity, Finding.status, func.count())
            .where(Finding.tenant_id == auth.tenant_id, Finding.status.in_(_OPEN_STATUSES))
            .group_by(Finding.type, Finding.severity, Finding.status)
        )
    ).all()
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    total = 0
    for ftype, severity, fstatus, count in rows:
        by_type[ftype.value] = by_type.get(ftype.value, 0) + count
        by_severity[severity.value] = by_severity.get(severity.value, 0) + count
        by_status[fstatus.value] = by_status.get(fstatus.value, 0) + count
        total += count
    last_completed = await session.scalar(
        select(func.max(Scan.completed_at)).where(
            Scan.tenant_id == auth.tenant_id, Scan.status == ScanStatus.COMPLETED
        )
    )
    return FindingStatsResponse(
        total_open=total,
        by_type=by_type,
        by_severity=by_severity,
        by_status=by_status,
        last_scan_completed_at=last_completed,
    )


@router.get("/{finding_id}", response_model=FindingDetailResponse)
async def get_finding(
    finding_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> FindingDetailResponse:
    finding = await session.scalar(
        select(Finding)
        .where(Finding.id == finding_id, Finding.tenant_id == auth.tenant_id)
        .options(selectinload(Finding.evidence), selectinload(Finding.persons))
    )
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    owners: list[PersonResponse] = []
    seen_owner_ids: set[uuid.UUID] = set()
    for person in finding.persons:
        if person.user_id in seen_owner_ids:
            continue
        seen_owner_ids.add(person.user_id)
        user = await session.get(User, person.user_id)
        owners.append(
            PersonResponse(
                account_id=user.external_id or "",
                display_name=user.display_name,
                confidence=person.confidence,
                authoritative=person.authoritative,
                evidence=person.evidence,
            )
        )
    base = FindingResponse.model_validate(finding).model_dump()
    base["owner_names"] = [o.display_name for o in owners]
    detail = base.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("pages"), list):
        # Normalise legacy relative/broken URLs stored in older findings.
        detail = {
            **detail,
            "pages": [
                {**p, "url": page_web_url(p.get("url"))} if isinstance(p, dict) else p
                for p in detail["pages"]
            ],
        }
        base["detail"] = detail
    return FindingDetailResponse(
        **base,
        evidence=[EvidenceResponse.model_validate(e) for e in finding.evidence],
        potential_owners=owners,
        pages=await _resolve_pages(session, finding),
    )


async def _resolve_pages(session: AsyncSession, finding: Finding) -> list[PageRef]:
    """Build absolute page links from the knowledge items referenced by a finding."""
    detail = finding.detail or {}
    item_ids: list[uuid.UUID] = []
    for key in ("item_a_id", "item_b_id", "item_id"):
        raw = detail.get(key)
        if not raw:
            continue
        try:
            item_ids.append(uuid.UUID(raw))
        except (ValueError, TypeError):
            continue
    if not item_ids:
        return []
    items = (
        await session.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.id.in_(item_ids),
                KnowledgeItem.tenant_id == finding.tenant_id,
            )
        )
    ).all()
    by_id = {i.id: i for i in items}
    settings = get_settings()
    base = (settings.confluence_base_url or "").rstrip("/")
    refs: list[PageRef] = []
    for iid in item_ids:
        item = by_id.get(iid)
        if not item:
            continue
        url = page_web_url(item.url)
        if not url and base and item.external_id:
            # Canonical fallback that always resolves, even without a stored webui path.
            url = f"{base}/wiki/pages/viewpage.action?pageId={item.external_id}"
        refs.append(
            PageRef(id=str(item.id), external_id=item.external_id, title=item.title, url=url)
        )
    return refs


@router.post("/{finding_id}/status", response_model=FindingResponse)
async def update_finding_status(
    finding_id: uuid.UUID,
    update: FindingStatusUpdate,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> Finding:
    if update.status not in ALLOWED_MANUAL_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Manual status must be one of {sorted(s.value for s in ALLOWED_MANUAL_STATUSES)}",
        )
    finding = await session.scalar(
        select(Finding).where(Finding.id == finding_id, Finding.tenant_id == auth.tenant_id)
    )
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    finding.status = update.status
    if update.status == FindingStatus.RESOLVED:
        finding.resolved_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor=auth.subject,
            event_type="FINDING_STATUS_CHANGED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="ALLOWED",
            detail={"new_status": update.status.value},
        )
    )
    await session.commit()
    await session.refresh(finding)
    return finding


async def _load_finding(
    session: AsyncSession, finding_id: uuid.UUID, tenant_id: uuid.UUID
) -> Finding:
    finding = await session.scalar(
        select(Finding)
        .where(Finding.id == finding_id, Finding.tenant_id == tenant_id)
        .options(selectinload(Finding.evidence))
    )
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


async def _finding_items(
    session: AsyncSession, finding: Finding
) -> tuple[KnowledgeItem, KnowledgeItem]:
    detail = finding.detail or {}
    try:
        a_id = uuid.UUID(detail.get("item_a_id") or detail.get("item_id") or "")
        b_id = uuid.UUID(detail.get("item_b_id") or detail.get("item_id") or "")
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Finding does not reference a page pair"
        ) from exc
    items = (
        await session.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.id.in_([a_id, b_id]),
                KnowledgeItem.tenant_id == finding.tenant_id,
            )
        )
    ).all()
    by_id = {i.id: i for i in items}
    if a_id not in by_id or b_id not in by_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Referenced pages no longer exist")
    return by_id[a_id], by_id[b_id]


@router.post("/{finding_id}/actions/merge-redirect", response_model=ActionResultResponse)
async def merge_redirect_action(
    finding_id: uuid.UUID,
    body: MergeRedirectRequest,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> ActionResultResponse:
    """Human-approved: archive the duplicate page with a redirect notice."""
    finding = await _load_finding(session, finding_id, auth.tenant_id)
    if finding.type != FindingType.DUPLICATE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only duplicate findings can be merged")
    try:
        result = await merge_and_redirect(session, finding, body.keep_item_id, auth.subject)
    except ActionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ActionResultResponse(ok=True, detail=result)


@router.post("/{finding_id}/actions/draft-fix", response_model=DraftFixResponse)
async def draft_fix_action(
    finding_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> DraftFixResponse:
    """Draft (not apply) a precise patch resolving a contradiction."""
    finding = await _load_finding(session, finding_id, auth.tenant_id)
    if finding.type != FindingType.CONTRADICTION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Fix drafting is only available for contradictions"
        )
    item_a, item_b = await _finding_items(session, finding)
    claims = [e.excerpt for e in finding.evidence if e.excerpt]
    draft, _run = await draft_edit(item_a, item_b, finding.summary, claims)
    titles = {item_a.external_id: item_a.title, item_b.external_id: item_b.title}
    session.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor=auth.subject,
            event_type="FIX_DRAFTED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="ALLOWED",
            detail={"patch_count": len(draft.patches)},
        )
    )
    await session.commit()
    return DraftFixResponse(
        patches=[
            EditPatchResponse(
                page_external_id=p.page_external_id,
                page_title=titles.get(p.page_external_id),
                find_text=p.find_text,
                replace_text=p.replace_text,
                rationale=p.rationale,
                confidence=p.confidence,
            )
            for p in draft.patches
        ],
        reasoning=draft.reasoning,
    )


@router.post("/{finding_id}/actions/apply-fix", response_model=ActionResultResponse)
async def apply_fix_action(
    finding_id: uuid.UUID,
    body: ApplyFixRequest,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> ActionResultResponse:
    """Human-approved: apply a previously drafted patch (exact match or reject)."""
    finding = await _load_finding(session, finding_id, auth.tenant_id)
    try:
        result = await apply_patch(
            session,
            finding,
            body.page_external_id,
            body.find_text,
            body.replace_text,
            auth.subject,
        )
    except ActionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ActionResultResponse(ok=True, detail=result)


@router.post("/{finding_id}/actions/notify-owner", response_model=ActionResultResponse)
async def notify_owner_action(
    finding_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> ActionResultResponse:
    """Human-approved: post a Docgrity comment @-mentioning the inferred owner.

    Enqueued to the worker: comment drafting uses an LLM and can exceed the
    25s Forge invokeRemote cap. The app system token (when present) is passed
    so the comment is authored by the Docgrity app, not the user.
    """
    finding = await _load_finding(session, finding_id, auth.tenant_id)
    item_a, _item_b = await _finding_items(session, finding)
    logger.info(
        "notify_owner.auth_path",
        extra={"as_app": bool(auth.app_token and auth.cloud_id), "subject": auth.subject},
    )
    await _enqueue_task(
        "notify_owner",
        str(auth.tenant_id),
        str(finding.id),
        auth.app_token,
        auth.cloud_id,
    )
    session.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor=auth.subject,
            event_type="OWNER_NOTIFIED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="HUMAN_APPROVED",
            detail={"page": item_a.external_id, "queued": True},
        )
    )
    await session.commit()
    return ActionResultResponse(ok=True, detail={"page": item_a.external_id, "queued": True})


async def _enqueue_task(task: str, tenant_id: str, *args) -> None:
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job_id = f"tenant:{tenant_id}:job:{task}:{uuid.uuid4().hex}"
        await pool.enqueue_job(task, tenant_id, *args, _job_id=job_id)
    finally:
        await pool.aclose()
