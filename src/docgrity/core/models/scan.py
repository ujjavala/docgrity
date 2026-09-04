"""Scans, agent tasks, audit events."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from docgrity.core.enums import AgentTaskStatus, ScanStatus
from docgrity.core.models.base import Base, TenantScopedMixin, TimestampMixin, uuid_pk


class Scan(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "scan"

    id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status"), nullable=False, default=ScanStatus.PENDING
    )
    checks: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    actions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanSource(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "scan_source"

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id"), nullable=False
    )
    scope_external_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class ScanFinding(Base, TenantScopedMixin):
    __tablename__ = "scan_finding"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan.id"), primary_key=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finding.id"), primary_key=True
    )


class AgentTask(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "agent_task"

    id: Mapped[uuid.UUID] = uuid_pk()
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_task.id")
    )
    scan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("scan.id"))

    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[AgentTaskStatus] = mapped_column(
        Enum(AgentTaskStatus, name="agent_task_status"),
        nullable=False,
        default=AgentTaskStatus.PENDING,
    )

    input: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB)

    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    token_usage: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)

    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base, TenantScopedMixin, TimestampMixin):
    """Every attempted or executed action is audited."""

    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor: Mapped[str] = mapped_column(String(255), nullable=False)  # agent name or user id
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    # ALLOWED | DENIED | APPROVAL_REQUIRED
    policy_decision: Mapped[str | None] = mapped_column(String(50))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
