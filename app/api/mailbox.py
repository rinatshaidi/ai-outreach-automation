"""Owner-controlled Gmail OAuth connection routes."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.crm import DbSession
from app.config import get_settings
from app.modules.audit.models import AuditEvent
from app.modules.mailbox.gmail import (
    GMAIL_SCOPES,
    GmailProviderError,
    authorization_url,
    decrypt_refresh_token,
    encrypt_refresh_token,
    exchange_authorization_code,
    gmail_profile,
)
from app.modules.mailbox.models import MailboxConnection, OAuthAuthorizationState

router = APIRouter(tags=["mailbox"], include_in_schema=False)


def _redirect(status: str) -> RedirectResponse:
    return RedirectResponse(f"/settings?gmail={status}", status_code=303)


@router.get("/settings/gmail/connect")
async def connect_gmail(session: DbSession) -> RedirectResponse:
    settings = get_settings()
    if not settings.gmail_oauth_enabled:
        return _redirect("not_configured")
    state = token_urlsafe(48)
    session.add(
        OAuthAuthorizationState(
            provider="gmail",
            state_hash=sha256(state.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await session.commit()
    return RedirectResponse(authorization_url(settings, state), status_code=303)


@router.get("/auth/gmail/callback")
async def gmail_callback(
    request: Request,
    session: DbSession,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    settings = get_settings()
    request_id = str(getattr(request.state, "request_id", "gmail-oauth"))[:64]
    if error or not code or not state or not settings.gmail_oauth_enabled:
        return _redirect("cancelled" if error else "failed")
    stored = await session.scalar(
        select(OAuthAuthorizationState)
        .where(
            OAuthAuthorizationState.provider == "gmail",
            OAuthAuthorizationState.state_hash == sha256(state.encode()).hexdigest(),
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if stored is None or stored.consumed_at is not None or stored.expires_at <= now:
        return _redirect("state_invalid")
    stored.consumed_at = now
    await session.commit()
    try:
        token = await exchange_authorization_code(settings, code)
        if not set(GMAIL_SCOPES).issubset(token.scopes):
            raise GmailProviderError("gmail_required_scopes_missing")
        account_email = await gmail_profile(token.access_token)
        connection = await session.scalar(
            select(MailboxConnection).where(MailboxConnection.provider == "gmail")
        )
        if connection is None:
            connection = MailboxConnection(provider="gmail")
            session.add(connection)
        if token.refresh_token:
            connection.encrypted_refresh_token = encrypt_refresh_token(
                settings, token.refresh_token
            )
        if not connection.encrypted_refresh_token:
            raise GmailProviderError("gmail_refresh_token_missing")
        connection.account_email = account_email
        connection.status = "connected"
        connection.scopes = token.scopes
        connection.connected_at = now
        connection.disconnected_at = None
        connection.last_error_code = None
        session.add(
            AuditEvent(
                actor="primary_owner",
                action="gmail_mailbox_connected",
                entity_type="mailbox_connection",
                entity_id=str(connection.id),
                result="success",
                safe_diff={
                    "provider": "gmail",
                    "account_hash": sha256(account_email.casefold().encode()).hexdigest(),
                    "scopes": token.scopes,
                },
                request_id=request_id,
            )
        )
        await session.commit()
    except (GmailProviderError, httpx.HTTPError):
        await session.rollback()
        return _redirect("failed")
    finally:
        code = None
    return _redirect("connected")


@router.post("/settings/gmail/disconnect")
async def disconnect_gmail(request: Request, session: DbSession) -> RedirectResponse:
    settings = get_settings()
    connection = await session.scalar(
        select(MailboxConnection)
        .where(MailboxConnection.provider == "gmail")
        .with_for_update()
    )
    if connection is None:
        return _redirect("disconnected")
    refresh_token = ""
    if connection.encrypted_refresh_token:
        try:
            refresh_token = decrypt_refresh_token(
                settings, connection.encrypted_refresh_token
            )
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": refresh_token},
                )
        except (GmailProviderError, httpx.HTTPError):
            pass
        finally:
            refresh_token = ""
    connection.status = "disconnected"
    connection.encrypted_refresh_token = None
    connection.disconnected_at = datetime.now(UTC)
    connection.last_error_code = None
    session.add(
        AuditEvent(
            actor="primary_owner",
            action="gmail_mailbox_disconnected",
            entity_type="mailbox_connection",
            entity_id=str(connection.id),
            result="success",
            safe_diff={"provider": "gmail"},
            request_id=str(getattr(request.state, "request_id", "gmail-disconnect"))[:64],
        )
    )
    await session.commit()
    return _redirect("disconnected")
