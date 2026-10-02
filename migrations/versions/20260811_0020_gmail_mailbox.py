"""Add single-owner Gmail OAuth connection and scoped reply persistence.

Revision ID: 20260811_0020
Revises: 20260810_0019
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0020"
down_revision: str | None = "20260810_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbound_messages", sa.Column("external_thread_id", sa.String(500)))
    op.create_index(
        op.f("ix_outbound_messages_external_thread_id"),
        "outbound_messages",
        ["external_thread_id"],
    )
    op.create_table(
        "mailbox_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("account_email", sa.String(320)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text()),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider"),
    )
    op.create_table(
        "oauth_authorization_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("state_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        op.f("ix_oauth_authorization_states_provider"),
        "oauth_authorization_states",
        ["provider"],
    )
    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("provider_message_id", sa.String(500), nullable=False),
        sa.Column("provider_thread_id", sa.String(500), nullable=False),
        sa.Column("sender_hash", sa.String(128), nullable=False),
        sa.Column("sender_masked", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["outbound_message_id"], ["outbound_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_message_id"),
    )
    for column in ("outbound_message_id", "company_id", "contact_id", "provider_thread_id"):
        op.create_index(op.f(f"ix_inbound_messages_{column}"), "inbound_messages", [column])


def downgrade() -> None:
    op.drop_table("inbound_messages")
    op.drop_table("oauth_authorization_states")
    op.drop_table("mailbox_connections")
    op.drop_index(
        op.f("ix_outbound_messages_external_thread_id"), table_name="outbound_messages"
    )
    op.drop_column("outbound_messages", "external_thread_id")
