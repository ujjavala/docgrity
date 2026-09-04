"""Add ARCHIVE_CONFLUENCE_PAGE to action_type enum.

Revision ID: b1c2d3e4f5a6
Revises: 903610e1e97f
Create Date: 2026-04-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "903610e1e97f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'ARCHIVE_CONFLUENCE_PAGE'")


def downgrade() -> None:
    # Postgres cannot drop enum values; no-op.
    pass
