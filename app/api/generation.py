"""Company-scoped, decision-gated draft generation without delivery capabilities."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import add_event
from app.infrastructure.db.session import get_db_session
from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateFact,
    CandidateProfile,
    CandidateRule,
)
from app.modules.crm.models import Company, CompanySource, Contact
from app.modules.crm.pipeline import draft_generation_allowed
from app.modules.crm.schemas import PipelineStatus
from app.modules.generation.models import (
    ApprovedWritingExample,
    GenerationRun,
    MessageDraft,
    SenderVoiceProfile,
)
from app.modules.generation.schemas import (
    DraftStatus,
    GenerationCreate,
    GenerationRunRead,
    MessageDraftRead,
)
from app.modules.generation.service import (
    MODEL,
    PROVIDER,
    GenerationContext,
    LocalStructuredGenerationAdapter,
    choose_language,
    content_hash,
    estimate_tokens,
    primary_match_fingerprint,
    validate_draft,
)
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    OpportunitySignal,
    PositioningRecommendation,
)
from app.modules.opportunities.readiness import (
    evaluate_opportunity_readiness,
    is_source_backed_opportunity,
)
from app.modules.opportunities.schemas import OpportunityDecision
from app.modules.research.models import CompanyFact
from app.modules.research.synthesis import (
    draft_primary_match_for_contact,
    get_or_build_decision_synthesis,
)

router = APIRouter(prefix="/api/v1/companies/{company_id}/generation", tags=["generation"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def require_company(session: AsyncSession, company_id: UUID) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise api_error(404, "company_not_found", "Company was not found")
    return company


async def run_read(session: AsyncSession, run: GenerationRun) -> GenerationRunRead:
    drafts = list(
        await session.scalars(
            select(MessageDraft)
            .where(MessageDraft.generation_run_id == run.id)
            .order_by(MessageDraft.variant)
        )
    )
    payload = GenerationRunRead.model_validate(run).model_dump()
    payload["drafts"] = [MessageDraftRead.model_validate(item) for item in drafts]
    return GenerationRunRead.model_validate(payload)


@router.post(
    "/generate",
    response_model=GenerationRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_company_drafts(
    company_id: UUID,
    payload: GenerationCreate,
    request: Request,
    session: DbSession,
) -> GenerationRunRead:
    company = await require_company(session, company_id)
    contact = cast(Contact | None, await session.get(Contact, payload.contact_id))
    if contact is None or contact.company_id != company_id:
        raise api_error(404, "contact_not_found", "Company contact was not found")
    if contact.validation_status != "VERIFIED_CONTACT" or contact.validated_at is None:
        raise api_error(
            409,
            "contact_path_not_verified",
            "The selected outreach contact must pass public-path validation first",
        )
    recommendation = cast(
        PositioningRecommendation | None,
        await session.get(PositioningRecommendation, payload.recommendation_id),
    )
    if recommendation is None or recommendation.company_id != company_id:
        raise api_error(404, "recommendation_not_found", "Positioning recommendation was not found")
    try:
        gate_open = draft_generation_allowed(
            PipelineStatus(company.pipeline_status),
            OpportunityDecision(recommendation.user_decision),
        )
    except ValueError:
        gate_open = False
    if not gate_open:
        raise api_error(
            409,
            "outreach_decision_required",
            "Draft generation requires an explicit outreach decision for this recommendation",
        )
    readiness = await evaluate_opportunity_readiness(session, company)
    if not readiness.actionable:
        raise api_error(
            409,
            "opportunity_not_actionable",
            "Draft generation requires an actionable opportunity with a verified public "
            f"contact path. Current recommendation: {readiness.recommended_action.value}",
        )
    assessment = cast(
        OpportunityAssessment | None,
        await session.get(OpportunityAssessment, recommendation.assessment_id),
    )
    if assessment is None:
        raise api_error(409, "assessment_missing", "Recommendation assessment was not found")
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    if profile is None:
        raise api_error(409, "profile_missing", "Candidate Profile must exist")

    candidate_facts = list(
        await session.scalars(
            select(CandidateFact).where(
                CandidateFact.profile_id == profile.id,
                CandidateFact.verified.is_(True),
                CandidateFact.store_private.is_(True),
                CandidateFact.use_in_draft.is_(True),
            )
        )
    )
    signature_contacts = list(
        await session.scalars(
            select(CandidateContact).where(
                CandidateContact.profile_id == profile.id,
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
            .where(CandidateRule.profile_id == profile.id, CandidateRule.active.is_(True))
            .order_by(CandidateRule.priority)
        )
    )
    company_facts = list(
        await session.scalars(
            select(CompanyFact).where(
                CompanyFact.company_id == company_id, CompanyFact.status == "verified"
            )
        )
    )
    opportunities = list(
        await session.scalars(
            select(CompanyOpportunity).where(
                CompanyOpportunity.company_id == company_id,
                CompanyOpportunity.status != "rejected",
            )
        )
    )
    opportunities = [item for item in opportunities if is_source_backed_opportunity(item)]
    signals = list(
        await session.scalars(
            select(OpportunitySignal).where(
                OpportunitySignal.company_id == company_id,
                OpportunitySignal.status == "verified",
            )
        )
    )
    source_languages = list(
        await session.scalars(
            select(CompanySource.language).where(
                CompanySource.company_id == company_id, CompanySource.language.is_not(None)
            )
        )
    )
    selected_language = payload.language
    if selected_language == "auto":
        selected_language = getattr(request.state, "dashboard_locale", "en")
    language = choose_language(
        company, selected_language, [item for item in source_languages if item]
    )
    synthesis = await get_or_build_decision_synthesis(session, company, locale=language.code)
    # A selected recipient is part of the same owner-visible thesis. Keep the
    # company/profile angle immutable, but explain the concrete contact route
    # that the owner chose for this draft.
    decision_brief = dict(synthesis.payload or {})
    primary_match = draft_primary_match_for_contact(decision_brief, contact, language.code)
    if primary_match:
        decision_brief["draft_primary_match"] = primary_match
    sender_voice_profile = await session.scalar(
        select(SenderVoiceProfile).where(
            SenderVoiceProfile.candidate_profile_id == profile.id,
            SenderVoiceProfile.active.is_(True),
        )
    )
    approved_examples = (
        list(
            await session.scalars(
                select(ApprovedWritingExample).where(
                    ApprovedWritingExample.sender_voice_profile_id == sender_voice_profile.id,
                    ApprovedWritingExample.approved.is_(True),
                    ApprovedWritingExample.language == language.code,
                )
            )
        )
        if sender_voice_profile is not None
        else []
    )
    context = GenerationContext(
        company=company,
        contact=contact,
        recommendation=recommendation,
        opportunities=opportunities,
        signals=signals,
        company_facts=company_facts,
        candidate_facts=candidate_facts,
        signature_contacts=signature_contacts,
        rules=rules,
        language=language,
        campaign_goal=payload.campaign_goal,
        prompt_version=payload.prompt_version,
        min_words=payload.min_words,
        max_words=payload.max_words,
        sender_name=profile.display_name or "",
        decision_brief=decision_brief,
        sender_voice_profile=sender_voice_profile,
        approved_examples=approved_examples,
    )
    try:
        generated = await LocalStructuredGenerationAdapter().generate(context)
    except ValueError as exc:
        raise api_error(
            409, str(exc), "Localized research and permitted profile evidence are required"
        ) from exc
    reports = [validate_draft(item, context, outreach_allowed=gate_open) for item in generated]
    all_ready = all(report.passed for report in reports)
    input_ids = {
        "candidate_fact_ids": [str(item.id) for item in candidate_facts],
        "company_fact_ids": [str(item.id) for item in company_facts],
        "opportunity_type_ids": [str(item.id) for item in opportunities],
        "opportunity_signal_ids": [str(item.id) for item in signals],
        "source_ids": list(
            dict.fromkeys(
                [str(item.source_id) for item in company_facts]
                + [str(item.source_id) for item in signals if item.source_id]
            )
        ),
        "analysis_quality_version": decision_brief.get("quality_version"),
        "primary_match_fingerprint": primary_match_fingerprint(primary_match),
    }
    output_tokens = sum(estimate_tokens(f"{item.subject}\n{item.body}") for item in generated)
    run = GenerationRun(
        company_id=company_id,
        contact_id=contact.id,
        recommendation_id=recommendation.id,
        assessment_id=assessment.id,
        status="ready" if all_ready else "blocked",
        prompt_version=payload.prompt_version,
        provider=PROVIDER,
        model=MODEL,
        input_tokens=estimate_tokens(str(input_ids)),
        output_tokens=output_tokens,
        estimated_cost_usd=0,
        input_entity_ids=input_ids,
        validation_summary={
            "passed": all_ready,
            "analysis_quality_version": decision_brief.get("quality_version"),
            "primary_match_fingerprint": primary_match_fingerprint(primary_match),
            "blocked_variants": [
                item.variant.value
                for item, report in zip(generated, reports, strict=True)
                if not report.passed
            ],
        },
        request_id=str(getattr(request.state, "request_id", "missing-request-id")),
    )
    session.add(run)
    await session.flush()
    for item, report in zip(generated, reports, strict=True):
        session.add(
            MessageDraft(
                generation_run_id=run.id,
                company_id=company_id,
                contact_id=contact.id,
                contact_version=contact.version,
                recommendation_id=recommendation.id,
                assessment_id=assessment.id,
                variant=item.variant.value,
                message_format=item.message_format.value,
                tone=item.tone.value,
                status=DraftStatus.READY.value if report.passed else DraftStatus.BLOCKED.value,
                subject=item.subject,
                body=item.body,
                language=item.language,
                language_confidence=language.confidence,
                language_reason=language.reason,
                explanation=item.explanation,
                opportunity_type_ids=[str(value) for value in item.opportunity_type_ids],
                opportunity_signal_ids=[str(value) for value in item.opportunity_signal_ids],
                positioning_strategy=item.positioning_strategy,
                collaboration_format=item.collaboration_format,
                value_proposition=item.value_proposition,
                candidate_fact_ids=[str(value) for value in item.candidate_fact_ids],
                company_fact_ids=[str(value) for value in item.company_fact_ids],
                source_ids=[str(value) for value in item.source_ids],
                warnings=item.warnings,
                validation_report=report.model_dump(mode="json"),
                word_count=len(item.body.split()),
                prompt_version=payload.prompt_version,
                provider=PROVIDER,
                model=MODEL,
                content_hash=content_hash(item.subject, item.body),
            )
        )
    company.next_action = "Review A/B drafts" if all_ready else "Resolve generation blockers"
    if all_ready:
        company.pipeline_status = "draft_ready"
    company.version += 1
    add_event(
        session,
        company_id=company_id,
        contact_id=contact.id,
        event_type="drafts_generated" if all_ready else "drafts_blocked",
        summary=("A/B drafts generated" if all_ready else "A/B drafts blocked by validation"),
        metadata={"run_id": str(run.id), "prompt_version": payload.prompt_version},
    )
    await session.commit()
    await session.refresh(run)
    return await run_read(session, run)


@router.get("/runs", response_model=list[GenerationRunRead])
async def list_generation_runs(company_id: UUID, session: DbSession) -> list[GenerationRunRead]:
    await require_company(session, company_id)
    runs = list(
        await session.scalars(
            select(GenerationRun)
            .where(GenerationRun.company_id == company_id)
            .order_by(GenerationRun.created_at.desc())
        )
    )
    return [await run_read(session, run) for run in runs]


@router.get("/drafts", response_model=list[MessageDraftRead])
async def list_message_drafts(company_id: UUID, session: DbSession) -> list[MessageDraft]:
    await require_company(session, company_id)
    return list(
        await session.scalars(
            select(MessageDraft)
            .where(MessageDraft.company_id == company_id)
            .order_by(MessageDraft.created_at.desc(), MessageDraft.variant)
        )
    )
