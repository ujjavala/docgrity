"""Tests for agent schemas, prompt loading, and deterministic agent helpers."""

import pytest
from pydantic import ValidationError

from docgrity.agents.action import comment_to_storage_html
from docgrity.agents.base import input_hash
from docgrity.agents.prompts import load_prompt
from docgrity.agents.schemas import (
    CommentDraft,
    DuplicateAssessment,
    EvidenceItem,
    OwnershipAssessment,
)
from docgrity.core.enums import DuplicateAction, FindingSeverity


def test_load_prompt_latest_version():
    for agent, latest in (
        ("duplicate", "v1"),
        ("ownership", "v1"),
        ("action", "v2"),
        ("verification", "v1"),
    ):
        text, version = load_prompt(agent)
        assert version == latest
        assert len(text) > 100


def test_load_prompt_missing_agent():
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent-agent")


def test_input_hash_deterministic():
    assert input_hash("abc") == input_hash("abc")
    assert input_hash("abc") != input_hash("abd")


def test_duplicate_assessment_requires_valid_confidence():
    with pytest.raises(ValidationError):
        DuplicateAssessment(
            is_duplicate=True,
            confidence=1.5,  # out of range
            severity=FindingSeverity.MEDIUM,
            summary="s",
            recommended_action=DuplicateAction.MERGE,
            evidence=[],
        )


def test_ownership_assessment_allows_empty_candidates():
    assessment = OwnershipAssessment(candidates=[], reasoning="no reliable signal")
    assert assessment.candidates == []


def test_comment_to_storage_html_escapes_and_mentions():
    draft = CommentDraft(
        body_markdown="🤖 Docgrity\nFound <duplicate> pages.",
        mentions_account_ids=["acc-123"],
    )
    html = comment_to_storage_html(draft)
    assert "&lt;duplicate&gt;" in html
    assert 'ri:account-id="acc-123"' in html
    assert "<script" not in html


def test_evidence_item_schema():
    item = EvidenceItem(
        knowledge_item_external_id="1", excerpt="deploy with make deploy", source_label="Guide"
    )
    assert item.excerpt
