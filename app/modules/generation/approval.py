"""Cross-module invalidation hooks for revision-bound approvals."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.generation.models import DraftApproval, MessageDraft


async def invalidate_approvals_for_candidate_fact(
    session: AsyncSession,
    fact_id: UUID,
    *,
    reason: str = "candidate_permission_revoked",
) -> int:
    approvals = list(
        await session.scalars(
            select(DraftApproval)
            .join(MessageDraft, MessageDraft.id == DraftApproval.draft_id)
            .where(
                MessageDraft.candidate_fact_ids.contains([str(fact_id)]),
                DraftApproval.invalidated_at.is_(None),
                DraftApproval.consumed_at.is_(None),
            )
        )
    )
    now = datetime.now(UTC)
    for approval in approvals:
        approval.invalidated_at = now
        approval.invalidation_reason = reason
    return len(approvals)
