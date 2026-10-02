"""Add validated contact paths and independent UI/outreach language preferences.

Revision ID: 20260808_0015
Revises: 20260807_0014
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0015"
down_revision: str | None = "20260807_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("dashboard_locale", sa.String(length=10), nullable=False, server_default="ru"),
    )
    op.add_column(
        "users",
        sa.Column("outreach_language", sa.String(length=10), nullable=False, server_default="auto"),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "validation_status",
            sa.String(length=30),
            nullable=False,
            server_default="UNVERIFIED_CONTACT",
        ),
    )
    op.add_column("contacts", sa.Column("validated_at", sa.DateTime(timezone=True)))
    op.add_column("contacts", sa.Column("validation_http_status", sa.Integer()))
    op.add_column("contacts", sa.Column("validation_final_url", sa.Text()))
    op.add_column("contacts", sa.Column("validation_error", sa.String(length=500)))
    op.create_index("ix_contacts_validation_status", "contacts", ["validation_status"])


def downgrade() -> None:
    op.drop_index("ix_contacts_validation_status", table_name="contacts")
    op.drop_column("contacts", "validation_error")
    op.drop_column("contacts", "validation_final_url")
    op.drop_column("contacts", "validation_http_status")
    op.drop_column("contacts", "validated_at")
    op.drop_column("contacts", "validation_status")
    op.drop_column("users", "outreach_language")
    op.drop_column("users", "dashboard_locale")
