"""Confluence space listing for the dashboard space picker."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from docgrity.api.auth import AuthContext, get_auth
from docgrity.core.config import get_settings
from docgrity.mcp.confluence.client import ConfluenceClient

router = APIRouter(prefix="/api/v1/spaces", tags=["spaces"])


@router.get("")
async def list_spaces(auth: AuthContext = Depends(get_auth)) -> list[dict]:
    """List Confluence spaces the connector can see (id, key, name)."""
    settings = get_settings()
    async with ConfluenceClient.from_settings(settings) as client:
        data = await client.list_spaces(limit=100)
    return [
        {"id": str(s.get("id")), "key": s.get("key"), "name": s.get("name")}
        for s in data.get("results", [])
    ]
