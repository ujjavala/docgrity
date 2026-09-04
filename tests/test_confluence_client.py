"""Tests for the Confluence REST client using a mocked httpx transport."""

import httpx
import pytest

from docgrity.mcp.confluence.client import ConfluenceClient, ConfluenceError


def make_client(handler) -> ConfluenceClient:
    client = ConfluenceClient("https://example.atlassian.net", "dev@example.com", "token")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.atlassian.net",
    )
    return client


async def test_get_page():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/wiki/api/v2/pages/123"
        assert request.url.params["body-format"] == "storage"
        return httpx.Response(200, json={"id": "123", "title": "Deploy guide"})

    async with make_client(handler) as client:
        page = await client.get_page("123")
    assert page["title"] == "Deploy guide"


async def test_search_cql():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/wiki/rest/api/search"
        assert "type=page" in request.url.params["cql"]
        return httpx.Response(200, json={"results": [{"content": {"id": "1"}}]})

    async with make_client(handler) as client:
        result = await client.search_cql("type=page")
    assert len(result["results"]) == 1


async def test_add_footer_comment_posts_storage_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/wiki/api/v2/footer-comments"
        return httpx.Response(201, json={"id": "c1"})

    async with make_client(handler) as client:
        comment = await client.add_footer_comment("123", "<p>🤖 Docgrity</p>")
    assert comment["id"] == "c1"


async def test_error_raises_confluence_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="page not found")

    async with make_client(handler) as client:
        with pytest.raises(ConfluenceError) as exc_info:
            await client.get_page("999")
    assert exc_info.value.status_code == 404
