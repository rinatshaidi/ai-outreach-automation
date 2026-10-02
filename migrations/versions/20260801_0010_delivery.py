"""Add idempotent outbound messages and append-only delivery attempts.

Revision ID: 20260801_0010
Revises: 20260801_0009
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0010"
down_revision: str | None = "20260801_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("delivery_mode", sa.String(length=20), nullable=False),
        sa.Column("recipient_hash", sa.String(length=128), nullable=False),
        sa.Column("recipient_masked", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("delivery_status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("external_message_id", sa.String(length=500), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["draft_approvals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_id"], ["message_drafts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in (
        "company_id",
        "contact_id",
        "campaign_id",
        "draft_id",
        "approval_id",
        "delivery_mode",
        "delivery_status",
        "sent_at",
        "created_at",
    ):
        op.create_index(op.f(f"ix_outbound_messages_{column}"), "outbound_messages", [column])

    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["outbound_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("message_id", "result", "created_at"):
        op.create_index(op.f(f"ix_delivery_attempts_{column}"), "delivery_attempts", [column])


def downgrade() -> None:
    op.drop_table("delivery_attempts")
    op.drop_table("outbound_messages")
