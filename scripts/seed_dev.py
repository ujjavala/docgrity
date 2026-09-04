"""Seed local dev data: tenant for the Forge demo site + Confluence source/scope.

Usage: uv run python scripts/seed_dev.py
Idempotent — safe to re-run.
"""

import asyncio

from sqlalchemy import select

from docgrity.core.config import get_settings
from docgrity.core.db import get_session_factory
from docgrity.core.enums import SourceType
from docgrity.core.models import Source, SourceScope, Tenant
from docgrity.mcp.confluence.client import ConfluenceClient

CLOUD_ID = "1ad016a6-f17b-4ec3-b1a7-ac5f178cc3a3"  # one-atlas-nbtc.atlassian.net
TENANT_NAME = "one-atlas-nbtc (dev)"


async def main() -> None:
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.atlassian_cloud_id == CLOUD_ID))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(name=TENANT_NAME, atlassian_cloud_id=CLOUD_ID)
            session.add(tenant)
            await session.flush()
        print(f"tenant: {tenant.id}")

        source = (
            await session.execute(
                select(Source).where(
                    Source.tenant_id == tenant.id, Source.type == SourceType.CONFLUENCE
                )
            )
        ).scalar_one_or_none()
        if source is None:
            source = Source(
                tenant_id=tenant.id, type=SourceType.CONFLUENCE, name="demo-site", enabled=True
            )
            session.add(source)
            await session.flush()
        print(f"source: {source.id}")

        # Add every space on the site as an enabled scope (dev convenience).
        # external_id must be the numeric space id (required by the v2 pages API);
        # the human-readable key goes in name.
        if settings.confluence_api_token or settings.confluence_access_token:
            client = ConfluenceClient.from_settings(settings)
            spaces = await client.list_spaces()
            for space in spaces.get("results", []):
                space_id = str(space["id"])
                key = space.get("key") or space_id
                existing = (
                    await session.execute(
                        select(SourceScope).where(
                            SourceScope.source_id == source.id,
                            SourceScope.external_id == space_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        SourceScope(
                            tenant_id=tenant.id,
                            source_id=source.id,
                            external_id=space_id,
                            name=space.get("name", key),
                            enabled=True,
                        )
                    )
                    print(f"scope added: {key} ({space_id})")
            await client.close()
        else:
            print("no Confluence credentials in .env — skipped scope discovery")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
