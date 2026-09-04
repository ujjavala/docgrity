"""Scan endpoints: trigger and inspect scans."""

from __future__ import annotations

import logging
import uuid

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docgrity.api.auth import AuthContext, get_auth
from docgrity.api.schemas import ScanCreateRequest, ScanResponse
from docgrity.core.config import get_settings
from docgrity.core.db import get_session
from docgrity.core.models import AuditEvent, Scan

logger = logging.getLogger("docgrity.api.scans")

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])


async def _enqueue(task: str, tenant_id: str, *args) -> None:
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        # Tenant-namespaced job keys prevent cross-tenant collisions/bleeding.
        job_id = f"tenant:{tenant_id}:job:{task}:{uuid.uuid4().hex}"
        await pool.enqueue_job(task, tenant_id, *args, _job_id=job_id)
    finally:
        await pool.aclose()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_scan(
    request: ScanCreateRequest,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Enqueue scan work. The worker creates the Scan row and reports progress."""
    enqueued: list[str] = []
    if "ingest" in request.checks:
        if not request.source_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_id required for ingest")
        await _enqueue("ingest_confluence_source", str(auth.tenant_id), str(request.source_id))
        enqueued.append("ingest")
    if "duplicates" in request.checks:
        await _enqueue(
            "scan_duplicates",
            str(auth.tenant_id),
            request.post_comments,
            request.space_id,
            auth.app_token,
            auth.cloud_id,
        )
        enqueued.append("duplicates")
    if "contradictions" in request.checks:
        await _enqueue(
            "scan_contradictions",
            str(auth.tenant_id),
            request.post_comments,
            request.space_id,
            auth.app_token,
            auth.cloud_id,
        )
        enqueued.append("contradictions")
    if "open_questions" in request.checks:
        await _enqueue(
            "scan_open_questions",
            str(auth.tenant_id),
            request.post_comments,
            request.space_id,
            auth.app_token,
            auth.cloud_id,
        )
        enqueued.append("open_questions")
    # Cross-boundary checks — no-op gracefully when the connector isn't configured.
    for check, task in (
        ("stale_specs", "scan_stale_specs"),
        ("code_doc_drift", "scan_code_doc_drift"),
        ("tribal_knowledge", "scan_tribal_knowledge"),
    ):
        if check in request.checks:
            await _enqueue(task, str(auth.tenant_id), request.post_comments, request.space_id)
            enqueued.append(check)
    if not enqueued:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No known checks requested")
    session.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor=auth.subject,
            event_type="SCAN_REQUESTED",
            resource_type="scan",
            resource_id="",
            policy_decision="ALLOWED",
            detail={
                "checks": enqueued,
                "post_comments": request.post_comments,
                "space_id": request.space_id,
            },
        )
    )
    await session.commit()
    logger.info(
        "scan.requested",
        extra={"tenant_id": str(auth.tenant_id), "checks": enqueued, "actor": auth.subject},
    )
    return {"enqueued": enqueued}


@router.get("", response_model=list[ScanResponse])
async def list_scans(
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Scan]:
    result = await session.scalars(
        select(Scan)
        .where(Scan.tenant_id == auth.tenant_id)
        .order_by(Scan.created_at.desc())
        .limit(limit)
    )
    return list(result)


@router.get("/{scan_id}", response_model=ScanResponse)
async def get_scan(
    scan_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth),
    session: AsyncSession = Depends(get_session),
) -> Scan:
    scan = await session.scalar(
        select(Scan).where(Scan.id == scan_id, Scan.tenant_id == auth.tenant_id)
    )
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan
