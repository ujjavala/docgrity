"""Docgrity API entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from docgrity import __version__
from docgrity.api.mcp_remote import build_mcp_asgi_app
from docgrity.api.routes import findings, health, scans, spaces
from docgrity.core.config import get_settings
from docgrity.core.logging import setup_logging
from docgrity.mcp.docgrity.server import mcp

setup_logging(get_settings().log_level)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # The mounted MCP streamable-HTTP app needs its session manager running.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Docgrity", version=__version__, lifespan=_lifespan)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


app.include_router(health.router)
app.include_router(scans.router)
app.include_router(findings.router)
app.include_router(spaces.router)

# Hosted MCP endpoint — bring-your-own-agent surface (VS Code, Claude, Cursor, ...).
app.mount("/mcp", build_mcp_asgi_app())
