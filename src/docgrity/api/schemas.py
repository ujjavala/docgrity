"""API request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from docgrity.core.enums import FindingSeverity, FindingStatus, FindingType, ScanStatus


class ScanCreateRequest(BaseModel):
    checks: list[str] = Field(
        default=["duplicates"],
        description=(
            "ingest | duplicates | contradictions | open_questions | "
            "stale_specs | code_doc_drift | tribal_knowledge"
        ),
    )
    source_id: uuid.UUID | None = None  # required for ingest
    post_comments: bool = False
    space_id: str | None = None  # limit non-ingest checks to one Confluence space


class ScanResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    status: ScanStatus
    checks: list
    stats: dict
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class EvidenceResponse(BaseModel):
    model_config = {"from_attributes": True}

    excerpt: str
    source_label: str
    knowledge_item_id: uuid.UUID | None


class PersonResponse(BaseModel):
    account_id: str
    display_name: str
    confidence: float
    authoritative: bool
    evidence: list


class FindingResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    type: FindingType
    severity: FindingSeverity
    status: FindingStatus
    title: str
    summary: str
    confidence: float
    recommended_action: str | None
    detail: dict
    created_at: datetime
    resolved_at: datetime | None
    owner_names: list[str] = []


class PageRef(BaseModel):
    id: str | None = None
    external_id: str | None = None
    title: str
    url: str | None = None


class FindingDetailResponse(FindingResponse):
    evidence: list[EvidenceResponse]
    potential_owners: list[PersonResponse]
    pages: list[PageRef] = []


class FindingStatsResponse(BaseModel):
    total_open: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    by_status: dict[str, int]
    last_scan_completed_at: datetime | None


class FindingStatusUpdate(BaseModel):
    status: FindingStatus


class MergeRedirectRequest(BaseModel):
    keep_item_id: uuid.UUID


class EditPatchResponse(BaseModel):
    page_external_id: str
    page_title: str | None = None
    find_text: str
    replace_text: str
    rationale: str
    confidence: float


class DraftFixResponse(BaseModel):
    patches: list[EditPatchResponse]
    reasoning: str


class ApplyFixRequest(BaseModel):
    page_external_id: str
    find_text: str
    replace_text: str


class ActionResultResponse(BaseModel):
    ok: bool
    detail: dict
