"""Sources: source, source_connection, source_scope."""

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from docgrity.core.enums import SourceType
from docgrity.core.models.base import Base, TenantScopedMixin, TimestampMixin, uuid_pk


class Source(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "source"
    __table_args__ = (UniqueConstraint("tenant_id", "type", "name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SourceConnection(Base, TenantScopedMixin, TimestampMixin):
    """Connection metadata only. Credentials live in the secrets manager, never here."""

    __tablename__ = "source_connection"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id"), nullable=False
    )
    base_url: Mapped[str | None] = mapped_column(String(1024))
    auth_kind: Mapped[str] = mapped_column(String(50), nullable=False)  # api_token | oauth | forge
    secret_ref: Mapped[str | None] = mapped_column(String(255))  # secrets-manager key, not a secret
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SourceScope(Base, TenantScopedMixin, TimestampMixin):
    """A scannable scope within a source (Confluence space, Slack channel, repo)."""

    __tablename__ = "source_scope"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. space key
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
