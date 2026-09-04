"""Smoke tests for the SQLAlchemy domain model metadata."""

from docgrity.core import models
from docgrity.core.models import Base

EXPECTED_TABLES = {
    "tenant",
    "user",
    "team",
    "team_member",
    "source",
    "source_connection",
    "source_scope",
    "knowledge_item",
    "knowledge_item_chunk",
    "knowledge_item_version",
    "finding",
    "finding_evidence",
    "finding_person",
    "finding_action",
    "comment_action",
    "scan",
    "scan_source",
    "scan_finding",
    "agent_task",
    "audit_event",
}


def test_all_domain_tables_registered():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_table_is_tenant_scoped():
    for name, table in Base.metadata.tables.items():
        if name == "tenant":
            continue
        assert "tenant_id" in table.columns, f"{name} is missing tenant_id"


def test_finding_tracks_reproducibility_fields():
    finding = Base.metadata.tables["finding"]
    for column in ("model", "prompt_version", "input_hash"):
        assert column in finding.columns


def test_models_exported():
    assert len(models.__all__) == 21  # 20 models + Base
