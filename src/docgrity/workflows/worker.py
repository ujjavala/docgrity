"""arq worker settings. Scan/ingestion tasks register here."""

from arq.connections import RedisSettings

from docgrity.core.config import get_settings
from docgrity.core.logging import setup_logging
from docgrity.workflows.checks_cross import (
    scan_code_doc_drift,
    scan_stale_specs,
    scan_tribal_knowledge,
)
from docgrity.workflows.ingest import ingest_confluence_source
from docgrity.workflows.scan import (
    notify_owner,
    scan_contradictions,
    scan_duplicates,
    scan_open_questions,
)

setup_logging(get_settings().log_level)


async def ping(ctx: dict) -> str:
    """Trivial task proving the worker processes jobs."""
    return "pong"


class WorkerSettings:
    functions = [
        ping,
        ingest_confluence_source,
        notify_owner,
        scan_duplicates,
        scan_contradictions,
        scan_open_questions,
        scan_stale_specs,
        scan_code_doc_drift,
        scan_tribal_knowledge,
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Full-source ingests embed hundreds of pages; the arq default (300s) is too short.
    job_timeout = 3600
