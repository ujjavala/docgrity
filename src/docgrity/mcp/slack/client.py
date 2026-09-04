"""Async Slack Web API client (bot token; read-only in MVP).

Required bot scopes: channels:read, channels:history. Message posting is
policy-gated in the MCP server. Only the Slack MCP server and deterministic
checks may use this; agents go through MCP tools.
"""

from __future__ import annotations

from typing import Any

import httpx

from docgrity.mcp.confluence.client import TokenBucket


class SlackError(Exception):
    pass


class SlackClient:
    def __init__(self, bot_token: str) -> None:
        if not bot_token:
            raise ValueError("SLACK_BOT_TOKEN is not configured.")
        self._client = httpx.AsyncClient(
            base_url="https://slack.com/api",
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=30.0,
        )
        self._bucket = TokenBucket(rate=1.0, capacity=3)  # Slack tier-3 ≈ 50/min

    @classmethod
    def from_settings(cls, settings) -> SlackClient:
        return cls(settings.slack_bot_token)

    @classmethod
    def is_configured(cls, settings) -> bool:
        return bool(settings.slack_bot_token)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SlackClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _call(self, method: str, **params: Any) -> dict[str, Any]:
        await self._bucket.acquire()
        response = await self._client.get(
            f"/{method}", params={k: v for k, v in params.items() if v is not None}
        )
        data = response.json()
        if not data.get("ok"):
            raise SlackError(f"Slack API {method} failed: {data.get('error')}")
        return data

    async def channel_history(
        self, channel: str, limit: int = 100, oldest: str | None = None
    ) -> dict[str, Any]:
        return await self._call(
            "conversations.history", channel=channel, limit=limit, oldest=oldest
        )

    async def thread_replies(self, channel: str, ts: str, limit: int = 50) -> dict[str, Any]:
        return await self._call("conversations.replies", channel=channel, ts=ts, limit=limit)

    async def list_channels(self, limit: int = 100) -> dict[str, Any]:
        return await self._call("conversations.list", limit=limit, exclude_archived=True)
