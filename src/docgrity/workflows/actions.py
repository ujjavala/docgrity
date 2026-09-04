"""Deterministic execution of human-approved finding actions.

Architectural principles honoured here:
- Destructive actions (page edit, archive) run ONLY from explicit human
  approval (dashboard click) — never autonomously from an agent.
- Application is deterministic: an EditPatch is applied with exact-match
  replacement or rejected; no fuzzy/LLM-side mutation of page content.
- Every action is recorded as FindingAction + AuditEvent.
"""

from __future__ import annotations

import html
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docgrity.core.config import get_settings
from docgrity.core.enums import ActionType, FindingStatus
from docgrity.core.models import AuditEvent, Finding, FindingAction, KnowledgeItem
from docgrity.ingestion.confluence import page_web_url
from docgrity.mcp.confluence.client import ConfluenceClient


class ActionError(Exception):
    """Raised when a requested action cannot be executed safely."""


def _moved_notice(target_title: str, target_url: str) -> str:
    """Storage-format 'this page has moved' info panel."""
    return (
        '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
        f"<p><strong>This page has moved.</strong> The maintained version is "
        f'<a href="{html.escape(target_url, quote=True)}">{html.escape(target_title)}</a>. '
        "This copy was archived by Docgrity after a human-approved merge.</p>"
        "</ac:rich-text-body></ac:structured-macro>"
    )


async def merge_and_redirect(
    session: AsyncSession,
    finding: Finding,
    keep_item_id: uuid.UUID,
    actor: str,
) -> dict[str, Any]:
    """Archive the duplicate page, leaving a redirect notice to the kept page."""
    detail = finding.detail or {}
    ids = [detail.get("item_a_id"), detail.get("item_b_id")]
    if str(keep_item_id) not in ids:
        raise ActionError("keep_item_id is not part of this finding")
    archive_item_id = uuid.UUID(next(i for i in ids if i != str(keep_item_id)))

    keep = await _get_item(session, finding.tenant_id, keep_item_id)
    archive = await _get_item(session, finding.tenant_id, archive_item_id)

    keep_url = page_web_url(keep.url) or ""
    settings = get_settings()
    async with ConfluenceClient.from_settings(settings) as client:
        page = await client.get_page(archive.external_id, body_format="storage")
        version = (page.get("version") or {}).get("number", 1)
        body = (page.get("body") or {}).get("storage", {}).get("value", "")
        new_body = _moved_notice(keep.title, keep_url) + body
        await client.update_page(
            archive.external_id,
            page.get("title", archive.title),
            new_body,
            version + 1,
            message="Docgrity merge & redirect (human-approved)",
        )
        await client.archive_page(archive.external_id)

    finding.status = FindingStatus.RESOLVED
    finding.resolved_at = datetime.now(UTC)
    action = FindingAction(
        tenant_id=finding.tenant_id,
        finding_id=finding.id,
        action_type=ActionType.ARCHIVE_CONFLUENCE_PAGE,
        status="EXECUTED",
        executed_at=datetime.now(UTC),
        detail={
            "kept_page": keep.external_id,
            "archived_page": archive.external_id,
            "approved_by": actor,
        },
    )
    session.add(action)
    session.add(
        AuditEvent(
            tenant_id=finding.tenant_id,
            actor=actor,
            event_type="ACTION_EXECUTED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="HUMAN_APPROVED",
            detail={"action": "merge_redirect", "archived_page": archive.external_id},
        )
    )
    await session.commit()
    return {"kept": keep.external_id, "archived": archive.external_id}


async def apply_patch(
    session: AsyncSession,
    finding: Finding,
    page_external_id: str,
    find_text: str,
    replace_text: str,
    actor: str,
) -> dict[str, Any]:
    """Apply a drafted patch deterministically: exact match or rejection."""
    if not find_text or find_text == replace_text:
        raise ActionError("Patch is empty or a no-op")

    settings = get_settings()
    async with ConfluenceClient.from_settings(settings) as client:
        page = await client.get_page(page_external_id, body_format="storage")
        body = (page.get("body") or {}).get("storage", {}).get("value", "")
        # Page text may appear raw or HTML-escaped inside storage format.
        candidates = [find_text, html.escape(find_text)]
        target = next((c for c in candidates if body.count(c) == 1), None)
        if target is None:
            occurrences = {c: body.count(c) for c in candidates}
            raise ActionError(
                f"Patch rejected: find_text must occur exactly once on the page "
                f"(occurrences: {occurrences}). The page may have changed since drafting."
            )
        replacement = replace_text if target == find_text else html.escape(replace_text)
        new_body = body.replace(target, replacement, 1)
        version = (page.get("version") or {}).get("number", 1)
        await client.update_page(
            page_external_id,
            page.get("title", ""),
            new_body,
            version + 1,
            message="Docgrity contradiction fix (human-approved)",
        )

    finding.status = FindingStatus.RESOLVED
    finding.resolved_at = datetime.now(UTC)
    action = FindingAction(
        tenant_id=finding.tenant_id,
        finding_id=finding.id,
        action_type=ActionType.UPDATE_CONFLUENCE,
        status="EXECUTED",
        executed_at=datetime.now(UTC),
        detail={
            "page_external_id": page_external_id,
            "find_text": find_text,
            "replace_text": replace_text,
            "approved_by": actor,
        },
    )
    session.add(action)
    session.add(
        AuditEvent(
            tenant_id=finding.tenant_id,
            actor=actor,
            event_type="ACTION_EXECUTED",
            resource_type="finding",
            resource_id=str(finding.id),
            policy_decision="HUMAN_APPROVED",
            detail={"action": "apply_fix", "page": page_external_id},
        )
    )
    await session.commit()
    return {"page": page_external_id, "applied": True}


async def _get_item(
    session: AsyncSession, tenant_id: uuid.UUID, item_id: uuid.UUID
) -> KnowledgeItem:
    item = await session.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.id == item_id, KnowledgeItem.tenant_id == tenant_id
        )
    )
    if item is None:
        raise ActionError(f"Knowledge item {item_id} not found")
    return item
