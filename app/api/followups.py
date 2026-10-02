"""Guarded follow-up proposals and manually recorded communication outcomes."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import add_event
from app.infrastructure.db.session import get_db_session
from app.modules.audit.models import AuditEvent
from app.modules.crm.models import Campaign, Company, Contact
from app.modules.delivery.models import OutboundMessage
from app.modules.followups.models import FollowUp
from app.modules.followups.schemas import (
    FollowUpDecisionCreate,
    FollowUpDeferCreate,
    FollowUpRead,
    FollowUpRefreshRequest,
    ManualReplyCreate,
    ManualReplyRead,
)
from app.modules.followups.service import (
    OPEN_FOLLOWUP_STATUSES,
    cancel_open_followups,
    proposal_for,
)

router = APIRouter(prefix="/api/v1", tags=["follow-ups"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
TERMINAL_COMPANY_STATUSES = {
    "replied",
    "interview",
    "project_discussion",
    "consulting_discussion",
    "rejected",
    "offer",
    "agreement",
    "closed",
}


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "missing-request-id"))[:64]


async def followup_or_404(session: AsyncSession, followup_id: UUID) -> FollowUp:
    item = await session.scalar(
        select(FollowUp).where(FollowUp.id == followup_id).with_for_update()
    )
    if item is None:
        raise api_error(404, "followup_not_found", "Follow-up was not found")
    return item


def ensure_version(item: FollowUp, supplied: int) -> None:
    if item.version != supplied:
        raise api_error(409, "version_conflict", "Follow-up changed; refresh and try again")


def add_audit(
    session: AsyncSession,
    *,
    item: FollowUp,
    action: str,
    request: Request,
    safe_diff: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            actor="primary_owner",
            action=action,
            entity_type="followup",
            entity_id=str(item.id),
            result="success",
            safe_diff=safe_diff,
            request_id=request_id(request),
        )
    )


@router.get("/followups", response_model=list[FollowUpRead])
async def list_followups(
    session: DbSession,
    company_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status", max_length=30),
    due_before: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[FollowUp]:
    query: Select[tuple[FollowUp]] = select(FollowUp)
    if company_id:
        query = query.where(FollowUp.company_id == company_id)
    if status_filter:
        query = query.where(FollowUp.status == status_filter)
    if due_before:
        query = query.where(FollowUp.due_at <= due_before)
    return list(await session.scalars(query.order_by(FollowUp.due_at.asc()).limit(limit)))


@router.post("/followups/refresh-due", response_model=list[FollowUpRead])
async def refresh_due_followups(
    payload: FollowUpRefreshRequest,
    request: Request,
    session: DbSession,
) -> list[FollowUp]:
    now = datetime.now(UTC)
    items = list(
        await session.scalars(
            select(FollowUp)
            .where(
                FollowUp.status.in_({"planned", "deferred"}),
                FollowUp.due_at <= now,
            )
            .order_by(FollowUp.due_at.asc())
            .limit(payload.limit)
            .with_for_update(skip_locked=True)
        )
    )
    proposed: list[FollowUp] = []
    for item in items:
        company = await session.get(Company, item.company_id)
        contact = await session.get(Contact, item.contact_id)
        campaign = await session.get(Campaign, item.campaign_id)
        if (
            company is None
            or contact is None
            or campaign is None
            or company.pipeline_status in TERMINAL_COMPANY_STATUSES
            or contact.do_not_contact
            or contact.verification_status == "suppressed"
            or campaign.status != "active"
        ):
            await cancel_open_followups(
                session,
                company_id=item.company_id,
                reason="context_no_longer_eligible",
                request_id=request_id(request),
            )
            continue
        original = await session.get(OutboundMessage, item.original_message_id)
        if original is None or original.delivery_status != "sent":
            await cancel_open_followups(
                session,
                company_id=item.company_id,
                reason="original_delivery_missing",
                request_id=request_id(request),
            )
            continue
        item.status = "due"
        subject, body, report, digest = proposal_for(original)
        item.subject = subject
        item.body = body
        item.validation_report = report
        item.content_hash = digest
        item.status = "draft_ready" if report["passed"] else "rejected"
        item.version += 1
        proposed.append(item)
        add_event(
            session,
            company_id=item.company_id,
            contact_id=item.contact_id,
            event_type="followup_proposed",
            summary="Follow-up proposal is ready for manual review",
            metadata={"followup_id": str(item.id), "content_hash": digest},
        )
        add_audit(
            session,
            item=item,
            action="followup_proposed",
            request=request,
            safe_diff={"status": item.status, "content_hash": digest},
        )
    await session.commit()
    for item in proposed:
        await session.refresh(item)
    return proposed


@router.post("/followups/{followup_id}/approve", response_model=FollowUpRead)
async def approve_followup(
    followup_id: UUID,
    payload: FollowUpDecisionCreate,
    request: Request,
    session: DbSession,
) -> FollowUp:
    item = await followup_or_404(session, followup_id)
    ensure_version(item, payload.version)
    if not payload.confirmed:
        raise api_error(422, "explicit_confirmation_required", "Approval must be explicit")
    if item.status != "draft_ready" or not item.validation_report.get("passed"):
        raise api_error(409, "followup_not_ready", "Only a valid proposal can be approved")
    item.status = "approved"
    item.approved_at = datetime.now(UTC)
    item.approved_by = "primary_owner"
    item.approval_comment = payload.comment
    item.version += 1
    add_event(
        session,
        company_id=item.company_id,
        contact_id=item.contact_id,
        event_type="followup_approved",
        summary="Follow-up proposal manually approved; automatic sending remains disabled",
        metadata={"followup_id": str(item.id), "content_hash": item.content_hash},
    )
    add_audit(
        session,
        item=item,
        action="followup_approved",
        request=request,
        safe_diff={"content_hash": item.content_hash, "automatic_send": False},
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/followups/{followup_id}/defer", response_model=FollowUpRead)
async def defer_followup(
    followup_id: UUID,
    payload: FollowUpDeferCreate,
    request: Request,
    session: DbSession,
) -> FollowUp:
    item = await followup_or_404(session, followup_id)
    ensure_version(item, payload.version)
    if item.status not in OPEN_FOLLOWUP_STATUSES or item.status == "approved":
        raise api_error(409, "followup_not_open", "Follow-up cannot be deferred")
    if payload.due_at.tzinfo is None or payload.due_at <= datetime.now(UTC):
        raise api_error(422, "future_due_required", "Deferred due time must be in the future")
    item.status = "deferred"
    item.due_at = payload.due_at
    item.version += 1
    add_event(
        session,
        company_id=item.company_id,
        contact_id=item.contact_id,
        event_type="followup_deferred",
        summary="Follow-up manually deferred",
        metadata={"followup_id": str(item.id), "due_at": item.due_at.isoformat()},
    )
    add_audit(
        session,
        item=item,
        action="followup_deferred",
        request=request,
        safe_diff={"due_at": item.due_at.isoformat()},
    )
    await session.commit()
    await session.refresh(item)
    return item


async def close_followup(
    *,
    item: FollowUp,
    payload: FollowUpDecisionCreate,
    request: Request,
    session: AsyncSession,
    target: str,
) -> FollowUp:
    ensure_version(item, payload.version)
    if not payload.confirmed:
        raise api_error(422, "explicit_confirmation_required", "Decision must be explicit")
    if item.status not in OPEN_FOLLOWUP_STATUSES:
        raise api_error(409, "followup_not_open", "Follow-up is already closed")
    item.status = target
    if target == "cancelled":
        item.cancelled_at = datetime.now(UTC)
        item.cancellation_reason = "manual_cancellation"
    item.version += 1
    add_event(
        session,
        company_id=item.company_id,
        contact_id=item.contact_id,
        event_type=f"followup_{target}",
        summary=f"Follow-up manually {target}",
        metadata={"followup_id": str(item.id)},
    )
    add_audit(
        session,
        item=item,
        action=f"followup_{target}",
        request=request,
        safe_diff={"status": target},
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/followups/{followup_id}/reject", response_model=FollowUpRead)
async def reject_followup(
    followup_id: UUID,
    payload: FollowUpDecisionCreate,
    request: Request,
    session: DbSession,
) -> FollowUp:
    return await close_followup(
        item=await followup_or_404(session, followup_id),
        payload=payload,
        request=request,
        session=session,
        target="rejected",
    )


@router.post("/followups/{followup_id}/cancel", response_model=FollowUpRead)
async def cancel_followup(
    followup_id: UUID,
    payload: FollowUpDecisionCreate,
    request: Request,
    session: DbSession,
) -> FollowUp:
    return await close_followup(
        item=await followup_or_404(session, followup_id),
        payload=payload,
        request=request,
        session=session,
        target="cancelled",
    )


@router.post(
    "/communications/replies",
    response_model=ManualReplyRead,
    status_code=status.HTTP_201_CREATED,
)
async def record_manual_reply(
    payload: ManualReplyCreate,
    request: Request,
    session: DbSession,
) -> ManualReplyRead:
    company = await session.get(Company, payload.company_id)
    contact = await session.get(Contact, payload.contact_id)
    if company is None or contact is None:
        raise api_error(404, "reply_context_not_found", "Company or contact was not found")
    if contact.company_id != company.id:
        raise api_error(422, "contact_mismatch", "Contact belongs to another company")
    outcome = payload.outcome.value
    company.pipeline_status = outcome
    company.next_action = f"Review manually recorded outcome: {outcome}"
    company.version += 1
    cancelled = await cancel_open_followups(
        session,
        company_id=company.id,
        reason=f"manual_reply_{outcome}",
        request_id=request_id(request),
    )
    occurred_at = payload.occurred_at or datetime.now(UTC)
    add_event(
        session,
        company_id=company.id,
        contact_id=contact.id,
        event_type=outcome,
        summary=payload.summary,
        metadata={"manual": True, "cancelled_followups": len(cancelled)},
        occurred_at=occurred_at,
    )
    session.add(
        AuditEvent(
            actor="primary_owner",
            action="manual_reply_recorded",
            entity_type="company",
            entity_id=str(company.id),
            result="success",
            safe_diff={"outcome": outcome, "cancelled_followups": len(cancelled)},
            request_id=request_id(request),
        )
    )
    await session.commit()
    return ManualReplyRead(
        company_id=company.id,
        contact_id=contact.id,
        outcome=payload.outcome,
        cancelled_followups=len(cancelled),
        occurred_at=occurred_at,
    )
