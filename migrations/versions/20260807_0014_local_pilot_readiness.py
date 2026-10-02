"""Mark synthetic companies and normalize approved local-pilot data.

Revision ID: 20260807_0014
Revises: 20260803_0013
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0014"
down_revision: str | None = "20260803_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_companies_is_synthetic", "companies", ["is_synthetic"])
    op.execute(
        """
        UPDATE companies
        SET is_synthetic = TRUE
        WHERE normalized_domain LIKE '%.example'
           OR name ILIKE '%(Synthetic)%'
        """
    )
    op.execute(
        """
        UPDATE candidate_profiles
        SET desired_roles = COALESCE((
                SELECT jsonb_agg(regexp_replace(value, '\\s+Страны:\\s*Любая страна\\s*$', ''))
                FROM jsonb_array_elements_text(desired_roles) AS role(value)
            ), '[]'::jsonb),
            adjacent_roles = COALESCE((
                SELECT jsonb_agg(regexp_replace(value, '\\s+Нежелательные роли:\\s*$', ''))
                FROM jsonb_array_elements_text(adjacent_roles) AS role(value)
            ), '[]'::jsonb)
        WHERE owner_key = 'primary'
        """
    )
    op.execute(
        """
        UPDATE candidate_experiences
        SET organization_label = 'Independent Projects'
        WHERE profile_id = (SELECT id FROM candidate_profiles WHERE owner_key = 'primary')
          AND position(chr(92) in organization_label) > 0
          AND lower(organization_label) LIKE '%independent projects%'
        """
    )
    op.execute(
        """
        UPDATE candidate_skills
        SET skill_group = 'technology'
        WHERE profile_id = (SELECT id FROM candidate_profiles WHERE owner_key = 'primary')
          AND lower(name) = lower('AI Automation / Python Automation')
        """
    )
    op.execute(
        """
        UPDATE candidate_rules SET rule_type = 'wording'
        WHERE profile_id = (SELECT id FROM candidate_profiles WHERE owner_key = 'primary')
          AND rule_type = 'worning'
        """
    )
    profile_table = sa.table(
        "candidate_profiles",
        sa.column("id", sa.Uuid()),
        sa.column("owner_key", sa.String()),
    )
    primary_profile_id = sa.select(profile_table.c.id).where(
        profile_table.c.owner_key == "primary"
    )
    permission_updates = (
        "candidate_experiences",
        "candidate_skills",
        "candidate_strengths",
        "candidate_facts",
        "candidate_contacts",
    )
    for table_name in permission_updates:
        table = sa.table(
            table_name,
            sa.column("profile_id", sa.Uuid()),
            sa.column("store_private", sa.Boolean()),
            sa.column("use_for_ai_analysis", sa.Boolean()),
            sa.column("use_in_scoring", sa.Boolean()),
            sa.column("use_in_draft", sa.Boolean()),
            sa.column("send_externally", sa.Boolean()),
            sa.column("use_in_signature", sa.Boolean()),
            sa.column("publish_publicly", sa.Boolean()),
        )
        op.execute(
            table.update()
            .where(table.c.profile_id == primary_profile_id.scalar_subquery())
            .values(
                store_private=True,
                use_for_ai_analysis=True,
                use_in_scoring=True,
                use_in_draft=True,
                send_externally=False,
                use_in_signature=False,
                publish_publicly=False,
            )
        )


def downgrade() -> None:
    op.drop_index("ix_companies_is_synthetic", table_name="companies")
    op.drop_column("companies", "is_synthetic")
