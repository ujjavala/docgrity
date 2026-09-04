"""Tenancy: tenant, user, team."""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from docgrity.core.models.base import Base, TenantScopedMixin, TimestampMixin, uuid_pk


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Atlassian installation mapping (Forge lifecycle): cloudId → tenant.
    atlassian_cloud_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    # SHA-256 hash of the tenant API key (used by the hosted MCP endpoint and
    # any direct API access). The plaintext key is shown once at creation and
    # never stored.
    api_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class User(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    external_id: Mapped[str | None] = mapped_column(String(255))  # e.g. Atlassian accountId
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))


class Team(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "team"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class TeamMember(Base, TenantScopedMixin):
    __tablename__ = "team_member"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("team.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), primary_key=True
    )
