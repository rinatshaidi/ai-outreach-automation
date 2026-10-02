"""Minimal Gmail OAuth, delivery, and thread-scoped reply synchronization."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from hashlib import sha256
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.crm.models import CommunicationEvent, Company
from app.modules.delivery.models import OutboundMessage
from app.modules.delivery.service import mask_email, recipient_hash
from app.modules.delivery.smtp import DeliveryProviderError, DeliveryReceipt
from app.modules.followups.service import cancel_open_followups
from app.modules.mailbox.models import InboundMessage, MailboxConnection

GMAIL_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint URL
GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)
MAX_REPLY_BODY_CHARS = 100_000


class GmailProviderError(DeliveryProviderError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GmailTokenResult:
    access_token: str
    refresh_token: str | None
    scopes: list[str]


def authorization_url(settings: Settings, state: str) -> str:
    if not settings.gmail_oauth_client_id:
        raise GmailProviderError("gmail_oauth_not_configured")
    query = urlencode(
        {
            "client_id": settings.gmail_oauth_client_id,
            "redirect_uri": settings.gmail_oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GMAIL_AUTHORIZE_URL}?{query}"


def _fernet(settings: Settings) -> Fernet:
    if settings.gmail_token_encryption_key is None:
        raise GmailProviderError("gmail_token_encryption_not_configured")
    try:
        return Fernet(settings.gmail_token_encryption_key.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise GmailProviderError("gmail_token_encryption_invalid") from exc


def encrypt_refresh_token(settings: Settings, token: str) -> str:
    return _fernet(settings).encrypt(token.encode()).decode("ascii")


def decrypt_refresh_token(settings: Settings, encrypted: str) -> str:
    try:
        return _fernet(settings).decrypt(encrypted.encode("ascii")).decode()
    except (InvalidToken, UnicodeError) as exc:
        raise GmailProviderError("gmail_refresh_token_unreadable") from exc


def _client_secret(settings: Settings) -> str:
    if not settings.gmail_oauth_client_secret:
        raise GmailProviderError("gmail_oauth_not_configured")
    return settings.gmail_oauth_client_secret.get_secret_value()


async def exchange_authorization_code(settings: Settings, code: str) -> GmailTokenResult:
    if not settings.gmail_oauth_client_id:
        raise GmailProviderError("gmail_oauth_not_configured")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            GMAIL_TOKEN_URL,
            data={
                "client_id": settings.gmail_oauth_client_id,
                "client_secret": _client_secret(settings),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.gmail_oauth_redirect_uri,
            },
        )
    if response.status_code >= 400:
        raise GmailProviderError("gmail_oauth_exchange_failed")
    payload = response.json()
    access_token = str(payload.get("access_token", ""))
    if not access_token:
        raise GmailProviderError("gmail_oauth_access_token_missing")
    return GmailTokenResult(
        access_token=access_token,
        refresh_token=payload.get("refresh_token"),
        scopes=str(payload.get("scope", "")).split(),
    )


async def refresh_access_token(settings: Settings, connection: MailboxConnection) -> str:
    if not settings.gmail_oauth_client_id or not connection.encrypted_refresh_token:
        raise GmailProviderError("gmail_connection_incomplete")
    refresh_token = decrypt_refresh_token(settings, connection.encrypted_refresh_token)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                GMAIL_TOKEN_URL,
                data={
                    "client_id": settings.gmail_oauth_client_id,
                    "client_secret": _client_secret(settings),
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
    finally:
        refresh_token = ""
    if response.status_code in {400, 401}:
        raise GmailProviderError("gmail_reauthorization_required")
    if response.status_code >= 400:
        raise GmailProviderError("gmail_token_refresh_failed")
    access_token = str(response.json().get("access_token", ""))
    if not access_token:
        raise GmailProviderError("gmail_access_token_missing")
    return access_token


async def gmail_profile(access_token: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GMAIL_API_ROOT}/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        raise GmailProviderError("gmail_profile_failed")
    email_address = str(response.json().get("emailAddress", "")).strip()
    if "@" not in email_address:
        raise GmailProviderError("gmail_profile_email_missing")
    return email_address


class GmailDeliveryAdapter:
    provider_name = "gmail-api"

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def send(
        self, *, recipient: str, subject: str, body: str
    ) -> DeliveryReceipt:
        connection = await self.session.scalar(
            select(MailboxConnection).where(
                MailboxConnection.provider == "gmail",
                MailboxConnection.status == "connected",
            )
        )
        if connection is None or not connection.account_email:
            raise GmailProviderError("gmail_not_connected")
        access_token = await refresh_access_token(self.settings, connection)
        message = EmailMessage()
        message["From"] = formataddr(
            (self.settings.smtp_from_name, connection.account_email)
        )
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{GMAIL_API_ROOT}/messages/send",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
        if response.status_code >= 400:
            raise GmailProviderError("gmail_send_failed")
        payload = response.json()
        message_id = str(payload.get("id", ""))
        if not message_id:
            raise GmailProviderError("gmail_send_response_invalid")
        return DeliveryReceipt(message_id, payload.get("threadId"))


def _header(message: dict[str, object], name: str) -> str:
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return ""
    headers = payload.get("headers", [])
    if not isinstance(headers, list):
        return ""
    for item in headers:
        if isinstance(item, dict) and str(item.get("name", "")).casefold() == name.casefold():
            return str(item.get("value", ""))
    return ""


def _decode_data(data: str) -> str:
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _plain_body(part: object) -> str:
    if not isinstance(part, dict):
        return ""
    mime_type = str(part.get("mimeType", ""))
    body = part.get("body")
    if mime_type == "text/plain" and isinstance(body, dict):
        return _decode_data(str(body.get("data", "")))
    parts = part.get("parts", [])
    if isinstance(parts, list):
        for child in parts:
            value = _plain_body(child)
            if value:
                return value
    return ""


def parse_gmail_reply(message: dict[str, object]) -> tuple[str, str, str, datetime]:
    sender = parseaddr(_header(message, "From"))[1].strip().casefold()
    subject = _header(message, "Subject").strip()[:500]
    body = _plain_body(message.get("payload"))[:MAX_REPLY_BODY_CHARS]
    try:
        received_at = datetime.fromtimestamp(int(str(message["internalDate"])) / 1000, UTC)
    except (KeyError, TypeError, ValueError, OSError):
        received_at = datetime.now(UTC)
    return sender, subject, body, received_at


async def sync_gmail_replies(session: AsyncSession, settings: Settings) -> int:
    if not settings.gmail_sync_enabled:
        return 0
    connection = await session.scalar(
        select(MailboxConnection).where(
            MailboxConnection.provider == "gmail",
            MailboxConnection.status == "connected",
        )
    )
    if connection is None or not connection.account_email:
        return 0
    access_token = await refresh_access_token(settings, connection)
    outbound = list(
        await session.scalars(
            select(OutboundMessage)
            .where(
                OutboundMessage.provider == "gmail-api",
                OutboundMessage.delivery_status == "sent",
                OutboundMessage.external_thread_id.is_not(None),
            )
            .order_by(OutboundMessage.sent_at.desc())
            .limit(settings.gmail_sync_batch_size)
        )
    )
    created = 0
    had_sync_error = False
    async with httpx.AsyncClient(timeout=30) as client:
        for original in outbound:
            response = await client.get(
                f"{GMAIL_API_ROOT}/threads/{original.external_thread_id}",
                params={"format": "full"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code >= 400:
                connection.last_error_code = "gmail_thread_sync_failed"
                had_sync_error = True
                continue
            messages = response.json().get("messages", [])
            for item in messages if isinstance(messages, list) else []:
                if not isinstance(item, dict):
                    continue
                provider_id = str(item.get("id", ""))
                if not provider_id or provider_id == original.external_message_id:
                    continue
                if await session.scalar(
                    select(InboundMessage.id).where(
                        InboundMessage.provider_message_id == provider_id
                    )
                ):
                    continue
                sender, subject, body, received_at = parse_gmail_reply(item)
                if "@" not in sender or sender == connection.account_email.casefold():
                    continue
                inbound = InboundMessage(
                    outbound_message_id=original.id,
                    company_id=original.company_id,
                    contact_id=original.contact_id,
                    provider_message_id=provider_id,
                    provider_thread_id=str(item.get("threadId", "")),
                    sender_hash=recipient_hash(sender),
                    sender_masked=mask_email(sender),
                    subject=subject,
                    body=body,
                    received_at=received_at,
                )
                session.add(inbound)
                await session.flush()
                company = await session.get(Company, original.company_id)
                if company:
                    company.pipeline_status = "replied"
                    company.next_action = "Review Gmail reply"
                    company.version += 1
                session.add(
                    CommunicationEvent(
                        company_id=original.company_id,
                        contact_id=original.contact_id,
                        event_type="inbound_reply",
                        occurred_at=received_at,
                        summary="Reply received through connected Gmail mailbox",
                        metadata_json={
                            "outbound_message_id": str(original.id),
                            "inbound_message_id": str(inbound.id),
                            "provider": "gmail-api",
                        },
                    )
                )
                await cancel_open_followups(
                    session,
                    reason="reply_received",
                    request_id="gmail-sync",
                    company_id=original.company_id,
                    contact_id=original.contact_id,
                )
                session.add(
                    AuditEvent(
                        actor="background_worker",
                        action="gmail_reply_synchronized",
                        entity_type="outbound_message",
                        entity_id=str(original.id),
                        result="success",
                        safe_diff={
                            "provider_message_hash": sha256(provider_id.encode()).hexdigest()
                        },
                        request_id="gmail-sync",
                    )
                )
                created += 1
    connection.last_sync_at = datetime.now(UTC)
    if not had_sync_error:
        connection.last_error_code = None
    await session.commit()
    return created


def scopes_json() -> str:
    return json.dumps(GMAIL_SCOPES)
