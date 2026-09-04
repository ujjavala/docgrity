"""API tests for scans/findings using dev auth and the compose Postgres."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from docgrity.api.main import app
from docgrity.core.config import get_settings
from docgrity.core.db import get_session_factory
from docgrity.core.enums import FindingSeverity, FindingStatus, FindingType
from docgrity.core.models import Finding, Tenant

pytestmark = pytest.mark.integration


@pytest.fixture
async def tenant_id():
    factory = get_session_factory()
    async with factory() as session:
        tenant = Tenant(name=f"test-{uuid.uuid4().hex[:8]}")
        session.add(tenant)
        await session.commit()
        return str(tenant.id)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def headers(tenant_id: str) -> dict:
    return {"X-API-Key": get_settings().api_secret_key, "X-Tenant-Id": tenant_id}


async def test_unauthenticated_rejected(client):
    response = await client.get("/api/v1/findings")
    assert response.status_code == 401


async def test_list_findings_empty(client, tenant_id):
    response = await client.get("/api/v1/findings", headers=headers(tenant_id))
    assert response.status_code == 200
    assert response.json() == []


async def test_finding_lifecycle(client, tenant_id):
    factory = get_session_factory()
    async with factory() as session:
        finding = Finding(
            tenant_id=uuid.UUID(tenant_id),
            type=FindingType.DUPLICATE,
            severity=FindingSeverity.MEDIUM,
            status=FindingStatus.NEW,
            title="Possible duplicate",
            summary="Two deploy guides overlap.",
            confidence=0.9,
            detail={"item_a_id": "a", "item_b_id": "b"},
        )
        session.add(finding)
        await session.commit()
        finding_id = str(finding.id)

    listed = await client.get("/api/v1/findings", headers=headers(tenant_id))
    assert [f["id"] for f in listed.json()] == [finding_id]

    detail = await client.get(f"/api/v1/findings/{finding_id}", headers=headers(tenant_id))
    assert detail.status_code == 200
    assert detail.json()["evidence"] == []

    # Manual transition to an allowed status
    updated = await client.post(
        f"/api/v1/findings/{finding_id}/status",
        headers=headers(tenant_id),
        json={"status": "DISMISSED"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "DISMISSED"

    # Disallowed manual status
    bad = await client.post(
        f"/api/v1/findings/{finding_id}/status",
        headers=headers(tenant_id),
        json={"status": "INVESTIGATING"},
    )
    assert bad.status_code == 400


async def test_tenant_isolation(client, tenant_id):
    other_headers = headers(str(uuid.uuid4()))
    response = await client.get("/api/v1/findings", headers=other_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_scan_requires_source_for_ingest(client, tenant_id):
    response = await client.post(
        "/api/v1/scans", headers=headers(tenant_id), json={"checks": ["ingest"]}
    )
    assert response.status_code == 400
