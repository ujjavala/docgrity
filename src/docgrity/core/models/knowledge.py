"""Knowledge: knowledge_item, knowledge_item_version."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from docgrity.core.enums import KnowledgeItemType, SourceType
from docgrity.core.models.base import Base, TenantScopedMixin, TimestampMixin, uuid_pk

EMBEDDING_DIM = 1536  # OpenAI text-embedding-3-small


class KnowledgeItem(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "knowledge_item"
    __table_args__ = (UniqueConstraint("tenant_id", "source_type", "external_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)

    type: Mapped[KnowledgeItemType] = mapped_column(
        Enum(KnowledgeItemType, name="knowledge_item_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))

    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"))

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeItemChunk(Base, TenantScopedMixin, TimestampMixin):
    """Semantic chunk of a knowledge item; embeddings are re-computed only when
    the chunk's content hash changes (incremental-scan cost control)."""

    __tablename__ = "knowledge_item_chunk"
    __table_args__ = (UniqueConstraint("knowledge_item_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    knowledge_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_item.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class KnowledgeItemVersion(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "knowledge_item_version"
    __table_args__ = (UniqueConstraint("knowledge_item_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    knowledge_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_item.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    author_external_id: Mapped[str | None] = mapped_column(String(255))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
