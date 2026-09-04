"""Typed output schemas for agent LLM calls.

Architectural principle: all LLM output must use typed Pydantic schemas —
never parse arbitrary prose. Every schema that produces a finding carries
evidence, and ownership results are explicitly *potential* ownership.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from docgrity.core.enums import DuplicateAction, FindingSeverity


class EvidenceItem(BaseModel):
    """A verbatim excerpt supporting a finding. No evidence → no finding."""

    knowledge_item_external_id: str
    excerpt: str = Field(description="Verbatim excerpt from the source content.")
    source_label: str = Field(description="Human-readable label, e.g. page title.")


class DuplicateAssessment(BaseModel):
    """LLM judgement on whether two pages are duplicates."""

    is_duplicate: bool
    confidence: float = Field(ge=0.0, le=1.0)
    severity: FindingSeverity
    summary: str = Field(description="One-paragraph explanation of the overlap.")
    differences: list[str] = Field(
        default_factory=list, description="Material differences between the pages, if any."
    )
    recommended_action: DuplicateAction
    evidence: list[EvidenceItem] = Field(
        description="Excerpts from BOTH pages demonstrating the overlap."
    )


class ContradictionAssessment(BaseModel):
    """LLM judgement on whether two pages contradict each other."""

    is_contradiction: bool
    confidence: float = Field(ge=0.0, le=1.0)
    severity: FindingSeverity
    summary: str = Field(description="One-paragraph explanation of the conflict.")
    conflicting_claims: list[str] = Field(
        default_factory=list,
        description="Each entry states one claim from A and the conflicting claim from B.",
    )
    evidence: list[EvidenceItem] = Field(
        description="Verbatim excerpts from BOTH pages showing the conflicting statements."
    )


class OpenQuestion(BaseModel):
    """A single unresolved question found in a page."""

    question: str = Field(description="The unresolved question, quoted or tightly paraphrased.")
    excerpt: str = Field(description="Verbatim excerpt containing or implying the question.")
    confidence: float = Field(ge=0.0, le=1.0)


class OpenQuestionAssessment(BaseModel):
    """LLM scan of one page for unresolved questions / undecided items."""

    questions: list[OpenQuestion] = Field(
        default_factory=list, description="Unresolved questions. Empty if none."
    )
    severity: FindingSeverity = Field(
        default=FindingSeverity.LOW, description="Overall severity if questions exist."
    )
    summary: str = Field(default="", description="Short summary of what remains unresolved.")


class OwnerCandidate(BaseModel):
    """A person who *might* own the content. Always potential, never asserted."""

    account_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(
        description="Signals supporting this candidate (e.g. 'page owner', '5 of last 10 edits')."
    )


class OwnershipAssessment(BaseModel):
    """Potential ownership inference for a knowledge item."""

    candidates: list[OwnerCandidate] = Field(
        description="Ranked candidates, best first. Empty if no reliable signal."
    )
    reasoning: str


class EditPatch(BaseModel):
    """A precise text replacement drafted by the agent to fix a contradiction.

    Applied deterministically: the exact `find_text` must occur in the target
    page's plain text or the patch is rejected (never fuzzy-applied).
    """

    page_external_id: str = Field(description="External id of the page to edit.")
    find_text: str = Field(description="Exact text currently on the page that is wrong.")
    replace_text: str = Field(description="Corrected text to substitute.")
    rationale: str = Field(description="Why this edit resolves the contradiction.")
    confidence: float = Field(ge=0.0, le=1.0)


class EditDraft(BaseModel):
    """Drafted fix for a contradiction finding. Empty patches = no safe fix found."""

    patches: list[EditPatch] = Field(default_factory=list)
    reasoning: str


class CommentDraft(BaseModel):
    """Draft of a Docgrity Confluence comment for a finding."""

    body_markdown: str = Field(
        description="Comment body. Must state the finding, evidence, and a clear next step."
    )
    mentions_account_ids: list[str] = Field(
        default_factory=list,
        description="Account ids to @-mention as potential owners (label them 'potential').",
    )


class VerificationResult(BaseModel):
    """Whether a previously reported finding is now resolved."""

    resolved: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
