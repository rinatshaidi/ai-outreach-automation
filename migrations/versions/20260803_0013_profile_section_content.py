"""Add editable content drafts to candidate profile sections.

Revision ID: 20260803_0013
Revises: 20260802_0012
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0013"
down_revision: str | None = "20260802_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_profile_sections",
        sa.Column("content_draft", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_profile_sections", "content_draft")
