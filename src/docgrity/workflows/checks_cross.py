"""Cross-boundary integrity checks (Jira, GitHub, Slack).

All three checks are deterministic orchestration: they fetch external signals
via the connector clients, compare timestamps/similarity, and record findings
with evidence. They no-op gracefully (COMPLETED with skipped=true) when the
connector is not configured, so a Confluence-only install never fails a scan.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from docgrity.core.config import get_settings
from docgrity.core.db import get_session_factory
from docgrity.core.enums import (
    FindingSeverity,
    FindingStatus,
    FindingType,
    SourceType,
)
from docgrity.core.llm import LLMRouter
from docgrity.core.models import Finding, FindingEvidence, KnowledgeItem
from docgrity.mcp.github.client import GitHubClient
from docgrity.mcp.jira.client import JiraClient
from docgrity.mcp.slack.client import SlackClient
from docgrity.workflows.scan import _finish_scan, _page_detail, _start_scan

logger = logging.getLogger("docgrity.scan.cross")

# ENG-123 style Jira issue keys.
_ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")
# GitHub file links inside page content: github.com/owner/repo/blob/ref/path
# (ref treated as a single path segment; branch names with slashes are rare in links)
_GITHUB_FILE_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/blob/([^/\s]+)/([\w.\-/]+)")
# Decision-ish language marking a Slack thread as tribal knowledge.
_DECISION_RE = re.compile(
    r"\b(we (decided|agreed|'ll go with|will go with)|decision:|going with|"
    r"let's (use|go with)|final answer|agreed to)\b",
    re.IGNORECASE,
)
# Cosine distance above which a Slack decision is "not documented anywhere".
TRIBAL_DISTANCE_THRESHOLD = 0.55


async def _already_flagged(session, tenant_id, ftype: FindingType, key: str, value: str) -> bool:
    existing = await session.scalar(
        select(Finding.id).where(
            Finding.tenant_id == tenant_id,
            Finding.type == ftype,
            Finding.detail[key].astext == value,
            # DISMISSED / FALSE_POSITIVE are human "ignore" decisions — never re-report.
            Finding.status != FindingStatus.RESOLVED,
        )
    )
    return existing is not None


def _mk_finding(
    tenant_id, scan_id, ftype: FindingType, title: str, summary: str, detail: dict
) -> Finding:
    return Finding(
        tenant_id=tenant_id,
        type=ftype,
        severity=FindingSeverity.MEDIUM,
        status=FindingStatus.NEW,
        title=title,
        summary=summary,
        confidence=0.9,  # deterministic timestamp/similarity comparison
        recommended_action="REVIEW",
        detail=detail,
        model="deterministic",
        prompt_version="n/a",
        input_hash="n/a",
        scan_id=scan_id,
    )


async def scan_stale_specs(
    ctx: dict, tenant_id: str, post_comments: bool = False, space_id: str | None = None
) -> dict[str, Any]:
    """Flag pages referencing Jira issues resolved AFTER the page's last update."""
    tenant_uuid = uuid.UUID(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()
    if not JiraClient.is_configured(settings):
        logger.info("scan.stale_specs.skipped", extra={"reason": "jira_not_configured"})
        return {"skipped": True, "reason": "Jira connector not configured"}

    scan_id = await _start_scan(
        session_factory, tenant_uuid, "stale_specs", post_comments, space_id
    )
    findings_created = 0
    pages_checked = 0
    error: str | None = None
    try:
        async with session_factory() as session, JiraClient.from_settings(settings) as jira:
            query = select(KnowledgeItem).where(
                KnowledgeItem.tenant_id == tenant_uuid,
                KnowledgeItem.source_type == SourceType.CONFLUENCE,
            )
            if space_id:
                query = query.where(KnowledgeItem.meta["space_id"].astext == str(space_id))
            items = (await session.scalars(query)).all()
            issue_cache: dict[str, dict | None] = {}
            for item in items:
                keys = sorted(set(_ISSUE_KEY_RE.findall(item.content or "")))[:10]
                if not keys or not item.source_updated_at:
                    continue
                pages_checked += 1
                for key in keys:
                    if key not in issue_cache:
                        try:
                            issue_cache[key] = await jira.get_issue(key)
                        except Exception:  # noqa: BLE001 - key may not be a real issue
                            issue_cache[key] = None
                    issue = issue_cache[key]
                    if not issue:
                        continue
                    fields = issue.get("fields", {})
                    resolved = fields.get("resolutiondate")
                    if not resolved:
                        continue
                    resolved_at = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                    page_updated = item.source_updated_at
                    if page_updated.tzinfo is None:
                        page_updated = page_updated.replace(tzinfo=UTC)
                    if resolved_at <= page_updated:
                        continue
                    dedupe_key = f"{item.id}:{key}"
                    if await _already_flagged(
                        session, tenant_uuid, FindingType.STALE, "stale_key", dedupe_key
                    ):
                        continue
                    finding = _mk_finding(
                        tenant_uuid,
                        scan_id,
                        FindingType.STALE,
                        f"“{item.title}” may be stale: {key} was resolved after its last edit",
                        (
                            f"The page references Jira issue {key} "
                            f"({fields.get('summary', '')!s}), which was resolved on "
                            f"{resolved_at.date()} — after the page was last updated on "
                            f"{page_updated.date()}. The spec may no longer match reality."
                        ),
                        {
                            "item_id": str(item.id),
                            "stale_key": dedupe_key,
                            "issue_key": key,
                            "issue_status": (fields.get("status") or {}).get("name"),
                            "issue_resolved_at": resolved,
                            "pages": [_page_detail(item)],
                        },
                    )
                    session.add(finding)
                    await session.flush()
                    session.add(
                        FindingEvidence(
                            tenant_id=tenant_uuid,
                            finding_id=finding.id,
                            knowledge_item_id=item.id,
                            excerpt=(
                                f"{key} · {fields.get('summary', '')} · "
                                f"status={(fields.get('status') or {}).get('name')} · "
                                f"resolved {resolved_at.date()}"
                            ),
                            source_label=f"Jira {key}",
                        )
                    )
                    await session.commit()
                    findings_created += 1
    except Exception as exc:  # noqa: BLE001 - recorded on the scan row
        error = str(exc)
        logger.exception("scan.stale_specs.failed", extra={"scan_id": str(scan_id)})

    await _finish_scan(
        session_factory,
        scan_id,
        error,
        {"pages_checked": pages_checked, "findings_created": findings_created},
    )
    return {"scan_id": str(scan_id), "findings_created": findings_created, "error": error}


async def scan_code_doc_drift(
    ctx: dict, tenant_id: str, post_comments: bool = False, space_id: str | None = None
) -> dict[str, Any]:
    """Flag pages linking GitHub files that changed after the page's last update."""
    tenant_uuid = uuid.UUID(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()
    if not GitHubClient.is_configured(settings):
        logger.info("scan.code_doc_drift.skipped", extra={"reason": "github_not_configured"})
        return {"skipped": True, "reason": "GitHub connector not configured"}

    allowed_repos = {
        r.strip().lower() for r in (settings.github_repos or "").split(",") if r.strip()
    }
    scan_id = await _start_scan(
        session_factory, tenant_uuid, "code_doc_drift", post_comments, space_id
    )
    findings_created = 0
    links_checked = 0
    error: str | None = None
    try:
        async with session_factory() as session, GitHubClient.from_settings(settings) as gh:
            query = select(KnowledgeItem).where(
                KnowledgeItem.tenant_id == tenant_uuid,
                KnowledgeItem.source_type == SourceType.CONFLUENCE,
            )
            if space_id:
                query = query.where(KnowledgeItem.meta["space_id"].astext == str(space_id))
            items = (await session.scalars(query)).all()
            for item in items:
                if not item.source_updated_at:
                    continue
                matches = _GITHUB_FILE_RE.findall(item.content or "")[:10]
                for owner, repo, _ref, path in matches:
                    if allowed_repos and f"{owner}/{repo}".lower() not in allowed_repos:
                        continue
                    links_checked += 1
                    try:
                        commit = await gh.get_last_commit(owner, repo, path)
                    except Exception:  # noqa: BLE001 - stale link / no access
                        continue
                    if not commit:
                        continue
                    commit_date_raw = ((commit.get("commit") or {}).get("committer") or {}).get(
                        "date"
                    )
                    if not commit_date_raw:
                        continue
                    commit_date = datetime.fromisoformat(commit_date_raw.replace("Z", "+00:00"))
                    page_updated = item.source_updated_at
                    if page_updated.tzinfo is None:
                        page_updated = page_updated.replace(tzinfo=UTC)
                    if commit_date <= page_updated:
                        continue
                    dedupe_key = f"{item.id}:{owner}/{repo}/{path}"
                    if await _already_flagged(
                        session, tenant_uuid, FindingType.CODE_DOC_DRIFT, "drift_key", dedupe_key
                    ):
                        continue
                    finding = _mk_finding(
                        tenant_uuid,
                        scan_id,
                        FindingType.CODE_DOC_DRIFT,
                        f"“{item.title}” may lag the code: {path} changed after its last edit",
                        (
                            f"The page links to {owner}/{repo}/{path}, last changed on "
                            f"{commit_date.date()} — after the page was last updated on "
                            f"{page_updated.date()}. The documentation may no longer "
                            "describe the current code."
                        ),
                        {
                            "item_id": str(item.id),
                            "drift_key": dedupe_key,
                            "repo": f"{owner}/{repo}",
                            "path": path,
                            "code_changed_at": commit_date_raw,
                            "commit_sha": commit.get("sha"),
                            "pages": [_page_detail(item)],
                        },
                    )
                    session.add(finding)
                    await session.flush()
                    session.add(
                        FindingEvidence(
                            tenant_id=tenant_uuid,
                            finding_id=finding.id,
                            knowledge_item_id=item.id,
                            excerpt=(
                                f"{owner}/{repo}/{path} · commit {commit.get('sha', '')[:8]} · "
                                f"{(commit.get('commit') or {}).get('message', '')[:120]}"
                            ),
                            source_label=f"GitHub {owner}/{repo}",
                        )
                    )
                    await session.commit()
                    findings_created += 1
    except Exception as exc:  # noqa: BLE001 - recorded on the scan row
        error = str(exc)
        logger.exception("scan.code_doc_drift.failed", extra={"scan_id": str(scan_id)})

    await _finish_scan(
        session_factory,
        scan_id,
        error,
        {"links_checked": links_checked, "findings_created": findings_created},
    )
    return {"scan_id": str(scan_id), "findings_created": findings_created, "error": error}


async def scan_tribal_knowledge(
    ctx: dict, tenant_id: str, post_comments: bool = False, space_id: str | None = None
) -> dict[str, Any]:
    """Flag Slack threads containing decisions that are not documented anywhere.

    Deterministic pipeline: decision-language filter → embed thread → pgvector
    nearest-neighbour against the doc corpus → flag if nothing similar exists.
    """
    tenant_uuid = uuid.UUID(tenant_id)
    settings = get_settings()
    session_factory = get_session_factory()
    channels = [c.strip() for c in (settings.slack_channels or "").split(",") if c.strip()]
    if not SlackClient.is_configured(settings) or not channels:
        logger.info("scan.tribal_knowledge.skipped", extra={"reason": "slack_not_configured"})
        return {"skipped": True, "reason": "Slack connector or channels not configured"}

    scan_id = await _start_scan(
        session_factory, tenant_uuid, "tribal_knowledge", post_comments, space_id
    )
    router = LLMRouter()
    findings_created = 0
    threads_checked = 0
    error: str | None = None
    try:
        async with session_factory() as session, SlackClient.from_settings(settings) as slack:
            for channel in channels:
                history = await slack.channel_history(channel, limit=100)
                for msg in history.get("messages", []):
                    if not _DECISION_RE.search(msg.get("text", "")):
                        continue
                    ts = msg["ts"]
                    thread_text = msg.get("text", "")
                    if msg.get("reply_count"):
                        replies = await slack.thread_replies(channel, ts)
                        thread_text = "\n".join(
                            r.get("text", "") for r in replies.get("messages", [])
                        )
                    threads_checked += 1
                    dedupe_key = f"{channel}:{ts}"
                    if await _already_flagged(
                        session,
                        tenant_uuid,
                        FindingType.UNDOCUMENTED_DECISION,
                        "thread_key",
                        dedupe_key,
                    ):
                        continue
                    vectors = await router.embed([thread_text[:20_000]])
                    row = (
                        await session.execute(
                            text(
                                """
                                SELECT title, embedding <=> CAST(:vec AS vector) AS distance
                                FROM knowledge_item
                                WHERE tenant_id = :tenant AND embedding IS NOT NULL
                                ORDER BY distance LIMIT 1
                                """
                            ),
                            {"vec": str(vectors[0]), "tenant": str(tenant_uuid)},
                        )
                    ).first()
                    if row is not None and row.distance < TRIBAL_DISTANCE_THRESHOLD:
                        continue  # something similar is already documented
                    excerpt = msg.get("text", "")[:400]
                    finding = _mk_finding(
                        tenant_uuid,
                        scan_id,
                        FindingType.UNDOCUMENTED_DECISION,
                        "Decision made in Slack is not documented",
                        (
                            "A decision was discussed in Slack but no similar content "
                            "exists in the documentation corpus. Consider capturing it "
                            "on a Confluence page."
                        ),
                        {
                            "thread_key": dedupe_key,
                            "channel": channel,
                            "ts": ts,
                            "nearest_doc": row.title if row is not None else None,
                            "nearest_distance": float(row.distance) if row is not None else None,
                        },
                    )
                    session.add(finding)
                    await session.flush()
                    session.add(
                        FindingEvidence(
                            tenant_id=tenant_uuid,
                            finding_id=finding.id,
                            knowledge_item_id=None,
                            excerpt=excerpt,
                            source_label=f"Slack {channel}",
                        )
                    )
                    await session.commit()
                    findings_created += 1
    except Exception as exc:  # noqa: BLE001 - recorded on the scan row
        error = str(exc)
        logger.exception("scan.tribal_knowledge.failed", extra={"scan_id": str(scan_id)})

    await _finish_scan(
        session_factory,
        scan_id,
        error,
        {"threads_checked": threads_checked, "findings_created": findings_created},
    )
    return {"scan_id": str(scan_id), "findings_created": findings_created, "error": error}
