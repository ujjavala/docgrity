"""Async Jira Cloud REST client (v3 API).

Reuses the Atlassian site credentials configured for Confluence unless a
dedicated JIRA_BASE_URL is set. Read-only in MVP; issue creation is
policy-gated in the MCP server. Only the Jira MCP server may import this —
agents access Jira via MCP tools only.
"""

from __future__ import annotations

from typing import Any

import httpx

from docgrity.mcp.confluence.client import TokenBucket


class JiraError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Jira API error {status_code}: {message}")


class JiraClient:
    """Thin async wrapper over the Jira Cloud REST API v3."""

    def __init__(
        self,
        base_url: str,
        email: str | None = None,
        api_token: str | None = None,
        access_token: str | None = None,
    ) -> None:
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
            base_url=self._base_url, auth=auth, headers=headers, timeout=30.0
        )
        self._bucket = TokenBucket()

    @classmethod
    def from_settings(cls, settings) -> JiraClient:
        base = settings.jira_base_url or settings.confluence_base_url
        if not base:
            raise ValueError("JIRA_BASE_URL / CONFLUENCE_BASE_URL is not configured.")
        if settings.confluence_access_token:
            return cls(base_url=base, access_token=settings.confluence_access_token)
        return cls(
            base_url=base,
            email=settings.confluence_email,
            api_token=settings.confluence_api_token,
        )

    @classmethod
    def is_configured(cls, settings) -> bool:
        base = settings.jira_base_url or settings.confluence_base_url
        return bool(
            base
            and (
                settings.confluence_access_token
                or (settings.confluence_email and settings.confluence_api_token)
            )
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> JiraClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        await self._bucket.acquire()
        response = await self._client.get(path, params={k: v for k, v in params.items() if v})
        if response.status_code >= 400:
            raise JiraError(response.status_code, response.text[:500])
        return response.json()

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Fetch an issue: status, resolution, dates, summary."""
        return await self._get(
            f"/rest/api/3/issue/{issue_key}",
            fields="summary,status,resolution,resolutiondate,updated,assignee",
        )

    async def search(self, jql: str, max_results: int = 25) -> dict[str, Any]:
        return await self._get(
            "/rest/api/3/search/jql",
            jql=jql,
            maxResults=max_results,
            fields="summary,status,resolutiondate,updated",
        )
