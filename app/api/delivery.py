"""Idempotent test and real email delivery with atomic approval consumption."""

import logging
import time
from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import add_event
from app.api.review import approval_validity, lineage
from app.config import Settings, get_settings
from app.infrastructure.db.session import get_db_session
from app.modules.audit.models import AuditEvent
from app.modules.candidate_profile.models import CandidateContact, CandidateFact, ConsentEvent
from app.modules.crm.models import Campaign, Company, Contact
from app.modules.delivery.models import DeliveryAttempt, OutboundMessage
from app.modules.delivery.schemas import DeliveryCreate, OutboundMessageRead
from app.modules.delivery.service import (
    SAFE_TEST_SMTP_HOSTS,
    VERIFIED_CONTACT_STATUSES,
    is_placeholder_email,
    mask_email,
    real_delivery_authenticated,
    recipient_hash,
)
from app.modules.delivery.smtp import (
    DeliveryProviderError,
    DeliveryReceipt,
    EmailDeliveryAdapter,
    SmtpDeliveryAdapter,
)
from app.modules.followups.service import schedule_followup
from app.modules.generation.models import DraftApproval, MessageDraft
from app.modules.mailbox.gmail import GmailDeliveryAdapter
from app.modules.safety.models import OwnerSafetyPolicy

logger = logging.getLogger("app.delivery")
router = APIRouter(prefix="/api/v1", tags=["delivery"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def get_real_email_adapter(settings: AppSettings, session: DbSession) -> EmailDeliveryAdapter:
    if settings.email_delivery_provider == "gmail":
        return GmailDeliveryAdapter(session, settings)
    return SmtpDeliveryAdapter(settings)


def get_test_email_adapter(settings: AppSettings) -> EmailDeliveryAdapter:
    return SmtpDeliveryAdapter(settings)


# Compatibility name for existing dependency overrides and callers.
get_email_adapter = get_real_email_adapter
RealEmailAdapter = Annotated[EmailDeliveryAdapter, Depends(get_real_email_adapter)]
TestEmailAdapter = Annotated[EmailDeliveryAdapter, Depends(get_test_email_adapter)]


async def active_consent(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
    scope: str,
) -> bool:
    event = await session.scalar(
        select(ConsentEvent)
        .where(
            ConsentEvent.entity_type == entity_type,
            ConsentEvent.entity_id == entity_id,
            ConsentEvent.data_scope == scope,
        )
        .order_by(ConsentEvent.granted_at.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    return bool(
        event
        and event.decision == "allowed"
        and (event.expires_at is None or event.expires_at > now)
    )


async def external_permissions_valid(session: AsyncSession, draft: MessageDraft) -> bool:
    fact_ids = [UUID(value) for value in draft.candidate_fact_ids]
    facts = list(
        await session.scalars(
            select(CandidateFact).where(CandidateFact.id.in_(fact_ids)).with_for_update()
        )
    )
    if len(facts) != len(fact_ids):
        return False
    for fact in facts:
        if not (
            fact.verified and fact.store_private and fact.use_in_draft and fact.send_externally
        ):
            return False
        if not await active_consent(
            session,
            entity_type="candidate_fact",
            entity_id=fact.id,
            scope="send_externally",
        ):
            return False

    signature_contacts = list(
        await session.scalars(
            select(CandidateContact).where(CandidateContact.use_in_signature.is_(True))
        )
    )
    used_signature_contacts = [item for item in signature_contacts if item.value in draft.body]
    for item in used_signature_contacts:
        if not (
            item.verified
            and item.store_private
            and item.use_in_draft
            and item.send_externally
            and item.use_in_signature
        ):
            return False
        if not await active_consent(
            session,
            entity_type="candidate_contact",
            entity_id=item.id,
            scope="send_externally",
        ):
            return False
    return True


async def existing_idempotent_message(
    session: AsyncSession,
    key: str,
    *,
    draft_id: UUID,
    approval_id: UUID,
    campaign_id: UUID,
    mode: str,
) -> OutboundMessage | None:
    existing = await session.scalar(
        select(OutboundMessage).where(OutboundMessage.idempotency_key == key)
    )
    if existing is None:
        return None
    if (
        existing.draft_id != draft_id
        or existing.approval_id != approval_id
        or existing.campaign_id != campaign_id
        or existing.delivery_mode != mode
    ):
        raise api_error(409, "idempotency_key_reused", "Idempotency key belongs to another send")
    return existing


async def deliver(
    *,
    draft_id: UUID,
    mode: str,
    payload: DeliveryCreate,
    idempotency_key: str,
    authorization: str | None,
    request: Request,
    session: AsyncSession,
    settings: Settings,
    adapter: EmailDeliveryAdapter,
) -> OutboundMessage:
    existing = await existing_idempotent_message(
        session,
        idempotency_key,
        draft_id=draft_id,
        approval_id=payload.approval_id,
        campaign_id=payload.campaign_id,
        mode=mode,
    )
    if existing:
        return existing

    approval = await session.scalar(
        select(DraftApproval).where(DraftApproval.id == payload.approval_id).with_for_update()
    )
    draft = await session.scalar(
        select(MessageDraft).where(MessageDraft.id == draft_id).with_for_update()
    )
    if approval is None or draft is None or approval.draft_id != draft.id:
        raise api_error(404, "approval_or_draft_not_found", "Approval or draft was not found")
    if not compare_digest(
        approval.one_time_token_hash,
        sha256(payload.approval_token.encode()).hexdigest(),
    ):
        raise api_error(403, "approval_token_invalid", "Approval token is invalid")
    revisions = await lineage(session, draft)
    valid, reason = await approval_validity(session, approval, revisions[0])
    if not valid:
        raise api_error(409, "approval_invalid", f"Approval is not valid: {reason}")
    if "\r" in draft.subject or "\n" in draft.subject:
        raise api_error(409, "invalid_subject", "Email subject contains a header separator")

    contact = await session.scalar(
        select(Contact).where(Contact.id == draft.contact_id).with_for_update()
    )
    campaign = await session.scalar(
        select(Campaign).where(Campaign.id == payload.campaign_id).with_for_update()
    )
    company = await session.scalar(
        select(Company).where(Company.id == draft.company_id).with_for_update()
    )
    if contact is None or campaign is None or company is None:
        raise api_error(409, "delivery_context_missing", "Delivery context is incomplete")
    if campaign.status != "active":
        raise api_error(409, "campaign_not_active", "Campaign must be active")
    if (
        contact.do_not_contact
        or contact.verification_status not in VERIFIED_CONTACT_STATUSES
    ):
        raise api_error(409, "contact_not_eligible", "Contact is unverified or suppressed")
    if mode == "test" and not (
        contact.email
        or (
            contact.validation_status == "VERIFIED_CONTACT"
            and contact.validated_at is not None
        )
    ):
        raise api_error(
            409,
            "contact_path_not_verified",
            "Test delivery requires a verified public contact path",
        )
    if company.pipeline_status != "approved":
        raise api_error(409, "draft_not_approved", "Company must be in approved review state")

    if mode == "real":
        if not contact.email:
            raise api_error(409, "email_missing", "Verified contact email is required")
        if not settings.allow_real_email:
            raise api_error(403, "real_email_disabled", "ALLOW_REAL_EMAIL is disabled")
        owner_policy = await session.scalar(
            select(OwnerSafetyPolicy).where(OwnerSafetyPolicy.owner_key == "primary")
        )
        if owner_policy is None or not owner_policy.real_send_enabled:
            raise api_error(
                403,
                "owner_real_send_disabled",
                "The owner has not enabled real external sending in Safety Control Center",
            )
        if settings.demo_mode:
            raise api_error(403, "demo_mode_blocks_real_email", "Demo mode blocks real email")
        if not real_delivery_authenticated(authorization, settings):
            raise api_error(401, "delivery_auth_required", "Valid delivery owner token is required")
        if is_placeholder_email(contact.email):
            raise api_error(
                409,
                "placeholder_email",
                "Placeholder addresses cannot receive real email",
            )
        if not await external_permissions_valid(session, draft):
            raise api_error(
                409,
                "external_consent_missing",
                "Candidate facts or signature contacts lack active external-send consent",
            )
        start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        sent_today = int(
            await session.scalar(
                select(func.count(OutboundMessage.id)).where(
                    OutboundMessage.campaign_id == campaign.id,
                    OutboundMessage.delivery_mode == "real",
                    OutboundMessage.delivery_status == "sent",
                    OutboundMessage.sent_at >= start_of_day,
                )
            )
            or 0
        )
        if sent_today >= campaign.daily_limit:
            raise api_error(409, "daily_limit_reached", "Campaign daily limit was reached")
        duplicate = await session.scalar(
            select(OutboundMessage.id).where(
                OutboundMessage.draft_id == draft.id,
                OutboundMessage.delivery_mode == "real",
                OutboundMessage.delivery_status == "sent",
            )
        )
        if duplicate:
            raise api_error(409, "draft_already_sent", "This draft revision was already sent")
        recipient = contact.email
    else:
        if not settings.smtp_test_mode or settings.smtp_host not in SAFE_TEST_SMTP_HOSTS:
            raise api_error(403, "mailpit_required", "Test send requires local Mailpit SMTP")
        recipient = settings.smtp_test_recipient

    request_id = str(getattr(request.state, "request_id", "missing-request-id"))
    message = OutboundMessage(
        company_id=company.id,
        contact_id=contact.id,
        campaign_id=campaign.id,
        draft_id=draft.id,
        approval_id=approval.id,
        direction="outbound",
        channel="email",
        delivery_mode=mode,
        recipient_hash=recipient_hash(recipient),
        recipient_masked=mask_email(recipient),
        subject=draft.subject,
        body=draft.body,
        delivery_status="pending",
        provider=adapter.provider_name,
        idempotency_key=idempotency_key,
    )
    session.add(message)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        existing = await existing_idempotent_message(
            session,
            idempotency_key,
            draft_id=draft_id,
            approval_id=payload.approval_id,
            campaign_id=payload.campaign_id,
            mode=mode,
        )
        if existing:
            return existing
        raise api_error(409, "idempotency_conflict", "Concurrent send conflict") from exc

    started = time.perf_counter()
    try:
        receipt = await adapter.send(
            recipient=recipient,
            subject=draft.subject,
            body=draft.body,
        )
    except DeliveryProviderError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        error_code = f"provider_{str(exc).casefold()}"[:80]
        message.delivery_status = "failed"
        message.safe_error_code = error_code
        session.add(
            DeliveryAttempt(
                message_id=message.id,
                attempt_number=1,
                result="failed",
                provider=adapter.provider_name,
                duration_ms=duration_ms,
                safe_error_code=error_code,
                request_id=request_id,
            )
        )
        session.add(
            AuditEvent(
                actor="primary_owner",
                action=f"{mode}_email_send",
                entity_type="message_draft",
                entity_id=str(draft.id),
                result="failed",
                safe_diff={"message_id": str(message.id), "safe_error_code": error_code},
                request_id=request_id,
            )
        )
        await session.commit()
        logger.warning(
            "delivery_failed",
            extra={"request_id": request_id, "entity_id": str(draft.id)},
        )
        raise api_error(
            502,
            "delivery_provider_failed",
            "The configured email provider rejected the message",
        ) from exc

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    sent_at = datetime.now(UTC)
    if isinstance(receipt, DeliveryReceipt):
        external_id = receipt.message_id
        external_thread_id = receipt.thread_id
    else:
        external_id = receipt
        external_thread_id = None
    message.delivery_status = "sent"
    message.external_message_id = external_id
    message.external_thread_id = external_thread_id
    message.sent_at = sent_at
    if mode == "real":
        approval.consumed_at = sent_at
        company.pipeline_status = "sent"
        company.next_action = "Wait for reply"
        company.version += 1
        await schedule_followup(
            session,
            message=message,
            campaign=campaign,
            timezone_name=settings.user_timezone,
        )
    else:
        company.next_action = "Mailpit test sent; real email not sent"
        company.version += 1
    session.add(
        DeliveryAttempt(
            message_id=message.id,
            attempt_number=1,
            result="sent",
            provider=adapter.provider_name,
            duration_ms=duration_ms,
            request_id=request_id,
        )
    )
    session.add(
        AuditEvent(
            actor="primary_owner",
            action=f"{mode}_email_send",
            entity_type="message_draft",
            entity_id=str(draft.id),
            result="success",
            safe_diff={
                "message_id": str(message.id),
                "mode": mode,
                "recipient_hash": message.recipient_hash,
            },
            request_id=request_id,
        )
    )
    add_event(
        session,
        company_id=company.id,
        contact_id=contact.id,
        event_type="test_email_sent" if mode == "test" else "email_sent",
        summary="Test email delivered to Mailpit" if mode == "test" else "Email sent",
        metadata={"message_id": str(message.id), "draft_id": str(draft.id)},
    )
    await session.commit()
    await session.refresh(message)
    return message


@router.post(
    "/drafts/{draft_id}/send-test",
    response_model=OutboundMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def send_test_email(
    draft_id: UUID,
    payload: DeliveryCreate,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    adapter: TestEmailAdapter,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)],
) -> OutboundMessage:
    return await deliver(
        draft_id=draft_id,
        mode="test",
        payload=payload,
        idempotency_key=idempotency_key,
        authorization=None,
        request=request,
        session=session,
        settings=settings,
        adapter=adapter,
    )


@router.post(
    "/drafts/{draft_id}/send",
    response_model=OutboundMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def send_real_email(
    draft_id: UUID,
    payload: DeliveryCreate,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    adapter: RealEmailAdapter,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)],
    authorization: Annotated[str | None, Header()] = None,
) -> OutboundMessage:
    return await deliver(
        draft_id=draft_id,
        mode="real",
        payload=payload,
        idempotency_key=idempotency_key,
        authorization=authorization,
        request=request,
        session=session,
        settings=settings,
        adapter=adapter,
    )


@router.get("/messages", response_model=list[OutboundMessageRead])
async def list_outbound_messages(session: DbSession) -> list[OutboundMessage]:
    return list(
        await session.scalars(
            select(OutboundMessage).order_by(OutboundMessage.created_at.desc()).limit(500)
        )
    )
