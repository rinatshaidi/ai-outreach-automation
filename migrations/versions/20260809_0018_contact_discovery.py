"""Add normalized contact discovery candidates and public channels.

Revision ID: 20260809_0018
Revises: 20260808_0017
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0018"
down_revision: str | None = "20260808_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "contact_discovery_status",
            sa.String(length=30),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "companies", sa.Column("contact_discovered_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_companies_contact_discovery_status",
        "companies",
        ["contact_discovery_status"],
    )
    op.add_column("contacts", sa.Column("why_relevant", sa.Text()))
    op.add_column("contacts", sa.Column("discovery_score", sa.Float()))
    op.add_column("contacts", sa.Column("rank_label", sa.String(length=30)))
    op.create_index("ix_contacts_discovery_score", "contacts", ["discovery_score"])
    op.create_index("ix_contacts_rank_label", "contacts", ["rank_label"])
    op.create_table(
        "contact_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("channel_type", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "validation_status",
            sa.String(length=20),
            nullable=False,
            server_default="UNVERIFIED",
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("validation_http_status", sa.Integer()),
        sa.Column("validation_final_url", sa.Text()),
        sa.Column("validation_error", sa.String(length=500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "contact_id", "channel_type", "value", name="uq_contact_channels_value"
        ),
    )
    for column in ("contact_id", "channel_type", "validation_status"):
        op.create_index(
            op.f(f"ix_contact_channels_{column}"), "contact_channels", [column]
        )


def downgrade() -> None:
    op.drop_table("contact_channels")
    op.drop_index("ix_contacts_rank_label", table_name="contacts")
    op.drop_index("ix_contacts_discovery_score", table_name="contacts")
    op.drop_column("contacts", "rank_label")
    op.drop_column("contacts", "discovery_score")
    op.drop_column("contacts", "why_relevant")
    op.drop_index("ix_companies_contact_discovery_status", table_name="companies")
    op.drop_column("companies", "contact_discovered_at")
    op.drop_column("companies", "contact_discovery_status")
