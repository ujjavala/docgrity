"""Confluence → knowledge_item ingestion.

Deterministic connector-layer code (no LLM reasoning): walks configured spaces,
extracts text, hashes content, upserts knowledge items, records versions, and
embeds new/changed content via the capability router.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docgrity.core.config import get_settings
from docgrity.core.enums import KnowledgeItemType, SourceType
from docgrity.core.llm import LLMRouter
from docgrity.core.models import KnowledgeItem, KnowledgeItemChunk, KnowledgeItemVersion
from docgrity.ingestion.text import split_into_chunks, storage_html_to_text
from docgrity.mcp.confluence.client import ConfluenceClient

# Character cap for embedding input (~8k tokens for text-embedding-3-small).
EMBED_CHAR_LIMIT = 20_000


def page_web_url(webui_path: str | None) -> str | None:
    """Build an absolute Confluence page URL from a stored `_links.webui` path.

    Handles: relative paths (`/spaces/...`), paths already carrying `/wiki`,
    and absolute URLs that are missing the `/wiki` prefix.
    """
    if not webui_path:
        return None
    if webui_path.startswith("http"):
        parsed = urlparse(webui_path)
        if parsed.path.startswith("/wiki"):
            return webui_path
        return parsed._replace(path=f"/wiki{parsed.path}").geturl()
    base = get_settings().confluence_base_url.rstrip("/")
    if not base:
        return webui_path
    path = webui_path if webui_path.startswith("/wiki") else f"/wiki{webui_path}"
    return f"{base}{path}"


@dataclass
class IngestStats:
    pages_seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    embedded: int = 0
    errors: list[str] = field(default_factory=list)


def content_hash(title: str, text: str) -> str:
    return hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()


class ConfluenceIngestor:
    def __init__(
        self,
        session: AsyncSession,
        client: ConfluenceClient,
        router: LLMRouter,
        tenant_id: uuid.UUID,
        source_id: uuid.UUID,
    ) -> None:
        self._session = session
        self._client = client
        self._router = router
        self._tenant_id = tenant_id
        self._source_id = source_id

    async def ingest_space(self, space_id: str) -> IngestStats:
        """Ingest all pages in a Confluence space (cursor-paginated)."""
        stats = IngestStats()
        cursor: str | None = None
        while True:
            page_batch = await self._client.list_pages_in_space(space_id, cursor=cursor)
            for page in page_batch.get("results", []):
                try:
                    await self._ingest_page(page, stats)
                except Exception as exc:  # noqa: BLE001 - collected per-page
                    stats.errors.append(f"page {page.get('id')}: {exc}")
            cursor = _next_cursor(page_batch)
            if not cursor:
                break
        await self._session.commit()
        return stats

    async def _ingest_page(self, page: dict, stats: IngestStats) -> None:
        stats.pages_seen += 1
        external_id = str(page["id"])
        title = page.get("title", "")
        html = (page.get("body") or {}).get("storage", {}).get("value", "")
        text = storage_html_to_text(html)
        new_hash = content_hash(title, text)
        version = (page.get("version") or {}).get("number", 1)
        source_updated_at = _parse_ts((page.get("version") or {}).get("createdAt"))
        now = datetime.now(UTC)

        item = await self._session.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.tenant_id == self._tenant_id,
                KnowledgeItem.source_type == SourceType.CONFLUENCE,
                KnowledgeItem.external_id == external_id,
            )
        )

        if item is None:
            item = KnowledgeItem(
                tenant_id=self._tenant_id,
                source_type=SourceType.CONFLUENCE,
                source_id=self._source_id,
                external_id=external_id,
                type=KnowledgeItemType.CONFLUENCE_PAGE,
                title=title,
                content=text,
                url=(page.get("_links") or {}).get("webui"),
                content_hash=new_hash,
                meta={
                    "space_id": page.get("spaceId"),
                    "confluence_version": version,
                    "author_id": page.get("authorId"),
                    "owner_id": page.get("ownerId"),
                },
                source_updated_at=source_updated_at,
                last_scanned_at=now,
            )
            self._session.add(item)
            await self._session.flush()
            self._record_version(item, version, new_hash, page, source_updated_at)
            await self._embed(item, stats)
            stats.created += 1
        elif item.content_hash != new_hash:
            item.title = title
            item.content = text
            item.content_hash = new_hash
            item.url = (page.get("_links") or {}).get("webui") or item.url
            item.meta = {**item.meta, "confluence_version": version}
            item.source_updated_at = source_updated_at
            item.last_scanned_at = now
            self._record_version(item, version, new_hash, page, source_updated_at)
            await self._embed(item, stats)
            stats.updated += 1
        else:
            item.last_scanned_at = now
            if not item.url:  # backfill url for items ingested before url capture
                item.url = (page.get("_links") or {}).get("webui")
            if item.embedding is None:  # backfill after a previously failed embed
                await self._embed(item, stats)
            stats.unchanged += 1

    def _record_version(
        self,
        item: KnowledgeItem,
        version: int,
        new_hash: str,
        page: dict,
        source_updated_at: datetime | None,
    ) -> None:
        self._session.add(
            KnowledgeItemVersion(
                tenant_id=self._tenant_id,
                knowledge_item_id=item.id,
                version=version,
                content_hash=new_hash,
                author_external_id=(page.get("version") or {}).get("authorId"),
                source_updated_at=source_updated_at,
            )
        )

    async def _embed(self, item: KnowledgeItem, stats: IngestStats) -> None:
        text = f"{item.title}\n{item.content}"[:EMBED_CHAR_LIMIT]
        vectors = await self._router.embed([text])
        item.embedding = vectors[0]
        stats.embedded += 1
        await self._sync_chunks(item)

    async def _sync_chunks(self, item: KnowledgeItem) -> None:
        """Upsert semantic chunks; embed only chunks whose content hash changed."""
        chunks = split_into_chunks(item.content)
        existing = {
            c.chunk_index: c
            for c in await self._session.scalars(
                select(KnowledgeItemChunk).where(KnowledgeItemChunk.knowledge_item_id == item.id)
            )
        }
        to_embed: list[tuple[KnowledgeItemChunk, str]] = []
        for idx, content in enumerate(chunks):
            chash = hashlib.sha256(content.encode()).hexdigest()
            row = existing.pop(idx, None)
            if row is not None and row.content_hash == chash and row.embedding is not None:
                continue  # unchanged chunk: skip expensive embedding call
            if row is None:
                row = KnowledgeItemChunk(
                    tenant_id=self._tenant_id,
                    knowledge_item_id=item.id,
                    chunk_index=idx,
                    content=content,
                    content_hash=chash,
                )
                self._session.add(row)
            else:
                row.content = content
                row.content_hash = chash
            to_embed.append((row, content))
        for stale in existing.values():  # chunks past the new end of the page
            await self._session.delete(stale)
        if to_embed:
            vectors = await self._router.embed([c[:EMBED_CHAR_LIMIT] for _, c in to_embed])
            for (row, _), vec in zip(to_embed, vectors, strict=True):
                row.embedding = vec


def _next_cursor(batch: dict) -> str | None:
    next_link = (batch.get("_links") or {}).get("next")
    if not next_link:
        return None
    # v2 next link looks like ...?cursor=<value>&...
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(next_link).query).get("cursor", [None])[0]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
