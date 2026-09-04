"""Tests for the ingestion pipeline (text extraction, upsert, embedding)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from docgrity.core.enums import LLMCapability
from docgrity.core.llm.router import LLMRouter, ModelRoute
from docgrity.ingestion.confluence import ConfluenceIngestor, _next_cursor, content_hash
from docgrity.ingestion.text import storage_html_to_text


def test_storage_html_to_text():
    html = "<h1>Deploy guide</h1><p>Step  one.</p><ul><li>Item A</li><li>Item B</li></ul>"
    text = storage_html_to_text(html)
    assert text == "Deploy guide\nStep one.\nItem A\nItem B"


def test_content_hash_stable_and_sensitive():
    assert content_hash("t", "body") == content_hash("t", "body")
    assert content_hash("t", "body") != content_hash("t", "body2")


def test_next_cursor_parsing():
    batch = {"_links": {"next": "/wiki/api/v2/spaces/1/pages?cursor=abc123&limit=50"}}
    assert _next_cursor(batch) == "abc123"
    assert _next_cursor({}) is None


def make_page(page_id: str, title: str, body: str, version: int = 1) -> dict:
    return {
        "id": page_id,
        "title": title,
        "spaceId": "s1",
        "body": {"storage": {"value": body}},
        "version": {"number": version, "createdAt": "2026-09-01T00:00:00Z", "authorId": "acc-1"},
        "_links": {"webui": f"/pages/{page_id}"},
    }


class FakeRouter:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.0] * 1536 for _ in texts]


@pytest.fixture
def ingestor_env():
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.scalars = AsyncMock(return_value=iter(()))  # no existing chunks
    session.add = lambda obj: None
    client = AsyncMock()
    router = FakeRouter()
    ingestor = ConfluenceIngestor(
        session=session,
        client=client,
        router=router,
        tenant_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
    )
    return ingestor, session, client, router


async def test_ingest_space_creates_and_embeds(ingestor_env):
    ingestor, session, client, router = ingestor_env
    client.list_pages_in_space = AsyncMock(
        return_value={"results": [make_page("1", "A", "<p>hello</p>")]}
    )
    stats = await ingestor.ingest_space("s1")
    assert stats.pages_seen == 1
    assert stats.created == 1
    assert stats.embedded == 1
    assert router.calls == 2  # item-level embed + chunk embed batch
    session.commit.assert_awaited()


async def test_ingest_space_skips_unchanged(ingestor_env):
    ingestor, session, client, router = ingestor_env
    page = make_page("1", "A", "<p>hello</p>")
    existing = AsyncMock()
    existing.content_hash = content_hash("A", "hello")
    existing.meta = {}
    session.scalar = AsyncMock(return_value=existing)
    client.list_pages_in_space = AsyncMock(return_value={"results": [page]})
    stats = await ingestor.ingest_space("s1")
    assert stats.unchanged == 1
    assert stats.embedded == 0
    assert router.calls == 0


def test_router_resolves_capabilities():
    router = LLMRouter(
        routes={LLMCapability.EMBEDDING: ModelRoute("openai", "text-embedding-3-small")}
    )
    route = router.resolve(LLMCapability.EMBEDDING)
    assert route.provider == "openai"
    with pytest.raises(ValueError):
        router.resolve(LLMCapability.REASONING_HIGH)
