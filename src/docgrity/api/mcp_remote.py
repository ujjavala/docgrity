"""Hosted MCP transport: mounts the Docgrity MCP server at /mcp.

Users point any MCP-capable agent (VS Code, Claude, Cursor, ...) at
https://<host>/mcp with `Authorization: Bearer <tenant API key>`. The
middleware resolves the key to a tenant and the MCP tools then call the
Docgrity API with that tenant's identity — users bring their own agent;
Docgrity only serves findings and scan control.
"""

from __future__ import annotations

import hashlib
import logging
import os

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from docgrity.core.db import get_session_factory
from docgrity.core.models import Tenant
from docgrity.mcp.docgrity.server import mcp, request_auth

logger = logging.getLogger("docgrity.mcp.remote")


class BearerTenantMiddleware:
    """Resolve `Authorization: Bearer <key>` to a tenant before MCP handling."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request = Request(scope)
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            response = JSONResponse(
                {"error": "unauthorized", "detail": "Bearer tenant API key required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        api_key = authorization.removeprefix("Bearer ")
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        session_factory = get_session_factory()
        async with session_factory() as session:
            tenant = await session.scalar(select(Tenant).where(Tenant.api_key_hash == key_hash))
        if tenant is None:
            client = request.client.host if request.client else None
            logger.warning("mcp.auth_rejected", extra={"client": client})
            response = JSONResponse(
                {"error": "unauthorized", "detail": "Unknown API key"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        token = request_auth.set(
            {
                "api_key": api_key,
                "tenant_id": str(tenant.id),
                "api_url": os.environ.get("DOCGRITY_SELF_URL", "http://localhost:8000"),
            }
        )
        try:
            await self._app(scope, receive, send)
        finally:
            request_auth.reset(token)


def build_mcp_asgi_app() -> ASGIApp:
    """Streamable-HTTP MCP app wrapped with tenant Bearer auth."""
    return BearerTenantMiddleware(mcp.streamable_http_app())
