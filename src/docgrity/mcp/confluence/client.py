"""Async Confluence Cloud REST client (v2 API, CQL search via v1).

Auth modes (Marketplace security requirement: no basic auth for listed apps):
- Bearer token (OAuth 2.0 3LO or Forge-mediated access token) — production.
- Email + API token basic auth — local development only.

Credentials come from Settings / secrets manager — never hardcoded.

This client is only ever called by the Confluence MCP server; agents must not
import it directly (architectural principle: external systems via MCP only).
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx


class TokenBucket:
    """Deterministic async token-bucket rate limiter.

    Defaults to 10 req/s with a burst of 20 — well inside Confluence Cloud
    per-connector limits. Purely deterministic (no LLM involvement).
    """

    def __init__(self, rate: float = 10.0, capacity: int = 20) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._rate)


class ConfluenceError(Exception):
    """Raised when the Confluence API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Confluence API error {status_code}: {message}")


class ConfluenceClient:
    """Thin async wrapper over the Confluence Cloud REST API."""

    def __init__(
        self,
        base_url: str,
        email: str | None = None,
        api_token: str | None = None,
        access_token: str | None = None,
    ) -> None:
        # base_url: https://your-site.atlassian.net (basic auth) or
        # https://api.atlassian.com/ex/confluence/<cloudId> (OAuth/Forge bearer).
        self._base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        auth: tuple[str, str] | None = None
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif email and api_token:
            auth = (email, api_token)
        else:
            raise ValueError("Provide either access_token or email + api_token.")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=auth,
            headers=headers,
            timeout=30.0,
        )
        self._bucket = TokenBucket()

    async def close(self) -> None:
        await self._client.aclose()

    @classmethod
    def from_settings(cls, settings) -> ConfluenceClient:
        """Build a client from app settings, preferring bearer auth over basic auth."""
        if not settings.confluence_base_url:
            raise ValueError("CONFLUENCE_BASE_URL is not configured.")
        if settings.confluence_access_token:
            return cls(
                base_url=settings.confluence_base_url,
                access_token=settings.confluence_access_token,
            )
        return cls(
            base_url=settings.confluence_base_url,
            email=settings.confluence_email,
            api_token=settings.confluence_api_token,
        )

    async def __aenter__(self) -> ConfluenceClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    _MAX_RETRIES = 4

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(self._MAX_RETRIES + 1):
            await self._bucket.acquire()
            response = await self._client.request(method, path, **kwargs)
            if response.status_code == 429 and attempt < self._MAX_RETRIES:
                # Honour Retry-After when present; otherwise exponential backoff + jitter.
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = min(2.0**attempt, 30.0) + random.uniform(0, 0.5)  # noqa: S311
                await asyncio.sleep(delay)
                continue
            break
        if response.status_code >= 400:
            raise ConfluenceError(response.status_code, response.text[:500])
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    # -- spaces ------------------------------------------------------------

    async def list_spaces(self, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/wiki/api/v2/spaces", params=params)

    # -- pages -------------------------------------------------------------

    async def list_pages_in_space(
        self, space_id: str, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "body-format": "storage"}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", f"/wiki/api/v2/spaces/{space_id}/pages", params=params)

    async def get_page(self, page_id: str, body_format: str = "storage") -> dict[str, Any]:
        return await self._request(
            "GET", f"/wiki/api/v2/pages/{page_id}", params={"body-format": body_format}
        )

    async def update_page(
        self,
        page_id: str,
        title: str,
        body_storage: str,
        version_number: int,
        message: str = "Updated by Docgrity (human-approved)",
    ) -> dict[str, Any]:
        """Update a page body/title. Caller must supply the next version number."""
        payload = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": body_storage},
            "version": {"number": version_number, "message": message},
        }
        return await self._request("PUT", f"/wiki/api/v2/pages/{page_id}", json=payload)

    async def archive_page(self, page_id: str) -> dict[str, Any]:
        """Archive a page (v1 bulk-archive endpoint; v2 has no archive yet)."""
        return await self._request(
            "POST", "/wiki/rest/api/content/archive", json={"pages": [{"id": page_id}]}
        )

    async def get_page_children(
        self, page_id: str, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", f"/wiki/api/v2/pages/{page_id}/children", params=params)

    async def get_page_versions(
        self, page_id: str, limit: int = 25, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", f"/wiki/api/v2/pages/{page_id}/versions", params=params)

    # -- comments ----------------------------------------------------------

    async def get_page_comments(
        self, page_id: str, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "body-format": "storage"}
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET", f"/wiki/api/v2/pages/{page_id}/footer-comments", params=params
        )

    async def add_footer_comment(self, page_id: str, body_storage: str) -> dict[str, Any]:
        payload = {
            "pageId": page_id,
            "body": {"representation": "storage", "value": body_storage},
        }
        return await self._request("POST", "/wiki/api/v2/footer-comments", json=payload)

    async def resolve_comment(self, comment_id: str) -> dict[str, Any]:
        # v2 has no dedicated resolve endpoint; deletion of our own bot comment
        # is the MVP resolution path and requires policy approval upstream.
        return await self._request("DELETE", f"/wiki/api/v2/footer-comments/{comment_id}")

    # -- search (CQL, v1 API) ------------------------------------------------

    async def search_cql(self, cql: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/wiki/rest/api/search",
            params={"cql": cql, "limit": limit, "start": start},
        )

    # -- users ---------------------------------------------------------------

    async def get_user(self, account_id: str) -> dict[str, Any]:
        return await self._request("GET", "/wiki/rest/api/user", params={"accountId": account_id})
