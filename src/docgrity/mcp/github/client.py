"""Async GitHub REST client (repo read access for code-to-doc drift checks).

Only the GitHub MCP server and deterministic checks may use this; agents go
through MCP tools.
"""

from __future__ import annotations

from typing import Any

import httpx

from docgrity.mcp.confluence.client import TokenBucket


class GitHubError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"GitHub API error {status_code}: {message}")


class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        if not token:
            raise ValueError("GITHUB_CONNECTOR_TOKEN is not configured.")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._bucket = TokenBucket(rate=5.0, capacity=10)

    @classmethod
    def from_settings(cls, settings) -> GitHubClient:
        return cls(settings.github_connector_token, settings.github_api_base_url)

    @classmethod
    def is_configured(cls, settings) -> bool:
        return bool(settings.github_connector_token)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _get(self, path: str, **params: Any) -> Any:
        await self._bucket.acquire()
        response = await self._client.get(path, params={k: v for k, v in params.items() if v})
        if response.status_code >= 400:
            raise GitHubError(response.status_code, response.text[:500])
        return response.json()

    async def get_last_commit(self, owner: str, repo: str, path: str) -> dict[str, Any] | None:
        """Most recent commit touching a path (None if the path has no commits)."""
        commits = await self._get(f"/repos/{owner}/{repo}/commits", path=path, per_page=1)
        return commits[0] if commits else None

    async def get_file(self, owner: str, repo: str, path: str, ref: str | None = None) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/contents/{path}", ref=ref)
