"""Add separate sender voice profile and approved writing examples.

Revision ID: 20260810_0019
Revises: 20260809_0018
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0019"
down_revision: str | None = "20260809_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sender_voice_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("communication_style", postgresql.JSONB(), nullable=False),
        sa.Column("values", postgresql.JSONB(), nullable=False),
        sa.Column("motivations", postgresql.JSONB(), nullable=False),
        sa.Column("interests", postgresql.JSONB(), nullable=False),
        sa.Column("preferred_tone", sa.String(length=80), nullable=False),
        sa.Column("preferred_openings", postgresql.JSONB(), nullable=False),
        sa.Column("things_to_avoid", postgresql.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_profile_id"),
    )
    op.create_index(
        op.f("ix_sender_voice_profiles_candidate_profile_id"),
        "sender_voice_profiles",
        ["candidate_profile_id"],
        unique=True,
    )
    op.create_table(
        "approved_writing_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sender_voice_profile_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("company_context", sa.String(length=300), nullable=False),
        sa.Column("purpose", sa.String(length=120), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["sender_voice_profile_id"], ["sender_voice_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("sender_voice_profile_id", "language", "approved"):
        op.create_index(
            op.f(f"ix_approved_writing_examples_{column}"),
            "approved_writing_examples",
            [column],
        )


def downgrade() -> None:
    op.drop_table("approved_writing_examples")
    op.drop_table("sender_voice_profiles")
