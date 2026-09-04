"""Security-focused tests: auth hardening, tenant isolation, headers, input limits."""

import hashlib
import secrets
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
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _make_tenant(api_key: str | None = None) -> Tenant:
    factory = get_session_factory()
    async with factory() as session:
        tenant = Tenant(name=f"sec-{uuid.uuid4().hex[:8]}")
        if api_key:
            tenant.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        session.add(tenant)
        await session.commit()
        return tenant


def dev_headers(tenant_id) -> dict:
    return {"X-API-Key": get_settings().api_secret_key, "X-Tenant-Id": str(tenant_id)}


# --- authentication -------------------------------------------------------


async def test_wrong_api_key_rejected(client):
    response = await client.get(
        "/api/v1/findings",
        headers={"X-API-Key": "definitely-wrong", "X-Tenant-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 401


async def test_malformed_tenant_id_is_400_not_500(client):
    response = await client.get(
        "/api/v1/findings",
        headers={"X-API-Key": get_settings().api_secret_key, "X-Tenant-Id": "not-a-uuid"},
    )
    assert response.status_code == 400


async def test_missing_tenant_id_is_400(client):
    response = await client.get(
        "/api/v1/findings", headers={"X-API-Key": get_settings().api_secret_key}
    )
    assert response.status_code == 400


async def test_garbage_bearer_token_rejected(client):
    response = await client.get("/api/v1/findings", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


async def test_tenant_api_key_authenticates_scoped_tenant(client):
    api_key = f"dgk_{secrets.token_urlsafe(32)}"
    tenant = await _make_tenant(api_key)
    response = await client.get("/api/v1/findings", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json() == []
    # Wrong key of same shape does not authenticate.
    bad = await client.get(
        "/api/v1/findings", headers={"X-API-Key": f"dgk_{secrets.token_urlsafe(32)}"}
    )
    assert bad.status_code == 401
    assert tenant.id is not None


# --- tenant isolation -----------------------------------------------------


async def test_findings_are_tenant_isolated(client):
    tenant_a = await _make_tenant()
    tenant_b = await _make_tenant()
    factory = get_session_factory()
    async with factory() as session:
        finding = Finding(
            tenant_id=tenant_a.id,
            type=FindingType.DUPLICATE,
            severity=FindingSeverity.MEDIUM,
            status=FindingStatus.NEW,
            title="A-only finding",
            summary="Visible only to tenant A.",
            confidence=0.9,
            detail={},
        )
        session.add(finding)
        await session.commit()
        finding_id = str(finding.id)

    # Tenant B cannot list or fetch tenant A's finding.
    listed = await client.get("/api/v1/findings", headers=dev_headers(tenant_b.id))
    assert finding_id not in [f["id"] for f in listed.json()]
    detail = await client.get(f"/api/v1/findings/{finding_id}", headers=dev_headers(tenant_b.id))
    assert detail.status_code == 404
    # Nor mutate its status.
    mutate = await client.post(
        f"/api/v1/findings/{finding_id}/status",
        headers=dev_headers(tenant_b.id),
        json={"status": "DISMISSED"},
    )
    assert mutate.status_code == 404


async def test_scans_are_tenant_isolated(client):
    tenant_a = await _make_tenant()
    tenant_b = await _make_tenant()
    from docgrity.core.enums import ScanStatus
    from docgrity.core.models import Scan

    factory = get_session_factory()
    async with factory() as session:
        scan = Scan(tenant_id=tenant_a.id, status=ScanStatus.COMPLETED, checks=["duplicates"])
        session.add(scan)
        await session.commit()
        scan_id = str(scan.id)

    response = await client.get(f"/api/v1/scans/{scan_id}", headers=dev_headers(tenant_b.id))
    assert response.status_code == 404


# --- input validation -----------------------------------------------------


async def test_limit_bounds_enforced(client):
    tenant = await _make_tenant()
    for bad in ("-5", "0", "9999", "abc"):
        response = await client.get(f"/api/v1/findings?limit={bad}", headers=dev_headers(tenant.id))
        assert response.status_code == 422, bad


async def test_manual_status_cannot_set_agent_states(client):
    tenant = await _make_tenant()
    factory = get_session_factory()
    async with factory() as session:
        finding = Finding(
            tenant_id=tenant.id,
            type=FindingType.DUPLICATE,
            severity=FindingSeverity.LOW,
            status=FindingStatus.NEW,
            title="t",
            summary="s",
            confidence=0.8,
            detail={},
        )
        session.add(finding)
        await session.commit()
        finding_id = str(finding.id)

    response = await client.post(
        f"/api/v1/findings/{finding_id}/status",
        headers=dev_headers(tenant.id),
        json={"status": "NEW"},
    )
    assert response.status_code == 400


# --- security headers -----------------------------------------------------


async def test_security_headers_present(client):
    response = await client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]


# --- hosted MCP endpoint --------------------------------------------------


async def test_mcp_requires_bearer(client):
    response = await client.post("/mcp/mcp", json={})
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


async def test_mcp_rejects_unknown_key(client):
    response = await client.post(
        "/mcp/mcp",
        headers={"Authorization": f"Bearer dgk_{secrets.token_urlsafe(32)}"},
        json={},
    )
    assert response.status_code == 401
