"""Ingestion tasks executed by the arq worker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from docgrity.core.config import get_settings
from docgrity.core.db import get_session_factory
from docgrity.core.enums import ScanStatus, SourceType
from docgrity.core.llm import get_router
from docgrity.core.models import Scan, ScanSource, Source, SourceScope
from docgrity.ingestion.confluence import ConfluenceIngestor, IngestStats
from docgrity.mcp.confluence.client import ConfluenceClient


async def ingest_confluence_source(ctx: dict, tenant_id: str, source_id: str) -> dict[str, Any]:
    """Ingest all configured scopes (spaces) of a Confluence source into knowledge items."""
    tenant_uuid = uuid.UUID(tenant_id)
    source_uuid = uuid.UUID(source_id)
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        source = await session.scalar(
            select(Source).where(Source.id == source_uuid, Source.tenant_id == tenant_uuid)
        )
        if source is None or source.type != SourceType.CONFLUENCE:
            return {"error": f"Confluence source {source_id} not found for tenant"}

        scopes = (
            await session.scalars(select(SourceScope).where(SourceScope.source_id == source_uuid))
        ).all()

        scan = Scan(
            tenant_id=tenant_uuid,
            status=ScanStatus.RUNNING,
            started_at=datetime.now(UTC),
            checks=["ingest"],
        )
        session.add(scan)
        await session.flush()
        session.add(
            ScanSource(
                tenant_id=tenant_uuid,
                scan_id=scan.id,
                source_id=source_uuid,
                scope_external_ids=[scope.external_id for scope in scopes],
            )
        )
        await session.commit()
        scan_id = scan.id

    totals = IngestStats()
    error: str | None = None
    try:
        async with (
            ConfluenceClient.from_settings(settings) as client,
            session_factory() as session,
        ):
            ingestor = ConfluenceIngestor(
                session=session,
                client=client,
                router=get_router(),
                tenant_id=tenant_uuid,
                source_id=source_uuid,
            )
            for scope in scopes:
                stats = await ingestor.ingest_space(scope.external_id)
                totals.pages_seen += stats.pages_seen
                totals.created += stats.created
                totals.updated += stats.updated
                totals.unchanged += stats.unchanged
                totals.embedded += stats.embedded
                totals.errors.extend(stats.errors)
    except Exception as exc:  # noqa: BLE001 - recorded on the scan row
        error = str(exc)

    async with session_factory() as session:
        scan = await session.get(Scan, scan_id)
        scan.status = ScanStatus.FAILED if error else ScanStatus.COMPLETED
        scan.completed_at = datetime.now(UTC)
        scan.error = error
        scan.stats = {
            "pages_seen": totals.pages_seen,
            "created": totals.created,
            "updated": totals.updated,
            "unchanged": totals.unchanged,
            "embedded": totals.embedded,
            "page_errors": totals.errors,
        }
        await session.commit()

    return {"scan_id": str(scan_id), "error": error, **scan.stats}
