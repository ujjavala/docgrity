"""API authentication.

Production path: Forge Remote requests carry a Forge Invocation Token (FIT) —
an asymmetric JWT signed by Atlassian. We verify signature (JWKS), audience
(our app id), and expiry, then map the installation's cloudId to a tenant.

Development path: X-API-Key matching settings.api_secret_key plus an explicit
X-Tenant-Id header. Never enabled for Marketplace traffic.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docgrity.core.config import get_settings
from docgrity.core.db import get_session
from docgrity.core.models import Tenant

logger = logging.getLogger("docgrity.auth")

_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True)
class AuthContext:
    tenant_id: uuid.UUID
    subject: str  # "forge:<installation>" or "dev"
    # Forge app system token (x-forge-oauth-system): lets the backend call
    # Confluence *as the app*, so bot comments show as Docgrity, not the user.
    app_token: str | None = None
    cloud_id: str | None = None


def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


async def _auth_forge(
    session: AsyncSession, settings, authorization: str, app_token: str | None = None
) -> AuthContext:
    token = authorization.removeprefix("Bearer ")
    try:
        signing_key = _get_jwks_client(settings.forge_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=[
                settings.forge_app_id,
                f"ari:cloud:ecosystem::app/{settings.forge_app_id}",
            ],
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("auth.forge_token_rejected", extra={"reason": type(exc).__name__})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Forge token") from exc
    cloud_id = (
        (claims.get("context") or {}).get("cloudId", "")
        or (claims.get("app") or {})
        .get("installationContext", "")
        .removeprefix("ari:cloud:confluence::site/")
        or claims.get("cloudId", "")
    )
    if not cloud_id:
        logger.warning("auth.fit_missing_cloud_id", extra={"claim_keys": sorted(claims.keys())})
    tenant = await session.scalar(select(Tenant).where(Tenant.atlassian_cloud_id == cloud_id))
    if tenant is None:
        logger.warning("auth.unknown_installation", extra={"cloud_id": cloud_id})
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unknown installation")
    return AuthContext(
        tenant_id=tenant.id,
        subject=f"forge:{cloud_id}",
        app_token=app_token,
        cloud_id=cloud_id,
    )


async def _auth_tenant_key(session: AsyncSession, x_api_key: str) -> AuthContext | None:
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    tenant = await session.scalar(select(Tenant).where(Tenant.api_key_hash == key_hash))
    if tenant is None:
        return None
    return AuthContext(tenant_id=tenant.id, subject=f"api-key:{tenant.id}")


def _auth_dev(x_tenant_id: str | None) -> AuthContext:
    if not x_tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant-Id header required")
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant-Id must be a UUID") from None
    return AuthContext(tenant_id=tenant_uuid, subject="dev")


async def get_auth(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_forge_oauth_system: str | None = Header(default=None),
) -> AuthContext:
    settings = get_settings()

    # Forge Remote: Bearer <FIT>
    if authorization and authorization.startswith("Bearer "):
        if not x_forge_oauth_system:
            logger.info(
                "auth.forge_headers", extra={"header_names": sorted(request.headers.keys())}
            )
        return await _auth_forge(session, settings, authorization, x_forge_oauth_system)

    # Tenant API key (hosted MCP endpoint / direct API access): X-API-Key
    # matching a tenant's stored key hash. No X-Tenant-Id needed — the key is
    # tenant-scoped.
    if x_api_key:
        ctx = await _auth_tenant_key(session, x_api_key)
        if ctx is not None:
            return ctx

    # Development: shared API key + explicit tenant (constant-time compare).
    if (
        settings.dev_auth_enabled
        and x_api_key
        and secrets.compare_digest(x_api_key, settings.api_secret_key)
    ):
        return _auth_dev(x_tenant_id)

    logger.warning("auth.rejected", extra={"had_api_key": bool(x_api_key)})
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
