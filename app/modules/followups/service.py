"""Deterministic due calculation, proposal generation and cancellation."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent
from app.modules.crm.models import Campaign, CommunicationEvent
from app.modules.delivery.models import OutboundMessage
from app.modules.followups.models import FollowUp

OPEN_FOLLOWUP_STATUSES = {"planned", "due", "draft_ready", "approved", "deferred"}


def add_history_event(
    session: AsyncSession,
    *,
    company_id: UUID,
    contact_id: UUID,
    event_type: str,
    summary: str,
    metadata: dict[str, Any],
) -> None:
    session.add(
        CommunicationEvent(
            company_id=company_id,
            contact_id=contact_id,
            event_type=event_type,
            summary=summary,
            metadata_json=metadata,
        )
    )


def timezone_or_error(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown user timezone: {name}") from exc


def add_business_days(value: datetime, days: int, timezone_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError("A timezone-aware send timestamp is required")
    if days < 0:
        raise ValueError("Business-day interval cannot be negative")
    local = value.astimezone(timezone_or_error(timezone_name))
    added = 0
    while added < days:
        local += timedelta(days=1)
        if local.weekday() < 5:
            added += 1
    return local.astimezone(UTC)


def followup_policy(campaign: Campaign) -> tuple[bool, int, int]:
    policy: dict[str, Any] = campaign.followup_policy or {}
    enabled = bool(policy.get("enabled", True))
    try:
        interval = int(policy.get("interval_business_days", 7))
        maximum = int(policy.get("max_followups", 1))
    except (TypeError, ValueError):
        interval, maximum = 7, 1
    return enabled, max(0, min(interval, 60)), max(0, min(maximum, 5))


def proposal_for(message: OutboundMessage) -> tuple[str, str, dict[str, Any], str]:
    subject = (
        message.subject
        if message.subject.casefold().startswith("re:")
        else f"Re: {message.subject}"
    )
    body = (
        "Following up on my previous note. If this is relevant, would a brief conversation "
        "make sense? If not, no action is needed."
    )
    report = {
        "passed": len(body) < len(message.body),
        "shorter_than_original": len(body) < len(message.body),
        "source_message_id": str(message.id),
        "new_candidate_facts": [],
        "automatic_send_allowed": False,
    }
    digest = sha256(f"{subject}\n{body}".encode()).hexdigest()
    return subject, body, report, digest


async def schedule_followup(
    session: AsyncSession,
    *,
    message: OutboundMessage,
    campaign: Campaign,
    timezone_name: str,
) -> FollowUp | None:
    enabled, interval, maximum = followup_policy(campaign)
    if not enabled or maximum < 1 or message.sent_at is None:
        return None
    existing = await session.scalar(
        select(FollowUp).where(
            FollowUp.original_message_id == message.id,
            FollowUp.sequence_number == 1,
        )
    )
    if existing:
        return existing
    followup = FollowUp(
        company_id=message.company_id,
        contact_id=message.contact_id,
        campaign_id=campaign.id,
        original_message_id=message.id,
        sequence_number=1,
        status="planned",
        timezone=timezone_name,
        due_at=add_business_days(message.sent_at, interval, timezone_name),
    )
    session.add(followup)
    await session.flush()
    add_history_event(
        session,
        company_id=message.company_id,
        contact_id=message.contact_id,
        event_type="followup_planned",
        summary="Follow-up planned after successful delivery",
        metadata={"followup_id": str(followup.id), "due_at": followup.due_at.isoformat()},
    )
    return followup


async def cancel_open_followups(
    session: AsyncSession,
    *,
    reason: str,
    request_id: str,
    company_id: UUID | None = None,
    contact_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> list[FollowUp]:
    query = select(FollowUp).where(FollowUp.status.in_(OPEN_FOLLOWUP_STATUSES))
    if company_id:
        query = query.where(FollowUp.company_id == company_id)
    if contact_id:
        query = query.where(FollowUp.contact_id == contact_id)
    if campaign_id:
        query = query.where(FollowUp.campaign_id == campaign_id)
    items = list(await session.scalars(query.with_for_update()))
    cancelled_at = datetime.now(UTC)
    for item in items:
        item.status = "cancelled"
        item.cancelled_at = cancelled_at
        item.cancellation_reason = reason
        item.version += 1
        add_history_event(
            session,
            company_id=item.company_id,
            contact_id=item.contact_id,
            event_type="followup_cancelled",
            summary=f"Follow-up cancelled: {reason}",
            metadata={"followup_id": str(item.id), "reason": reason},
        )
        session.add(
            AuditEvent(
                actor="primary_owner",
                action="followup_cancelled",
                entity_type="followup",
                entity_id=str(item.id),
                result="success",
                safe_diff={"reason": reason},
                request_id=request_id[:64],
            )
        )
    return items
