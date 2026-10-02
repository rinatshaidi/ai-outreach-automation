"""Add immutable draft revisions, review events and revision-bound approvals.

Revision ID: 20260801_0009
Revises: 20260801_0008
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0009"
down_revision: str | None = "20260801_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_message_draft_run_variant", "message_drafts", type_="unique")
    op.add_column("message_drafts", sa.Column("contact_version", sa.Integer(), nullable=True))
    op.add_column("message_drafts", sa.Column("content_hash", sa.String(length=128), nullable=True))
    op.execute(
        "UPDATE message_drafts AS d SET contact_version = c.version "
        "FROM contacts AS c WHERE c.id = d.contact_id"
    )
    op.execute("UPDATE message_drafts SET content_hash = md5(subject || E'\\n' || body)")
    op.alter_column("message_drafts", "contact_version", nullable=False)
    op.alter_column("message_drafts", "content_hash", nullable=False)
    op.create_unique_constraint(
        "uq_message_draft_run_variant_revision",
        "message_drafts",
        ["generation_run_id", "variant", "revision"],
    )

    op.create_table(
        "draft_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("one_time_token_hash", sa.String(length=128), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=240), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["message_drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id"),
        sa.UniqueConstraint("one_time_token_hash"),
    )
    op.create_index(op.f("ix_draft_approvals_draft_id"), "draft_approvals", ["draft_id"])
    op.create_index(op.f("ix_draft_approvals_decision"), "draft_approvals", ["decision"])

    op.create_table(
        "draft_review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("safe_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_id"], ["message_drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("company_id", "draft_id", "action", "created_at"):
        op.create_index(op.f(f"ix_draft_review_events_{column}"), "draft_review_events", [column])


def downgrade() -> None:
    op.drop_table("draft_review_events")
    op.drop_table("draft_approvals")
    op.drop_constraint("uq_message_draft_run_variant_revision", "message_drafts", type_="unique")
    op.execute(
        "DELETE FROM message_drafts AS older USING message_drafts AS newer "
        "WHERE older.generation_run_id = newer.generation_run_id "
        "AND older.variant = newer.variant AND older.revision < newer.revision"
    )
    op.create_unique_constraint(
        "uq_message_draft_run_variant", "message_drafts", ["generation_run_id", "variant"]
    )
    op.drop_column("message_drafts", "content_hash")
    op.drop_column("message_drafts", "contact_version")
