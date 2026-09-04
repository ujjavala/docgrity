"""Health and readiness endpoints."""

from fastapi import APIRouter
from sqlalchemy import text

from docgrity import __version__
from docgrity.core.db import get_session_factory

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/health/ready")
async def ready() -> dict:
    """Readiness: verifies database connectivity."""
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}
