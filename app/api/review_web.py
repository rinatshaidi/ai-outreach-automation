"""Server-rendered Review Center and explicit owner actions."""

from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app.api.crm import DbSession
from app.api.delivery import deliver
from app.api.review import (
    approve_draft,
    change_draft_recipient,
    defer_draft,
    edit_draft,
    regenerate_draft,
    reject_draft,
    restore_deferred_draft,
    restore_draft_revision,
    restore_rejected_draft,
    review_draft,
)
from app.api.web import templates
from app.config import get_settings
from app.modules.crm.models import Campaign, Company, Contact, ContactChannel
from app.modules.delivery.models import OutboundMessage
from app.modules.delivery.schemas import DeliveryCreate
from app.modules.delivery.smtp import SmtpDeliveryAdapter
from app.modules.feedback.service import DRAFT_DECISIONS, record_owner_feedback
from app.modules.generation.models import DraftApproval, MessageDraft
from app.modules.generation.rewrite import AIRewriteProvider, get_ai_rewrite_provider
from app.modules.generation.schemas import (
    DraftEditCreate,
    DraftRecipientChange,
    DraftRegenerateCreate,
    DraftRestoreCreate,
    DraftReviewDecisionCreate,
)

router = APIRouter(include_in_schema=False)
MAILPIT_TEST_CAMPAIGN_NAME = "Local Pilot — Mailpit test"


def review_error_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        return str(exc.detail.get("code", "review_action_failed"))
    return "review_action_failed"


def review_error_redirect(
    draft_id: UUID,
    draft: MessageDraft | None,
    workspace: bool,
    exc: HTTPException,
) -> RedirectResponse:
    code = review_error_code(exc)
    if workspace and draft is not None:
        return RedirectResponse(
            f"/companies/{draft.company_id}?letter_error={code}#letter", status_code=303
        )
    return RedirectResponse(f"/review/{draft_id}?error={code}", status_code=303)


async def ensure_mailpit_test_campaign(session: DbSession) -> Campaign:
    """Keep delivery bookkeeping internal instead of exposing legacy campaigns in the UI."""

    campaign = await session.scalar(
        select(Campaign).where(Campaign.name == MAILPIT_TEST_CAMPAIGN_NAME)
    )
    if campaign is not None:
        if campaign.status != "active":
            campaign.status = "active"
            campaign.version += 1
            await session.flush()
        return campaign
    campaign = Campaign(
        name=MAILPIT_TEST_CAMPAIGN_NAME,
        goal="Internal test delivery to Mailpit only",
        criteria={"system_managed": True, "delivery_mode": "test"},
        opportunity_types=[],
        positioning_strategies=[],
        collaboration_formats=[],
        preferred_language="auto",
        tone_defaults="professional",
        daily_limit=100,
        followup_policy={"enabled": False},
        status="active",
    )
    session.add(campaign)
    await session.flush()
    return campaign


@router.get("/review", response_class=HTMLResponse)
async def review_center(request: Request, session: DbSession) -> HTMLResponse:
    drafts = list(
        await session.scalars(select(MessageDraft).order_by(MessageDraft.created_at.desc()))
    )
    latest: dict[tuple[UUID, str], MessageDraft] = {}
    for draft in drafts:
        key = (draft.company_id, draft.variant)
        if key not in latest:
            latest[key] = draft
    companies = {item.id: item for item in await session.scalars(select(Company))}
    contacts = {item.id: item for item in await session.scalars(select(Contact))}
    return templates.TemplateResponse(
        request=request,
        name="review_center.html",
        context={"drafts": list(latest.values()), "companies": companies, "contacts": contacts},
    )


@router.get("/review/{draft_id}", response_class=HTMLResponse)
async def review_detail(draft_id: UUID, request: Request, session: DbSession) -> HTMLResponse:
    detail = await review_draft(draft_id, session)
    viewed_id = request.query_params.get("view")
    viewed_revision = next(
        (item for item in detail.revisions if str(item.id) == viewed_id), detail.current
    )
    sibling_items = list(
        await session.scalars(
            select(MessageDraft)
            .where(
                MessageDraft.generation_run_id == detail.current.generation_run_id,
                MessageDraft.variant != detail.current.variant,
            )
            .order_by(MessageDraft.revision.desc(), MessageDraft.created_at.desc())
        )
    )
    alternative_variants: list[MessageDraft] = []
    seen_variants: set[str] = set()
    for item in sibling_items:
        if item.variant not in seen_variants:
            alternative_variants.append(item)
            seen_variants.add(item.variant)
    messages = list(
        await session.scalars(
            select(OutboundMessage)
            .where(OutboundMessage.draft_id == detail.current.id)
            .order_by(OutboundMessage.created_at.desc())
        )
    )
    company_contacts = list(
        await session.scalars(
            select(Contact)
            .where(Contact.company_id == detail.current.company_id)
            .order_by(Contact.decision_priority.asc().nullslast(), Contact.name)
        )
    )
    contact_channels: dict[UUID, ContactChannel] = {}
    for channel in await session.scalars(
        select(ContactChannel)
        .where(
            ContactChannel.contact_id.in_([item.id for item in company_contacts]),
            ContactChannel.validation_status == "VERIFIED",
        )
        .order_by(ContactChannel.confidence.desc(), ContactChannel.created_at)
    ):
        contact_channels.setdefault(channel.contact_id, channel)
    valid_approval = next((item for item in detail.approvals if item.valid), None)
    action_error = request.query_params.get("error")
    action_notice = request.query_params.get("notice")
    revision_kinds = {str(item.draft_id): item.action for item in detail.events}
    return templates.TemplateResponse(
        request=request,
        name="review_detail.html",
        context={
            "detail": detail,
            "messages": messages,
            "company_contacts": company_contacts,
            "contact_channels": contact_channels,
            "viewed_revision": viewed_revision,
            "is_historical": viewed_revision.id != detail.current.id,
            "valid_approval": valid_approval,
            "action_error": action_error,
            "action_notice": action_notice,
            "revision_kinds": revision_kinds,
            "ai_rewrite_provider": get_settings().ai_rewrite_provider,
            "alternative_variants": alternative_variants,
        },
    )


@router.post("/review/{draft_id}/edit")
async def save_draft_edit(
    draft_id: UUID,
    request: Request,
    session: DbSession,
    revision: Annotated[int, Form()],
    subject: Annotated[str, Form()],
    body: Annotated[str, Form()],
    comment: Annotated[str | None, Form()] = None,
    workspace: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    source_draft = await session.get(MessageDraft, draft_id)
    try:
        new_draft = await edit_draft(
            draft_id,
            DraftEditCreate(revision=revision, subject=subject, body=body, comment=comment),
            request,
            session,
        )
    except HTTPException as exc:
        return review_error_redirect(draft_id, source_draft, workspace, exc)
    if workspace:
        return RedirectResponse(
            f"/companies/{new_draft.company_id}?letter_notice=saved#letter", status_code=303
        )
    return RedirectResponse(f"/review/{new_draft.id}", status_code=303)


@router.post("/review/{draft_id}/feedback")
async def save_draft_feedback(
    draft_id: UUID,
    session: DbSession,
    decision: Annotated[str, Form()],
    reason: Annotated[str | None, Form()] = None,
    comment: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    draft = await session.get(MessageDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        await record_owner_feedback(
            session,
            category="draft_owner_feedback",
            decision=decision,
            allowed_decisions=DRAFT_DECISIONS,
            reason=reason,
            comment=comment,
            company_id=draft.company_id,
            context={
                "draft_id": str(draft.id),
                "variant": draft.variant,
                "tone": draft.tone,
                "revision": draft.revision,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/review/{draft_id}?feedback=saved#learning", status_code=303)


@router.post("/review/{draft_id}/regenerate")
async def save_draft_regenerate(
    draft_id: UUID,
    request: Request,
    session: DbSession,
    provider: Annotated[AIRewriteProvider, Depends(get_ai_rewrite_provider)],
    revision: Annotated[int, Form()],
    campaign_goal: Annotated[str, Form()],
    language: Annotated[str, Form()] = "same",
    comment: Annotated[str | None, Form()] = None,
    workspace: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    source_draft = await session.get(MessageDraft, draft_id)
    try:
        new_draft = await regenerate_draft(
            draft_id,
            DraftRegenerateCreate(
                revision=revision,
                campaign_goal=campaign_goal,
                language=language,
                comment=comment,
            ),
            request,
            session,
            provider,
        )
    except HTTPException as exc:
        code = (
            exc.detail.get("code", "ai_rewrite_failed")
            if isinstance(exc.detail, dict)
            else "ai_rewrite_failed"
        )
        if workspace and source_draft is not None:
            return RedirectResponse(
                f"/companies/{source_draft.company_id}?letter_error={code}#letter",
                status_code=303,
            )
        return RedirectResponse(f"/review/{draft_id}?error={code}", status_code=303)
    if workspace:
        return RedirectResponse(
            f"/companies/{new_draft.company_id}?letter_notice=ai_rewritten#letter",
            status_code=303,
        )
    return RedirectResponse(f"/review/{new_draft.id}", status_code=303)


@router.post("/review/{draft_id}/restore")
async def save_revision_restore(
    draft_id: UUID,
    request: Request,
    session: DbSession,
    revision: Annotated[int, Form()],
    source_draft_id: Annotated[UUID, Form()],
    comment: Annotated[str | None, Form()] = None,
    workspace: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    source_draft = await session.get(MessageDraft, draft_id)
    try:
        new_draft = await restore_draft_revision(
            draft_id,
            DraftRestoreCreate(
                revision=revision,
                source_draft_id=source_draft_id,
                confirmed=True,
                comment=comment,
            ),
            request,
            session,
        )
    except HTTPException as exc:
        return review_error_redirect(draft_id, source_draft, workspace, exc)
    if workspace:
        return RedirectResponse(
            f"/companies/{new_draft.company_id}?letter_notice=revision_restored#letter",
            status_code=303,
        )
    return RedirectResponse(f"/review/{new_draft.id}?notice=revision_restored", status_code=303)


@router.post("/review/{draft_id}/recipient")
async def save_draft_recipient(
    draft_id: UUID,
    request: Request,
    session: DbSession,
    revision: Annotated[int, Form()],
    contact_id: Annotated[UUID, Form()],
    confirmed: Annotated[bool, Form()] = False,
    comment: Annotated[str | None, Form()] = None,
    workspace: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    source_draft = await session.get(MessageDraft, draft_id)
    try:
        new_draft = await change_draft_recipient(
            draft_id,
            DraftRecipientChange(
                revision=revision,
                contact_id=contact_id,
                confirmed=confirmed,
                comment=comment,
            ),
            request,
            session,
        )
    except HTTPException as exc:
        return review_error_redirect(draft_id, source_draft, workspace, exc)
    if workspace:
        return RedirectResponse(
            f"/companies/{new_draft.company_id}?letter_notice=recipient_changed#letter",
            status_code=303,
        )
    return RedirectResponse(f"/review/{new_draft.id}", status_code=303)


async def decision_payload(revision: int, comment: str | None) -> DraftReviewDecisionCreate:
    return DraftReviewDecisionCreate(revision=revision, confirmed=True, comment=comment)


@router.post("/review/{draft_id}/approve")
async def save_draft_approval(
    draft_id: UUID,
    request: Request,
    session: DbSession,
    revision: Annotated[int, Form()],
    comment: Annotated[str | None, Form()] = None,
    workspace: Annotated[bool, Form()] = False,
) -> Response:
    source_draft = await session.get(MessageDraft, draft_id)
    try:
        await approve_draft(
            draft_id, await decision_payload(revision, comment), request, session
        )
    except HTTPException as exc:
        return review_error_redirect(draft_id, source_draft, workspace, exc)
    if workspace:
        draft = await session.get(MessageDraft, draft_id)
        if draft is not None:
            return RedirectResponse(
                f"/companies/{draft.company_id}?letter_notice=approved#letter", status_code=303
            )
    return RedirectResponse(f"/review/{draft_id}?notice=approved", status_code=303)


@router.post("/review/{draft_id}/send-test")
async def save_test_delivery(
    draft_id: UUID,
    request: Request,
    session: DbSession,
    campaign_id: Annotated[UUID | None, Form()] = None,
    workspace: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    settings = get_settings()
    approval = await session.scalar(
        select(DraftApproval).where(
            DraftApproval.draft_id == draft_id,
            DraftApproval.invalidated_at.is_(None),
            DraftApproval.consumed_at.is_(None),
        )
    )
    if approval is None:
        if workspace:
            draft = await session.get(MessageDraft, draft_id)
            if draft is not None:
                return RedirectResponse(
                    f"/companies/{draft.company_id}?letter_error=approval_required#letter",
                    status_code=303,
                )
        return RedirectResponse(
            f"/review/{draft_id}?error=approval_required", status_code=303
        )
    approval_token = token_urlsafe(32)
    approval.one_time_token_hash = sha256(approval_token.encode()).hexdigest()
    campaign = (
        await session.get(Campaign, campaign_id)
        if campaign_id is not None
        else await ensure_mailpit_test_campaign(session)
    )
    if campaign is None or campaign.status != "active":
        campaign = await ensure_mailpit_test_campaign(session)
    await session.flush()
    await deliver(
        draft_id=draft_id,
        mode="test",
        payload=DeliveryCreate(
            approval_id=approval.id,
            approval_token=approval_token,
            campaign_id=campaign.id,
        ),
        idempotency_key=f"web-test-{uuid4()}",
        authorization=None,
        request=request,
        session=session,
        settings=settings,
        adapter=SmtpDeliveryAdapter(settings),
    )
    if workspace:
        draft = await session.get(MessageDraft, draft_id)
        if draft is not None:
            return RedirectResponse(
                f"/companies/{draft.company_id}?letter_notice=test_delivered#activity",
                status_code=303,
            )
    return RedirectResponse("/letters?tab=sent", status_code=303)


@router.post("/review/{draft_id}/{action}")
async def save_nonapproval_review_action(
    draft_id: UUID,
    action: str,
    request: Request,
    session: DbSession,
    revision: Annotated[int, Form()],
    comment: Annotated[str | None, Form()] = None,
    workspace: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    source_draft = await session.get(MessageDraft, draft_id)
    payload = await decision_payload(revision, comment)
    try:
        if action == "defer":
            await defer_draft(draft_id, payload, request, session)
        elif action == "reject":
            await reject_draft(draft_id, payload, request, session)
        elif action == "restore-deferred":
            await restore_deferred_draft(draft_id, payload, request, session)
        elif action == "restore-rejected":
            await restore_rejected_draft(draft_id, payload, request, session)
        else:
            return RedirectResponse(f"/review/{draft_id}", status_code=303)
    except HTTPException as exc:
        return review_error_redirect(draft_id, source_draft, workspace, exc)
    if workspace and source_draft is not None:
        notice = {
            "defer": "deferred",
            "reject": "rejected",
            "restore-deferred": "restored",
            "restore-rejected": "restored",
        }.get(action, action)
        return RedirectResponse(
            f"/companies/{source_draft.company_id}?letter_notice={notice}#letter",
            status_code=303,
        )
    if action == "defer":
        return RedirectResponse("/letters?tab=deferred", status_code=303)
    if action == "restore-deferred":
        return RedirectResponse("/letters?tab=drafts", status_code=303)
    if action == "restore-rejected":
        return RedirectResponse("/letters?tab=drafts", status_code=303)
    if action == "reject":
        return RedirectResponse("/letters?tab=closed", status_code=303)
    return RedirectResponse("/letters?tab=drafts", status_code=303)
