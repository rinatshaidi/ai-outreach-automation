"""Server-rendered Follow-up and manual history controls."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.api.crm import DbSession
from app.api.followups import (
    approve_followup,
    cancel_followup,
    defer_followup,
    record_manual_reply,
    refresh_due_followups,
    reject_followup,
)
from app.api.web import templates
from app.config import get_settings
from app.modules.crm.models import Company, Contact
from app.modules.followups.models import FollowUp
from app.modules.followups.schemas import (
    FollowUpDecisionCreate,
    FollowUpDeferCreate,
    FollowUpRefreshRequest,
    ManualOutcome,
    ManualReplyCreate,
)
from app.modules.followups.service import timezone_or_error

router = APIRouter(include_in_schema=False)


@router.get("/followups", response_class=HTMLResponse)
async def followups_page(request: Request, session: DbSession) -> HTMLResponse:
    items = list(await session.scalars(select(FollowUp).order_by(FollowUp.due_at.asc()).limit(500)))
    companies = {item.id: item for item in await session.scalars(select(Company))}
    contacts = {item.id: item for item in await session.scalars(select(Contact))}
    return templates.TemplateResponse(
        request=request,
        name="followups.html",
        context={
            "followups": items,
            "companies": companies,
            "contacts": contacts,
            "outcomes": list(ManualOutcome),
        },
    )


@router.post("/followups/refresh")
async def refresh_followups(request: Request, session: DbSession) -> RedirectResponse:
    await refresh_due_followups(FollowUpRefreshRequest(), request, session)
    return RedirectResponse("/followups", status_code=303)


@router.post("/followups/{followup_id}/decision/{action}")
async def decide_followup(
    followup_id: UUID,
    action: str,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    comment: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    payload = FollowUpDecisionCreate(version=version, confirmed=True, comment=comment)
    if action == "approve":
        await approve_followup(followup_id, payload, request, session)
    elif action == "reject":
        await reject_followup(followup_id, payload, request, session)
    elif action == "cancel":
        await cancel_followup(followup_id, payload, request, session)
    return RedirectResponse("/followups", status_code=303)


@router.post("/followups/{followup_id}/defer-until")
async def defer_followup_until(
    followup_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    due_at: Annotated[str, Form()],
) -> RedirectResponse:
    settings = get_settings()
    local_due = datetime.fromisoformat(due_at).replace(
        tzinfo=timezone_or_error(settings.user_timezone)
    )
    await defer_followup(
        followup_id,
        FollowUpDeferCreate(version=version, due_at=local_due.astimezone(UTC)),
        request,
        session,
    )
    return RedirectResponse("/followups", status_code=303)


@router.post("/followups/manual-reply")
async def save_manual_reply(
    request: Request,
    session: DbSession,
    company_id: Annotated[UUID, Form()],
    contact_id: Annotated[UUID, Form()],
    outcome: Annotated[ManualOutcome, Form()],
    summary: Annotated[str, Form()],
) -> RedirectResponse:
    await record_manual_reply(
        ManualReplyCreate(
            company_id=company_id,
            contact_id=contact_id,
            outcome=outcome,
            summary=summary,
        ),
        request,
        session,
    )
    return RedirectResponse("/followups", status_code=303)
