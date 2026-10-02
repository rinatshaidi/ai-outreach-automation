"""Owner-facing Safety Control Center."""

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.api.crm import DbSession
from app.config import get_settings
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.auth.service import password_matches
from app.modules.mailbox.models import MailboxConnection
from app.modules.safety.models import OwnerSafetyPolicy

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")
OWNER_KEY = "primary"
CONFIRMATION_PHRASE = "ВКЛЮЧИТЬ"


async def _policy(session: DbSession, *, lock: bool = False) -> OwnerSafetyPolicy | None:
    query = select(OwnerSafetyPolicy).where(OwnerSafetyPolicy.owner_key == OWNER_KEY)
    if lock:
        query = query.with_for_update()
    return cast(OwnerSafetyPolicy | None, await session.scalar(query))


def _redirect(status: str) -> RedirectResponse:
    return RedirectResponse(f"/settings/safety?status={status}", status_code=303)


@router.get("/settings/safety", response_class=HTMLResponse)
async def safety_center(request: Request, session: DbSession) -> HTMLResponse:
    settings = get_settings()
    policy = await _policy(session)
    gmail = await session.scalar(
        select(MailboxConnection).where(MailboxConnection.provider == "gmail")
    )
    return templates.TemplateResponse(
        request=request,
        name="safety.html",
        context={
            "policy": policy,
            "real_send_enabled": bool(policy and policy.real_send_enabled),
            "deployment_capable": settings.allow_real_email,
            "gmail_connected": bool(gmail and gmail.status == "connected"),
            "confirmation_phrase": CONFIRMATION_PHRASE,
        },
    )


@router.post("/settings/safety/real-send/enable")
async def enable_real_send(
    request: Request,
    session: DbSession,
    current_password: Annotated[str, Form(min_length=1, max_length=500)],
    confirmation_phrase: Annotated[str, Form(min_length=1, max_length=40)],
    risk_acknowledged: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    settings = get_settings()
    gmail = await session.scalar(
        select(MailboxConnection).where(MailboxConnection.provider == "gmail")
    )
    owner = getattr(request.state, "owner", None)
    if not settings.allow_real_email:
        return _redirect("capability_unavailable")
    if gmail is None or gmail.status != "connected":
        return _redirect("gmail_required")
    if not isinstance(owner, User) or not password_matches(owner.password_hash, current_password):
        return _redirect("password_invalid")
    if confirmation_phrase.strip() != CONFIRMATION_PHRASE or risk_acknowledged != "yes":
        return _redirect("confirmation_invalid")

    now = datetime.now(UTC)
    policy = await _policy(session, lock=True)
    if policy is None:
        policy = OwnerSafetyPolicy(owner_key=OWNER_KEY)
        session.add(policy)
    previous = policy.real_send_enabled
    policy.real_send_enabled = True
    policy.real_send_enabled_at = now
    policy.real_send_disabled_at = None
    session.add(
        AuditEvent(
            actor="primary_owner",
            action="real_external_send_enabled",
            entity_type="owner_safety_policy",
            entity_id=str(policy.id),
            result="success",
            safe_diff={"from": previous, "to": True, "automatic_send": False},
            request_id=str(getattr(request.state, "request_id", "safety-enable"))[:64],
        )
    )
    await session.commit()
    return _redirect("enabled")


@router.post("/settings/safety/real-send/disable")
async def disable_real_send(request: Request, session: DbSession) -> RedirectResponse:
    policy = await _policy(session, lock=True)
    if policy is None:
        policy = OwnerSafetyPolicy(owner_key=OWNER_KEY)
        session.add(policy)
    previous = policy.real_send_enabled
    policy.real_send_enabled = False
    policy.real_send_disabled_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            actor="primary_owner",
            action="real_external_send_disabled",
            entity_type="owner_safety_policy",
            entity_id=str(policy.id),
            result="success",
            safe_diff={"from": previous, "to": False, "automatic_send": False},
            request_id=str(getattr(request.state, "request_id", "safety-disable"))[:64],
        )
    )
    await session.commit()
    return _redirect("disabled")
