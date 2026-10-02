"""Add fail-closed owner safety policy.

Revision ID: 20260812_0021
Revises: 20260811_0020
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0021"
down_revision: str | None = "20260811_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_safety_policies",
        sa.Column("owner_key", sa.String(80), nullable=False),
        sa.Column("real_send_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("real_send_enabled_at", sa.DateTime(timezone=True)),
        sa.Column("real_send_disabled_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_key"),
    )


def downgrade() -> None:
    op.drop_table("owner_safety_policies")
