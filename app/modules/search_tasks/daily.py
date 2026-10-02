"""Profile-based daily discovery for the single-owner local pilot."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.candidate_profile.models import CandidateProfile
from app.modules.search_tasks.models import SearchTask
from app.modules.search_tasks.parsing import parse_search_query
from app.modules.search_tasks.schemas import SearchTaskStatus, SearchTaskType


def daily_query(profile: CandidateProfile) -> str:
    """Build a non-identifying discovery query from agreed profile preferences."""

    industries = ", ".join(profile.preferred_industries[:3])
    industry_line = f" Preferred industries: {industries}." if industries else ""
    return (
        "Find real operating companies worldwide with a current, publicly evidenced "
        "opportunity in one of these tracks: (1) project delivery, launches, operations "
        "or contractor coordination; (2) business development, market expansion or "
        "partnerships; (3) practical workflow automation or AI/Python implementation."
        f"{industry_line} Country is not a selection criterion; remote work, relocation "
        "and suitable hybrid formats are allowed. Do not return a company merely because "
        "it mentions projects, growth or AI. Require a recent vacancy, expansion, launch, "
        "partnership, automation initiative or other source-backed reason that can be "
        "linked to one of the three tracks."
    )


def local_today(now: datetime, timezone_name: str) -> date:
    return now.astimezone(ZoneInfo(timezone_name)).date()


async def queue_daily_discovery_if_due(
    session: AsyncSession,
    *,
    now: datetime,
    timezone_name: str,
    scheduled_hour: int,
    result_limit: int,
) -> SearchTask | None:
    """Create at most one durable daily task after the configured local hour."""

    local_now = now.astimezone(ZoneInfo(timezone_name))
    if local_now.hour < scheduled_hour:
        return None
    owner = await session.scalar(
        select(User).where(User.status == "active").order_by(User.created_at).limit(1)
    )
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary").limit(1)
    )
    # Discovery uses only broad role/industry preferences, not private contacts
    # or facts. A filled profile that is awaiting later verification may still
    # supply those preferences; a draft profile may not.
    if owner is None or profile is None:
        return None

    # Profile status is a separate review-flow marker.  A saved profile can
    # legitimately remain "draft" while its owner uses it for local search.
    # Daily discovery is activated only by the explicit production setting and
    # still requires at least one actual search preference.
    if not any(
        (
            profile.desired_roles,
            profile.preferred_industries,
            profile.preferred_countries,
        )
    ):
        return None
    scheduled_for = local_now.date()
    existing = await session.scalar(
        select(SearchTask.id)
        .where(
            SearchTask.owner_id == owner.id,
            SearchTask.source == "daily",
            SearchTask.scheduled_for_date == scheduled_for,
        )
        .limit(1)
    )
    if existing is not None:
        return None
    query = daily_query(profile)
    parsed = parse_search_query(query)
    task = SearchTask(
        owner_id=owner.id,
        original_query=query,
        query_language=parsed.language,
        task_type=SearchTaskType.FIND_COMPANIES.value,
        parsed_country=parsed.country,
        parsed_region=parsed.region,
        parsed_industry=parsed.industry,
        parsed_focus=parsed.focus,
        result_limit=result_limit,
        source="daily",
        scheduled_for_date=scheduled_for,
        status=SearchTaskStatus.RUNNING.value,
        current_stage="queued_for_execution",
    )
    session.add(task)
    await session.flush()
    session.add(
        AuditEvent(
            actor="daily_discovery_scheduler",
            action="daily_search_task_queued",
            entity_type="search_task",
            entity_id=str(task.id),
            result="success",
            safe_diff={
                "scheduled_for_date": scheduled_for.isoformat(),
                "result_limit": result_limit,
                "profile_version": profile.version,
            },
            request_id=f"daily-search-{scheduled_for.isoformat()}",
        )
    )
    await session.commit()
    await session.refresh(task)
    return task
