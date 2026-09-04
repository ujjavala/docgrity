"""Findings: finding, finding_evidence, finding_person, finding_action."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docgrity.core.enums import ActionType, FindingSeverity, FindingStatus, FindingType
from docgrity.core.models.base import Base, TenantScopedMixin, TimestampMixin, uuid_pk


class Finding(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "finding"

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[FindingType] = mapped_column(
        Enum(FindingType, name="finding_type"), nullable=False
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, name="finding_severity"), nullable=False
    )
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status"), nullable=False, default=FindingStatus.NEW
    )

    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_action: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Reproducibility (docs/evaluation.md)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    input_hash: Mapped[str | None] = mapped_column(String(64))

    scan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("scan.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evidence: Mapped[list["FindingEvidence"]] = relationship(back_populates="finding")
    persons: Mapped[list["FindingPerson"]] = relationship(back_populates="finding")


class FindingEvidence(Base, TenantScopedMixin, TimestampMixin):
    """Every finding must have evidence — never assert a problem without it."""

    __tablename__ = "finding_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finding.id"), nullable=False
    )
    knowledge_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_item.id")
    )
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    finding: Mapped[Finding] = relationship(back_populates="evidence")


class FindingPerson(Base, TenantScopedMixin, TimestampMixin):
    """A potential owner/answerer. Always 'potential' unless authoritative."""

    __tablename__ = "finding_person"

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finding.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    authoritative: Mapped[bool] = mapped_column(default=False, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # bullet strings

    finding: Mapped[Finding] = relationship(back_populates="persons")


class FindingAction(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "finding_action"

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finding.id"), nullable=False
    )
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, name="action_type"), nullable=False
    )
    # REQUESTED | APPROVED | EXECUTED | FAILED
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommentAction(Base, TenantScopedMixin, TimestampMixin):
    """Tracks the Docgrity comment on a source page: create once, update thereafter."""

    __tablename__ = "comment_action"

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finding.id"), nullable=False
    )
    knowledge_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_item.id"), nullable=False
    )
    external_comment_id: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATED|UPDATED|RESOLVED
