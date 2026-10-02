"""Separate outreach message format from tone.

Revision ID: 20260818_0023
Revises: 20260814_0022
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0023"
down_revision: str | None = "20260814_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "message_drafts",
        sa.Column(
            "message_format",
            sa.String(30),
            nullable=False,
            server_default="expanded",
        ),
    )
    # A short-lived pre-release build used `linkedin` as a tone. Preserve those
    # drafts as short professional messages while keeping production legacy
    # `professional` / `friendly` drafts expanded.
    op.execute(
        sa.text(
            "UPDATE message_drafts "
            "SET message_format = 'short', tone = 'professional' "
            "WHERE tone = 'linkedin'"
        )
    )
    op.create_index(
        "ix_message_drafts_format_tone",
        "message_drafts",
        ["message_format", "tone"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_drafts_format_tone", table_name="message_drafts")
    op.drop_column("message_drafts", "message_format")
