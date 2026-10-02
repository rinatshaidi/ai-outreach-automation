"""Revision-safe Review Center with explicit, one-time draft approvals."""

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import add_event
from app.infrastructure.db.session import get_db_session
from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateFact,
    CandidateProfile,
    CandidateRule,
)
from app.modules.crm.models import Company, CompanySource, Contact, ContactChannel
from app.modules.followups.service import cancel_open_followups
from app.modules.generation.models import (
    ApprovedWritingExample,
    DraftApproval,
    DraftReviewEvent,
    GenerationRun,
    MessageDraft,
    SenderVoiceProfile,
)
from app.modules.generation.rewrite import (
    AIRewriteFailed,
    AIRewriteProvider,
    AIRewriteUnavailable,
    get_ai_rewrite_provider,
)
from app.modules.generation.schemas import (
    AdapterDraft,
    DraftApprovalRead,
    DraftEditCreate,
    DraftRecipientChange,
    DraftRegenerateCreate,
    DraftRestoreCreate,
    DraftReviewDecisionCreate,
    DraftReviewEventRead,
    DraftStatus,
    MessageDraftRead,
    ReviewDraftDetail,
)
from app.modules.generation.service import (
    MODEL,
    PROVIDER,
    GenerationContext,
    LanguageChoice,
    LocalStructuredGenerationAdapter,
    content_hash,
    primary_match_fingerprint,
    validate_draft,
)
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunitySignal,
    PositioningRecommendation,
)
from app.modules.opportunities.readiness import is_source_backed_opportunity
from app.modules.research.models import CompanyFact
from app.modules.research.synthesis import (
    draft_primary_match_for_contact,
    get_or_build_decision_synthesis,
)

router = APIRouter(prefix="/api/v1", tags=["review-center"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def uuids(values: list[str]) -> list[UUID]:
    return [UUID(value) for value in values]


async def draft_or_404(session: AsyncSession, draft_id: UUID) -> MessageDraft:
    draft = await session.get(MessageDraft, draft_id)
    if draft is None:
        raise api_error(404, "draft_not_found", "Draft was not found")
    return draft


async def lineage(session: AsyncSession, draft: MessageDraft) -> list[MessageDraft]:
    return list(
        await session.scalars(
            select(MessageDraft)
            .where(
                MessageDraft.generation_run_id == draft.generation_run_id,
                MessageDraft.variant == draft.variant,
            )
            .order_by(MessageDraft.revision.desc())
        )
    )


async def require_latest(
    session: AsyncSession, draft: MessageDraft, supplied_revision: int
) -> None:
    revisions = await lineage(session, draft)
    latest = revisions[0]
    if draft.id != latest.id or supplied_revision != draft.revision:
        raise api_error(
            409,
            "stale_draft_revision",
            "Only the latest draft revision can be reviewed or changed",
        )


async def build_context(
    session: AsyncSession,
    draft: MessageDraft,
    *,
    campaign_goal: str,
) -> GenerationContext:
    company = cast(Company, await session.get(Company, draft.company_id))
    contact = cast(Contact, await session.get(Contact, draft.contact_id))
    recommendation = cast(
        PositioningRecommendation,
        await session.get(PositioningRecommendation, draft.recommendation_id),
    )
    candidate_facts = list(
        await session.scalars(
            select(CandidateFact).where(
                CandidateFact.id.in_(uuids(draft.candidate_fact_ids)),
                CandidateFact.verified.is_(True),
                CandidateFact.store_private.is_(True),
                CandidateFact.use_in_draft.is_(True),
            )
        )
    )
    company_facts = list(
        await session.scalars(
            select(CompanyFact).where(
                CompanyFact.id.in_(uuids(draft.company_fact_ids)),
                CompanyFact.status == "verified",
            )
        )
    )
    opportunities = list(
        await session.scalars(
            select(CompanyOpportunity).where(
                CompanyOpportunity.id.in_(uuids(draft.opportunity_type_ids)),
                CompanyOpportunity.status != "rejected",
            )
        )
    )
    opportunities = [item for item in opportunities if is_source_backed_opportunity(item)]
    signals = list(
        await session.scalars(
            select(OpportunitySignal).where(
                OpportunitySignal.id.in_(uuids(draft.opportunity_signal_ids)),
                OpportunitySignal.status == "verified",
            )
        )
    )
    signature_contacts = list(
        await session.scalars(
            select(CandidateContact).where(
                CandidateContact.verified.is_(True),
                CandidateContact.store_private.is_(True),
                CandidateContact.use_in_draft.is_(True),
                CandidateContact.use_in_signature.is_(True),
            )
        )
    )
    rules = list(
        await session.scalars(
            select(CandidateRule)
            .where(CandidateRule.active.is_(True))
            .order_by(CandidateRule.priority)
        )
    )
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    sender_voice_profile = (
        await session.scalar(
            select(SenderVoiceProfile).where(
                SenderVoiceProfile.candidate_profile_id == profile.id,
                SenderVoiceProfile.active.is_(True),
            )
        )
        if profile is not None
        else None
    )
    approved_examples = (
        list(
            await session.scalars(
                select(ApprovedWritingExample).where(
                    ApprovedWritingExample.sender_voice_profile_id == sender_voice_profile.id,
                    ApprovedWritingExample.approved.is_(True),
                    ApprovedWritingExample.language == draft.language,
                )
            )
        )
        if sender_voice_profile is not None
        else []
    )
    return GenerationContext(
        company=company,
        contact=contact,
        recommendation=recommendation,
        opportunities=opportunities,
        signals=signals,
        company_facts=company_facts,
        candidate_facts=candidate_facts,
        signature_contacts=signature_contacts,
        rules=rules,
        language=LanguageChoice(
            draft.language,
            draft.language_confidence,
            draft.language_reason,
            any("Language fallback" in item for item in draft.warnings),
        ),
        campaign_goal=campaign_goal,
        prompt_version=draft.prompt_version,
        min_words=100,
        max_words=250,
        sender_name=(profile.display_name if profile and profile.display_name else ""),
        sender_voice_profile=sender_voice_profile,
        approved_examples=approved_examples,
    )


def adapter_draft(draft: MessageDraft, subject: str, body: str) -> AdapterDraft:
    return AdapterDraft(
        variant=draft.variant,
        message_format=draft.message_format,
        tone=draft.tone,
        subject=subject,
        body=body,
        language=draft.language,
        explanation=draft.explanation,
        opportunity_type_ids=draft.opportunity_type_ids,
        opportunity_signal_ids=draft.opportunity_signal_ids,
        positioning_strategy=draft.positioning_strategy,
        collaboration_format=draft.collaboration_format,
        value_proposition=draft.value_proposition,
        candidate_fact_ids=draft.candidate_fact_ids,
        company_fact_ids=draft.company_fact_ids,
        source_ids=draft.source_ids,
        warnings=draft.warnings,
    )


async def invalidate_lineage_approvals(
    session: AsyncSession, draft: MessageDraft, reason: str
) -> None:
    revisions = await lineage(session, draft)
    approvals = list(
        await session.scalars(
            select(DraftApproval).where(
                DraftApproval.draft_id.in_([item.id for item in revisions]),
                DraftApproval.invalidated_at.is_(None),
                DraftApproval.consumed_at.is_(None),
            )
        )
    )
    now = datetime.now(UTC)
    for approval in approvals:
        approval.invalidated_at = now
        approval.invalidation_reason = reason


async def persist_revision(
    session: AsyncSession,
    source: MessageDraft,
    generated: AdapterDraft,
    context: GenerationContext,
    request: Request,
    *,
    action: str,
    comment: str | None,
    provider: str,
    model: str,
    contact_override: Contact | None = None,
) -> MessageDraft:
    report = validate_draft(
        generated,
        context,
        outreach_allowed=context.recommendation.user_decision == "outreach",
    )
    revision = MessageDraft(
        generation_run_id=source.generation_run_id,
        company_id=source.company_id,
        contact_id=(contact_override or context.contact).id,
        contact_version=(contact_override or context.contact).version,
        recommendation_id=source.recommendation_id,
        assessment_id=source.assessment_id,
        revision=source.revision + 1,
        variant=generated.variant.value,
        message_format=generated.message_format.value,
        tone=generated.tone.value,
        status=DraftStatus.READY.value if report.passed else DraftStatus.BLOCKED.value,
        subject=generated.subject,
        body=generated.body,
        language=generated.language,
        language_confidence=context.language.confidence,
        language_reason=context.language.reason,
        explanation=generated.explanation,
        opportunity_type_ids=[str(item) for item in generated.opportunity_type_ids],
        opportunity_signal_ids=[str(item) for item in generated.opportunity_signal_ids],
        positioning_strategy=generated.positioning_strategy,
        collaboration_format=generated.collaboration_format,
        value_proposition=generated.value_proposition,
        candidate_fact_ids=[str(item) for item in generated.candidate_fact_ids],
        company_fact_ids=[str(item) for item in generated.company_fact_ids],
        source_ids=[str(item) for item in generated.source_ids],
        warnings=generated.warnings,
        validation_report=report.model_dump(mode="json"),
        word_count=len(generated.body.split()),
        prompt_version=context.prompt_version,
        provider=provider,
        model=model,
        content_hash=content_hash(generated.subject, generated.body),
    )
    # A browser can submit the same action twice before it follows the first
    # redirect.  The database constraint is the final guard for a lineage;
    # translate that expected race into the same stale-version response the UI
    # already understands, rather than leaking a 500 error.
    try:
        async with session.begin_nested():
            session.add(revision)
            await session.flush()
    except IntegrityError as exc:
        if "uq_message_draft_run_variant_revision" in str(exc):
            raise api_error(
                409,
                "stale_draft_revision",
                "This draft was updated. Open the latest version and try again.",
            ) from exc
        raise

    await invalidate_lineage_approvals(session, source, "draft_revision_changed")
    request_id = str(getattr(request.state, "request_id", "missing-request-id"))
    session.add(
        DraftReviewEvent(
            company_id=source.company_id,
            draft_id=revision.id,
            action=action,
            actor="primary_owner",
            comment=comment,
            safe_diff={
                "from_revision": source.revision,
                "to_revision": revision.revision,
                "old_hash": source.content_hash,
                "new_hash": revision.content_hash,
                "contact_changed": contact_override is not None,
            },
            request_id=request_id,
        )
    )
    company = context.company
    company.pipeline_status = "review"
    company.next_action = (
        "Resolve draft blockers" if not report.passed else "Review current revision"
    )
    company.version += 1
    add_event(
        session,
        company_id=source.company_id,
        contact_id=revision.contact_id,
        event_type=f"draft_{action}",
        summary=f"Draft {source.variant} revision {revision.revision}: {action}",
        metadata={"draft_id": str(revision.id), "content_hash": revision.content_hash},
    )
    await session.commit()
    await session.refresh(revision)
    return revision


async def approval_validity(
    session: AsyncSession, approval: DraftApproval, latest: MessageDraft
) -> tuple[bool, str]:
    draft = cast(MessageDraft | None, await session.get(MessageDraft, approval.draft_id))
    if draft is None:
        return False, "draft_missing"
    if approval.invalidated_at:
        return False, approval.invalidation_reason or "invalidated"
    if approval.consumed_at:
        return False, "already_consumed"
    if draft.id != latest.id or approval.draft_revision != latest.revision:
        return False, "not_current_revision"
    if draft.content_hash != content_hash(draft.subject, draft.body):
        return False, "content_hash_mismatch"
    contact = cast(Contact | None, await session.get(Contact, draft.contact_id))
    if contact is None or contact.version != draft.contact_version:
        return False, "contact_changed"
    if contact.do_not_contact or contact.verification_status not in {
        "verified",
        "verified_public",
        "provider_verified",
    }:
        return False, "contact_not_eligible"
    allowed_fact_ids = set(
        await session.scalars(
            select(CandidateFact.id).where(
                CandidateFact.id.in_(uuids(draft.candidate_fact_ids)),
                CandidateFact.verified.is_(True),
                CandidateFact.store_private.is_(True),
                CandidateFact.use_in_draft.is_(True),
            )
        )
    )
    if allowed_fact_ids != set(uuids(draft.candidate_fact_ids)):
        return False, "candidate_permission_changed"
    if draft.status != "ready" or not draft.validation_report.get("passed", False):
        return False, "draft_validation_failed"
    return True, "valid_for_one_delivery_attempt"


async def approval_read(
    session: AsyncSession,
    approval: DraftApproval,
    latest: MessageDraft,
    *,
    token: str | None = None,
) -> DraftApprovalRead:
    valid, reason = await approval_validity(session, approval, latest)
    values = DraftApprovalRead.model_validate(approval).model_dump()
    values.update(valid=valid, validity_reason=reason, approval_token=token)
    return DraftApprovalRead.model_validate(values)


@router.get("/drafts", response_model=list[MessageDraftRead])
async def review_drafts(session: DbSession) -> list[MessageDraft]:
    drafts = list(
        await session.scalars(select(MessageDraft).order_by(MessageDraft.created_at.desc()))
    )
    latest: dict[tuple[UUID, str], MessageDraft] = {}
    for draft in drafts:
        key = (draft.generation_run_id, draft.variant)
        if key not in latest or draft.revision > latest[key].revision:
            latest[key] = draft
    return sorted(latest.values(), key=lambda item: item.created_at, reverse=True)


@router.get("/drafts/{draft_id}", response_model=ReviewDraftDetail)
async def review_draft(draft_id: UUID, session: DbSession) -> ReviewDraftDetail:
    draft = await draft_or_404(session, draft_id)
    revisions = await lineage(session, draft)
    current = revisions[0]
    company = cast(Company, await session.get(Company, current.company_id))
    contact = cast(Contact, await session.get(Contact, current.contact_id))
    recommendation = cast(
        PositioningRecommendation,
        await session.get(PositioningRecommendation, current.recommendation_id),
    )
    approvals = list(
        await session.scalars(
            select(DraftApproval)
            .where(DraftApproval.draft_id.in_([item.id for item in revisions]))
            .order_by(DraftApproval.approved_at.desc())
        )
    )
    events = list(
        await session.scalars(
            select(DraftReviewEvent)
            .where(DraftReviewEvent.draft_id.in_([item.id for item in revisions]))
            .order_by(DraftReviewEvent.created_at.desc())
        )
    )
    sources = list(
        await session.scalars(
            select(CompanySource).where(CompanySource.id.in_(uuids(current.source_ids)))
        )
    )
    facts = list(
        await session.scalars(
            select(CandidateFact).where(CandidateFact.id.in_(uuids(current.candidate_fact_ids)))
        )
    )
    return ReviewDraftDetail(
        current=MessageDraftRead.model_validate(current),
        revisions=[MessageDraftRead.model_validate(item) for item in revisions],
        approvals=[await approval_read(session, item, current) for item in approvals],
        events=[DraftReviewEventRead.model_validate(item) for item in events],
        company_name=company.name,
        contact_name=contact.name,
        relevance_score=company.relevance_score,
        positioning_context={
            "strategy": recommendation.primary_strategy,
            "role": recommendation.possible_role,
            "collaboration_format": recommendation.collaboration_format,
            "value_proposition": recommendation.value_proposition,
        },
        sources=[
            {
                "id": str(item.id),
                "url": item.url,
                "trust_level": item.trust_level,
                "freshness_status": item.freshness_status,
            }
            for item in sources
        ],
        candidate_permissions=[
            {
                "id": str(item.id),
                "fact_type": item.fact_type,
                "verified": item.verified,
                "store_private": item.store_private,
                "use_in_draft": item.use_in_draft,
                "use_in_signature": item.use_in_signature,
            }
            for item in facts
        ],
    )


@router.post("/drafts/{draft_id}/edit", response_model=MessageDraftRead, status_code=201)
async def edit_draft(
    draft_id: UUID,
    payload: DraftEditCreate,
    request: Request,
    session: DbSession,
) -> MessageDraft:
    source = await draft_or_404(session, draft_id)
    await require_latest(session, source, payload.revision)
    context = await build_context(session, source, campaign_goal="Owner-edited outreach draft")
    generated = adapter_draft(source, payload.subject, payload.body)
    return await persist_revision(
        session,
        source,
        generated,
        context,
        request,
        action="edited",
        comment=payload.comment,
        provider="owner-editor",
        model="manual-revision",
    )


@router.post("/drafts/{draft_id}/regenerate", response_model=MessageDraftRead, status_code=201)
async def regenerate_draft(
    draft_id: UUID,
    payload: DraftRegenerateCreate,
    request: Request,
    session: DbSession,
    provider: Annotated[AIRewriteProvider, Depends(get_ai_rewrite_provider)],
) -> MessageDraft:
    source = await draft_or_404(session, draft_id)
    await require_latest(session, source, payload.revision)
    context = await build_context(session, source, campaign_goal=payload.campaign_goal)
    context = replace(context, prompt_version="outreach-generation-v2")
    if payload.language != "same":
        context = replace(
            context,
            language=LanguageChoice(
                payload.language,
                1.0,
                "Explicit owner selection during regeneration",
                False,
            ),
        )
    try:
        rewritten = await provider.rewrite(
            context=context,
            subject=source.subject,
            body=source.body,
            instruction=payload.campaign_goal,
            message_format=source.message_format,
            tone=source.tone,
        )
    except AIRewriteUnavailable as exc:
        raise api_error(503, "ai_rewrite_unavailable", str(exc)) from exc
    except AIRewriteFailed as exc:
        raise api_error(502, exc.code, str(exc)) from exc
    generated = adapter_draft(source, rewritten.subject, rewritten.body)
    return await persist_revision(
        session,
        source,
        generated,
        context,
        request,
        action="ai_rewritten",
        comment=payload.comment,
        provider=provider.provider_name,
        model=provider.model_name,
    )


@router.post("/drafts/{draft_id}/restore", response_model=MessageDraftRead, status_code=201)
async def restore_draft_revision(
    draft_id: UUID,
    payload: DraftRestoreCreate,
    request: Request,
    session: DbSession,
) -> MessageDraft:
    current = await draft_or_404(session, draft_id)
    await require_latest(session, current, payload.revision)
    source = await draft_or_404(session, payload.source_draft_id)
    if (
        source.generation_run_id != current.generation_run_id
        or source.variant != current.variant
    ):
        raise api_error(409, "revision_lineage_mismatch", "Revision belongs to another draft")
    if source.id == current.id:
        raise api_error(409, "revision_already_current", "Selected revision is already current")
    context = await build_context(
        session,
        current,
        campaign_goal="Owner restored a previous revision",
    )
    generated = adapter_draft(current, source.subject, source.body)
    return await persist_revision(
        session,
        current,
        generated,
        context,
        request,
        action="restored",
        comment=payload.comment or f"Restored revision {source.revision}",
        provider="owner-history",
        model="revision-restore",
    )


@router.post("/drafts/{draft_id}/recipient", response_model=MessageDraftRead, status_code=201)
async def change_draft_recipient(
    draft_id: UUID,
    payload: DraftRecipientChange,
    request: Request,
    session: DbSession,
) -> MessageDraft:
    source = await draft_or_404(session, draft_id)
    await require_latest(session, source, payload.revision)
    contact = cast(Contact | None, await session.get(Contact, payload.contact_id))
    if contact is None or contact.company_id != source.company_id:
        raise api_error(404, "recipient_not_found", "Recipient does not belong to this company")
    verified_channel = await session.scalar(
        select(ContactChannel.id).where(
            ContactChannel.contact_id == contact.id,
            ContactChannel.validation_status == "VERIFIED",
        )
    )
    has_verified_path = bool(
        contact.validation_status == "VERIFIED_CONTACT"
        and contact.validated_at is not None
        and verified_channel is not None
    )
    if (
        contact.do_not_contact
        or contact.verification_status
        not in {"verified", "verified_public", "provider_verified"}
        or not (has_verified_path or contact.email)
    ):
        raise api_error(409, "recipient_not_eligible", "Recipient must be verified and contactable")
    context = await build_context(session, source, campaign_goal="Recipient change revalidation")
    context = replace(context, contact=contact)
    generated_items = await LocalStructuredGenerationAdapter().generate(context)
    generated = next(item for item in generated_items if item.variant.value == source.variant)
    return await persist_revision(
        session,
        source,
        generated,
        context,
        request,
        action="recipient_changed",
        comment=payload.comment,
        provider=PROVIDER,
        model=MODEL,
        contact_override=contact,
    )


@router.post(
    "/drafts/{draft_id}/approve",
    response_model=DraftApprovalRead,
    status_code=status.HTTP_201_CREATED,
)
async def approve_draft(
    draft_id: UUID,
    payload: DraftReviewDecisionCreate,
    request: Request,
    session: DbSession,
) -> DraftApprovalRead:
    draft = await draft_or_404(session, draft_id)
    await require_latest(session, draft, payload.revision)
    context = await build_context(session, draft, campaign_goal="Approval revalidation")
    run = await session.get(GenerationRun, draft.generation_run_id)
    synthesis = await get_or_build_decision_synthesis(
        session, context.company, locale=draft.language
    )
    current_primary = draft_primary_match_for_contact(
        synthesis.payload, context.contact, draft.language
    )
    current_fingerprint = primary_match_fingerprint(current_primary)
    stored_fingerprint = str(
        (run.input_entity_ids or {}).get("primary_match_fingerprint", "") if run else ""
    )
    if not current_fingerprint or current_fingerprint != stored_fingerprint:
        raise api_error(
            409,
            "draft_analysis_updated",
            "The current analysis changed; generate a new draft set before approval",
        )
    report = validate_draft(
        adapter_draft(draft, draft.subject, draft.body),
        context,
        outreach_allowed=context.recommendation.user_decision == "outreach",
    )
    if not report.passed or draft.status != "ready":
        raise api_error(409, "draft_blocked", "Only a currently valid ready draft can be approved")
    if draft.content_hash != content_hash(draft.subject, draft.body):
        raise api_error(409, "content_hash_mismatch", "Draft content no longer matches its hash")
    existing = await session.scalar(
        select(DraftApproval).where(
            DraftApproval.draft_id == draft.id,
            DraftApproval.invalidated_at.is_(None),
            DraftApproval.consumed_at.is_(None),
        )
    )
    if existing:
        raise api_error(409, "approval_exists", "This revision already has an active approval")
    sibling_ids = list(
        await session.scalars(
            select(MessageDraft.id).where(
                MessageDraft.generation_run_id == draft.generation_run_id,
                MessageDraft.variant != draft.variant,
            )
        )
    )
    if sibling_ids:
        sibling_approvals = list(
            await session.scalars(
                select(DraftApproval).where(
                    DraftApproval.draft_id.in_(sibling_ids),
                    DraftApproval.invalidated_at.is_(None),
                    DraftApproval.consumed_at.is_(None),
                )
            )
        )
        now = datetime.now(UTC)
        for sibling in sibling_approvals:
            sibling.invalidated_at = now
            sibling.invalidation_reason = "alternative_variant_selected"
    token = token_urlsafe(32)
    request_id = str(getattr(request.state, "request_id", "missing-request-id"))
    previous = await session.scalar(
        select(DraftApproval).where(DraftApproval.draft_id == draft.id)
    )
    if previous is not None:
        if previous.consumed_at is not None:
            raise api_error(
                409,
                "approval_already_consumed",
                "Create a new draft revision before approving another delivery",
            )
        previous.draft_revision = draft.revision
        previous.decision = "approved"
        previous.approved_by = "primary_owner"
        previous.approved_at = datetime.now(UTC)
        previous.comment = payload.comment
        previous.one_time_token_hash = sha256(token.encode()).hexdigest()
        previous.invalidated_at = None
        previous.invalidation_reason = None
        previous.request_id = request_id
        approval = previous
    else:
        approval = DraftApproval(
            draft_id=draft.id,
            draft_revision=draft.revision,
            decision="approved",
            approved_by="primary_owner",
            comment=payload.comment,
            one_time_token_hash=sha256(token.encode()).hexdigest(),
            request_id=request_id,
        )
        session.add(approval)
    session.add(
        DraftReviewEvent(
            company_id=draft.company_id,
            draft_id=draft.id,
            action="approved",
            actor="primary_owner",
            comment=payload.comment,
            safe_diff={"revision": draft.revision, "content_hash": draft.content_hash},
            request_id=request_id,
        )
    )
    company = context.company
    company.pipeline_status = "approved"
    company.next_action = "Ready to send to Mailpit; real delivery remains disabled"
    company.version += 1
    add_event(
        session,
        company_id=draft.company_id,
        contact_id=draft.contact_id,
        event_type="draft_approved",
        summary=f"Draft {draft.variant} revision {draft.revision} approved",
        metadata={"draft_id": str(draft.id), "content_hash": draft.content_hash},
    )
    await session.commit()
    await session.refresh(approval)
    return await approval_read(session, approval, draft, token=token)


async def record_nonapproval_decision(
    session: AsyncSession,
    draft: MessageDraft,
    payload: DraftReviewDecisionCreate,
    request: Request,
    action: str,
) -> DraftReviewEvent:
    await invalidate_lineage_approvals(session, draft, f"owner_{action}")
    request_id = str(getattr(request.state, "request_id", "missing-request-id"))
    event = DraftReviewEvent(
        company_id=draft.company_id,
        draft_id=draft.id,
        action=action,
        actor="primary_owner",
        comment=payload.comment,
        safe_diff={"revision": draft.revision, "content_hash": draft.content_hash},
        request_id=request_id,
    )
    session.add(event)
    company = cast(Company, await session.get(Company, draft.company_id))
    company.pipeline_status = "deferred" if action == "deferred" else "rejected"
    company.next_action = (
        "Review deferred draft" if action == "deferred" else "Letter closed without sending"
    )
    company.version += 1
    add_event(
        session,
        company_id=draft.company_id,
        contact_id=draft.contact_id,
        event_type=f"draft_{action}",
        summary=f"Draft {draft.variant} revision {draft.revision}: {action}",
    )
    await session.commit()
    await session.refresh(event)
    return event


@router.post("/drafts/{draft_id}/defer", response_model=DraftReviewEventRead, status_code=201)
async def defer_draft(
    draft_id: UUID,
    payload: DraftReviewDecisionCreate,
    request: Request,
    session: DbSession,
) -> DraftReviewEvent:
    draft = await draft_or_404(session, draft_id)
    await require_latest(session, draft, payload.revision)
    return await record_nonapproval_decision(session, draft, payload, request, "deferred")


@router.post("/drafts/{draft_id}/reject", response_model=DraftReviewEventRead, status_code=201)
async def reject_draft(
    draft_id: UUID,
    payload: DraftReviewDecisionCreate,
    request: Request,
    session: DbSession,
) -> DraftReviewEvent:
    draft = await draft_or_404(session, draft_id)
    await require_latest(session, draft, payload.revision)
    return await record_nonapproval_decision(session, draft, payload, request, "rejected")


@router.post(
    "/drafts/{draft_id}/restore-deferred",
    response_model=DraftReviewEventRead,
    status_code=201,
)
async def restore_deferred_draft(
    draft_id: UUID,
    payload: DraftReviewDecisionCreate,
    request: Request,
    session: DbSession,
) -> DraftReviewEvent:
    draft = await draft_or_404(session, draft_id)
    await require_latest(session, draft, payload.revision)
    company = cast(Company, await session.get(Company, draft.company_id))
    if company.pipeline_status != "deferred":
        raise api_error(409, "draft_not_deferred", "The letter is not currently deferred")
    request_id = str(getattr(request.state, "request_id", "missing-request-id"))
    event = DraftReviewEvent(
        company_id=draft.company_id,
        draft_id=draft.id,
        action="restored_to_drafts",
        actor="primary_owner",
        comment=payload.comment,
        safe_diff={"revision": draft.revision, "content_hash": draft.content_hash},
        request_id=request_id,
    )
    session.add(event)
    company.pipeline_status = "review"
    company.next_action = "Review current draft"
    company.version += 1
    add_event(
        session,
        company_id=draft.company_id,
        contact_id=draft.contact_id,
        event_type="draft_restored_to_drafts",
        summary=f"Draft {draft.variant} revision {draft.revision} returned to drafts",
    )
    await session.commit()
    await session.refresh(event)
    return event


@router.post(
    "/drafts/{draft_id}/restore-rejected",
    response_model=DraftReviewEventRead,
    status_code=201,
)
async def restore_rejected_draft(
    draft_id: UUID,
    payload: DraftReviewDecisionCreate,
    request: Request,
    session: DbSession,
) -> DraftReviewEvent:
    draft = await draft_or_404(session, draft_id)
    await require_latest(session, draft, payload.revision)
    company = cast(Company, await session.get(Company, draft.company_id))
    if company.pipeline_status != "rejected":
        raise api_error(409, "draft_not_rejected", "The letter is not currently closed")
    request_id = str(getattr(request.state, "request_id", "missing-request-id"))
    event = DraftReviewEvent(
        company_id=draft.company_id,
        draft_id=draft.id,
        action="restored_to_drafts",
        actor="primary_owner",
        comment=payload.comment,
        safe_diff={"revision": draft.revision, "content_hash": draft.content_hash},
        request_id=request_id,
    )
    session.add(event)
    company.pipeline_status = "review"
    company.next_action = "Review current draft"
    company.version += 1
    add_event(
        session,
        company_id=draft.company_id,
        contact_id=draft.contact_id,
        event_type="draft_restored_to_drafts",
        summary=f"Draft {draft.variant} revision {draft.revision} returned to drafts",
    )
    await session.commit()
    await session.refresh(event)
    return event


@router.post(
    "/drafts/{draft_id}/do-not-contact",
    response_model=DraftReviewEventRead,
    status_code=201,
)
async def mark_draft_do_not_contact(
    draft_id: UUID,
    payload: DraftReviewDecisionCreate,
    request: Request,
    session: DbSession,
) -> DraftReviewEvent:
    draft = await draft_or_404(session, draft_id)
    await require_latest(session, draft, payload.revision)
    contact = cast(Contact, await session.get(Contact, draft.contact_id))
    contact.do_not_contact = True
    contact.version += 1
    await cancel_open_followups(
        session,
        contact_id=contact.id,
        reason="do_not_contact",
        request_id=str(getattr(request.state, "request_id", "missing-request-id")),
    )
    await invalidate_lineage_approvals(session, draft, "contact_suppressed")
    request_id = str(getattr(request.state, "request_id", "missing-request-id"))
    event = DraftReviewEvent(
        company_id=draft.company_id,
        draft_id=draft.id,
        action="do_not_contact",
        actor="primary_owner",
        comment=payload.comment,
        safe_diff={"contact_id": str(contact.id), "do_not_contact": True},
        request_id=request_id,
    )
    session.add(event)
    company = cast(Company, await session.get(Company, draft.company_id))
    company.pipeline_status = "review"
    company.next_action = "Contact suppressed; select another lawful contact or reject"
    company.version += 1
    add_event(
        session,
        company_id=draft.company_id,
        contact_id=draft.contact_id,
        event_type="contact_suppressed",
        summary="Owner marked the draft contact as do-not-contact",
    )
    await session.commit()
    await session.refresh(event)
    return event
