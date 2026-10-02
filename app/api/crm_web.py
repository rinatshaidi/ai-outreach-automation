"""Server-rendered Mini-CRM pages and form actions."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.crm import (
    DbSession,
    create_campaign,
    create_company,
    create_contact,
    create_job,
    create_timeline_event,
    get_contact_validator,
    update_company,
)
from app.api.crm import (
    validate_contact as validate_contact_record,
)
from app.api.generation import generate_company_drafts
from app.api.opportunities import (
    create_assessment,
    create_opportunity,
    create_recommendation,
    create_signal,
    create_source,
    decide_recommendation,
)
from app.api.relevance import calculate_company_relevance, override_assessment
from app.api.research import get_safe_fetcher, run_research
from app.api.web import templates
from app.config import get_settings
from app.modules.candidate_profile.models import CandidateProfile
from app.modules.crm.contact_discovery import discover_company_contacts
from app.modules.crm.contact_presentation import present_contact
from app.modules.crm.contact_shortlist import has_usable_verified_route, preferred_contact_routes
from app.modules.crm.models import (
    Campaign,
    CommunicationEvent,
    Company,
    Contact,
    JobOpening,
)
from app.modules.crm.pipeline import allowed_next_statuses, transition_is_allowed
from app.modules.crm.schemas import (
    CampaignCreate,
    CampaignStatus,
    CampaignTone,
    CompanyCreate,
    CompanyUpdate,
    ContactCreate,
    JobCreate,
    PipelineStatus,
    TimelineEventCreate,
    VerificationStatus,
)
from app.modules.delivery.models import OutboundMessage
from app.modules.feedback.service import COMPANY_DECISIONS, record_owner_feedback
from app.modules.followups.models import FollowUp
from app.modules.generation.models import (
    DraftApproval,
    DraftReviewEvent,
    GenerationRun,
    MessageDraft,
)
from app.modules.generation.schemas import GenerationCreate
from app.modules.generation.service import primary_match_fingerprint
from app.modules.mailbox.models import InboundMessage, MailboxConnection
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    OpportunitySignal,
    PositioningRecommendation,
)
from app.modules.opportunities.presentation import (
    POSITIONING_LABELS_EN,
    POSITIONING_LABELS_RU,
    localized_values,
)
from app.modules.opportunities.readiness import evaluate_opportunity_readiness
from app.modules.opportunities.schemas import (
    CollaborationFormat,
    CompanyOpportunityCreate,
    CompanySourceCreate,
    DecisionMakerRole,
    EvidenceStatus,
    OpportunityAssessmentCreate,
    OpportunityDecision,
    OpportunityDecisionCreate,
    OpportunitySignalCreate,
    OpportunitySignalType,
    OpportunityType,
    PositioningRecommendationCreate,
    PositioningStrategy,
    ScoreBreakdown,
    WorkplaceFormat,
)
from app.modules.relevance.models import OpportunityAssessmentOverride
from app.modules.relevance.schemas import (
    AssessmentOverrideCreate,
    RelevanceCalculationRequest,
    ScoringWeights,
)
from app.modules.research.deeper import execute_deeper_research
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis, ResearchRun
from app.modules.research.schemas import ResearchRequest
from app.modules.research.synthesis import (
    draft_primary_match_for_contact,
    get_or_build_decision_synthesis,
    refresh_decision_synthesis,
)
from app.modules.safety.models import OwnerSafetyPolicy
from app.modules.search_tasks.models import SearchTask, SearchTaskResult

router = APIRouter(include_in_schema=False)

PIPELINE_COLUMNS: tuple[tuple[str, frozenset[str]], ...] = (
    ("Новые", frozenset({"new"})),
    ("Анализ", frozenset({"research_pending", "researched", "needs_review"})),
    ("Opportunity", frozenset({"opportunity_identified"})),
    ("Стратегия", frozenset({"strategy_selected"})),
    (
        "Контакт",
        frozenset({"contact_found", "contact_missing", "contact_research_required"}),
    ),
    ("Решение", frozenset({"decision_pending"})),
    (
        "Approved / Deferred / Watchlist",
        frozenset({"approved_for_outreach", "deferred", "watchlist"}),
    ),
    ("Письмо / Review", frozenset({"draft_ready", "review", "approved"})),
    ("Отправлено", frozenset({"sent", "waiting_reply"})),
    ("Ответ", frozenset({"replied"})),
    (
        "Интервью / Project / Consulting",
        frozenset({"interview", "project_discussion", "consulting_discussion"}),
    ),
    (
        "Offer / Agreement / Закрыто",
        frozenset({"offer", "agreement", "rejected", "not_relevant", "closed"}),
    ),
)


def csv_values(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


@router.get("/search-history", response_class=HTMLResponse)
async def search_history_page(request: Request, session: DbSession) -> HTMLResponse:
    tasks = list(
        await session.scalars(select(SearchTask).order_by(SearchTask.created_at.desc()).limit(100))
    )
    task_ids = [item.id for item in tasks]
    results = (
        list(
            await session.scalars(
                select(SearchTaskResult).where(SearchTaskResult.search_task_id.in_(task_ids))
            )
        )
        if task_ids
        else []
    )
    company_ids = {item.company_id for item in results}
    companies = {
        item.id: item
        for item in (
            await session.scalars(select(Company).where(Company.id.in_(company_ids)))
            if company_ids
            else []
        )
    }
    results_by_task: dict[UUID, list[SearchTaskResult]] = {}
    for result in results:
        results_by_task.setdefault(result.search_task_id, []).append(result)
    return templates.TemplateResponse(
        request=request,
        name="search_history.html",
        context={
            "tasks": tasks,
            "results_by_task": results_by_task,
            "companies": companies,
        },
    )


@router.get("/companies", response_class=HTMLResponse)
async def companies_page(
    request: Request,
    session: DbSession,
    campaign_id: UUID | None = None,
    task_id: UUID | None = None,
) -> HTMLResponse:
    all_companies = list(await session.scalars(select(Company).order_by(Company.updated_at.desc())))
    campaign = await session.get(Campaign, campaign_id) if campaign_id else None
    if campaign_id and campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign is not None:
        # Reuse explicit campaign criteria and delivery relationships; never
        # pretend that unrelated inbox companies belong to an old campaign.
        member_ids = set((campaign.criteria or {}).get("company_ids", []))
        task_ids = (campaign.criteria or {}).get("search_task_ids", [])
        member_ids.update(
            str(value)
            for value in await session.scalars(
                select(OutboundMessage.company_id).where(OutboundMessage.campaign_id == campaign.id)
            )
        )
        if task_ids:
            member_ids.update(
                str(value)
                for value in await session.scalars(
                    select(SearchTaskResult.company_id).where(
                        SearchTaskResult.search_task_id.in_([UUID(value) for value in task_ids])
                    )
                )
            )
        all_companies = [c for c in all_companies if str(c.id) in member_ids]
    task_result_company_ids: set[UUID] | None = None
    if task_id is not None:
        task_result_company_ids = set(
            await session.scalars(
                select(SearchTaskResult.company_id).where(
                    SearchTaskResult.search_task_id == task_id,
                    SearchTaskResult.accepted.is_(True),
                )
            )
        )
        all_companies = [item for item in all_companies if item.id in task_result_company_ids]
    all_ids = [item.id for item in all_companies]
    recent_search_tasks = list(
        await session.scalars(select(SearchTask).order_by(SearchTask.created_at.desc()).limit(1))
    )
    settings = get_settings()
    local_now = datetime.now(UTC).astimezone(ZoneInfo(settings.user_timezone))
    daily_tasks = list(
        await session.scalars(
            select(SearchTask)
            .where(SearchTask.source == "daily")
            .order_by(SearchTask.scheduled_for_date.desc(), SearchTask.created_at.desc())
        )
    )
    daily_task_today = next(
        (item for item in daily_tasks if item.scheduled_for_date == local_now.date()), None
    )
    next_daily_date = (
        local_now.date() + timedelta(days=1)
        if daily_task_today is not None or local_now.hour >= settings.daily_discovery_hour
        else local_now.date()
    )
    daily_discovery = {
        "enabled": settings.daily_discovery_enabled,
        "today_accepted": daily_task_today.accepted_count if daily_task_today else 0,
        "today_status": daily_task_today.status if daily_task_today else None,
        "today_found": daily_task_today.found_count if daily_task_today else 0,
        "total_accepted": sum(item.accepted_count for item in daily_tasks),
        "next_at": datetime.combine(
            next_daily_date,
            datetime.min.time(),
            tzinfo=ZoneInfo(settings.user_timezone),
        ).replace(hour=settings.daily_discovery_hour),
        "limit": settings.daily_discovery_result_limit,
    }
    search_task_results = (
        list(
            await session.scalars(
                select(SearchTaskResult).where(SearchTaskResult.company_id.in_(all_ids))
            )
        )
        if all_ids
        else []
    )
    linked_task_ids = {item.search_task_id for item in search_task_results}
    linked_tasks = (
        list(
            await session.scalars(
                select(SearchTask)
                .where(SearchTask.id.in_(linked_task_ids))
                .order_by(SearchTask.created_at.desc())
            )
        )
        if linked_task_ids
        else []
    )

    def latest_task_for_company(company_id: UUID) -> SearchTask | None:
        task_ids = {
            item.search_task_id for item in search_task_results if item.company_id == company_id
        }
        return next((item for item in linked_tasks if item.id in task_ids), None)

    def latest_result_for_company(company_id: UUID) -> SearchTaskResult | None:
        task = latest_task_for_company(company_id)
        if task is None:
            return None
        return next(
            (
                item
                for item in search_task_results
                if item.company_id == company_id and item.search_task_id == task.id
            ),
            None,
        )

    hidden_statuses = {
        "not_relevant",
        "rejected",
        "closed",
        "deferred",
        "sent",
        "waiting_reply",
        "replied",
    }
    real_companies = [
        item
        for item in all_companies
        if not item.is_synthetic
        and (
            (latest_result := latest_result_for_company(item.id)) is None
            or (
                latest_result.accepted
                and latest_result.qualification_status == "QUALIFIED"
                and item.identity_verification_status == "verified"
            )
        )
        and (
            campaign is not None
            or task_id is not None
            or item.pipeline_status not in hidden_statuses
        )
    ]
    synthetic_companies = [item for item in all_companies if item.is_synthetic]
    ids = [item.id for item in all_companies]
    opportunities = (
        list(
            await session.scalars(
                select(CompanyOpportunity)
                .where(CompanyOpportunity.company_id.in_(ids))
                .order_by(CompanyOpportunity.created_at.desc())
            )
        )
        if ids
        else []
    )
    hypotheses = (
        list(
            await session.scalars(
                select(CompanyTaskHypothesis)
                .where(CompanyTaskHypothesis.company_id.in_(ids))
                .order_by(CompanyTaskHypothesis.created_at.desc())
            )
        )
        if ids
        else []
    )
    recommendations = (
        list(
            await session.scalars(
                select(PositioningRecommendation)
                .where(PositioningRecommendation.company_id.in_(ids))
                .order_by(PositioningRecommendation.created_at.desc())
            )
        )
        if ids
        else []
    )
    contacts = (
        list(
            await session.scalars(
                select(Contact)
                .where(Contact.company_id.in_(ids))
                .order_by(Contact.decision_priority.asc().nullslast(), Contact.created_at)
            )
        )
        if ids
        else []
    )

    def latest_for(items: Sequence[Any], company_id: UUID) -> Any | None:
        return next((item for item in items if item.company_id == company_id), None)

    async def card(company: Company) -> dict[str, Any]:
        opportunity = latest_for(opportunities, company.id)
        hypothesis = latest_for(hypotheses, company.id)
        recommendation = latest_for(recommendations, company.id)
        company_contacts = [item for item in contacts if item.company_id == company.id]
        primary_contact = next(
            (
                item
                for item in company_contacts
                if item.validation_status == "VERIFIED_CONTACT" and not item.do_not_contact
            ),
            None,
        )
        readiness = await evaluate_opportunity_readiness(
            session, company, locale=request.state.dashboard_locale
        )
        presentation: dict[str, Any] = {}
        synthesis = await get_or_build_decision_synthesis(
            session, company, locale=request.state.dashboard_locale
        )
        source_task = latest_task_for_company(company.id)
        return {
            "company": company,
            "opportunity": opportunity,
            "hypothesis": hypothesis,
            "recommendation": recommendation,
            "primary_contact": primary_contact,
            "confidence": getattr(opportunity, "confidence", None)
            or getattr(hypothesis, "confidence", None),
            "main_reason": getattr(opportunity, "rationale", None)
            or getattr(hypothesis, "rationale", None),
            "main_risk": (
                (getattr(hypothesis, "risks", None) or [None])[0]
                if hypothesis is not None
                else None
            ),
            "readiness": readiness,
            "presentation": presentation,
            "brief": synthesis.payload,
            "positioning_label": (
                POSITIONING_LABELS_RU.get(company.recommended_positioning or "", "Не определено")
                if request.state.dashboard_locale == "ru"
                else POSITIONING_LABELS_EN.get(
                    company.recommended_positioning or "", "Not determined"
                )
            ),
            "work_formats": localized_values(
                company.recommended_workplace_formats, request.state.dashboard_locale
            ),
            "collaboration_formats": localized_values(
                company.recommended_collaboration_formats, request.state.dashboard_locale
            ),
            "source_task": source_task,
        }

    from app.modules.opportunities.quality import ready_for_inbox

    real_cards = [await card(item) for item in real_companies]
    real_cards = [
        item
        for item in real_cards
        if ready_for_inbox(
            item["company"], item["brief"], item["readiness"].contact_status == "CONTACT_FOUND"
        )
    ]
    awaiting_decision = [
        item for item in real_cards if item["company"].pipeline_status == "decision_pending"
    ]
    contact_research = [item for item in real_cards if item["readiness"].primary_contact is None]
    return templates.TemplateResponse(
        request=request,
        name="companies.html",
        context={
            "companies": real_companies,
            "campaign": campaign,
            "task_filter": task_id,
            "company_cards": real_cards,
            "actionable_cards": [item for item in real_cards if item["readiness"].actionable],
            "research_cards": [item for item in real_cards if not item["readiness"].actionable],
            "summary": {
                "selected": len(real_cards),
                "checked": len(all_companies),
                "filtered": len(all_companies) - len(real_cards),
                "awaiting_decision": len(awaiting_decision),
                "contact_research": len(contact_research),
            },
            "daily_discovery": daily_discovery,
            "synthetic_companies": synthetic_companies,
            "pipeline_statuses": list(PipelineStatus),
            "recent_search_tasks": recent_search_tasks,
            "task_notice": request.query_params.get("task"),
        },
    )


@router.post("/companies")
async def save_company(
    session: DbSession,
    name: Annotated[str, Form()],
    normalized_domain: Annotated[str, Form()],
    country: Annotated[str, Form()] = "",
    industry: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
) -> RedirectResponse:
    company = await create_company(
        CompanyCreate(
            name=name,
            normalized_domain=normalized_domain,
            country=country or None,
            industry=industry or None,
            description=description or None,
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company.id}", status_code=303)


@router.post("/companies/{company_id}/open")
async def open_company_from_inbox(
    company_id: UUID,
    session: DbSession,
    campaign_id: Annotated[UUID | None, Form()] = None,
) -> RedirectResponse:
    """Record that an inbox item was opened without changing its inbox state."""

    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    latest_event = await session.scalar(
        select(CommunicationEvent)
        .where(
            CommunicationEvent.company_id == company_id,
            CommunicationEvent.event_type.in_(
                {"owner_opened_from_inbox", "owner_returned_to_inbox"}
            ),
        )
        .order_by(CommunicationEvent.occurred_at.desc())
        .limit(1)
    )
    if latest_event is None or latest_event.event_type != "owner_opened_from_inbox":
        session.add(
            CommunicationEvent(
                company_id=company_id,
                event_type="owner_opened_from_inbox",
                summary="Owner opened company from the new opportunities inbox",
                metadata_json={},
            )
        )
        await session.commit()
    suffix = f"?campaign_id={campaign_id}" if campaign_id else ""
    return RedirectResponse(f"/companies/{company_id}{suffix}", status_code=303)


@router.post("/companies/{company_id}/return-to-inbox")
async def return_company_to_inbox(company_id: UUID, session: DbSession) -> RedirectResponse:
    """Compatibility action for historic records; open items already stay in the inbox."""

    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    session.add(
        CommunicationEvent(
            company_id=company_id,
            event_type="owner_returned_to_inbox",
            summary="Owner returned company to the new opportunities inbox",
            metadata_json={},
        )
    )
    await session.commit()
    return RedirectResponse("/companies", status_code=303)


@router.get("/companies/{company_id}", response_class=HTMLResponse)
async def company_page(company_id: UUID, request: Request, session: DbSession) -> HTMLResponse:
    company = await session.scalar(
        select(Company)
        .where(Company.id == company_id)
        .options(
            selectinload(Company.contacts).selectinload(Contact.channels),
            selectinload(Company.jobs),
            selectinload(Company.events),
            selectinload(Company.sources),
        )
    )
    if company is None:
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"entity": "Компания"},
            status_code=404,
        )
    company.events.sort(key=lambda event: event.occurred_at, reverse=True)
    latest_inbox_event = next(
        (
            event
            for event in company.events
            if event.event_type in {"owner_opened_from_inbox", "owner_returned_to_inbox"}
        ),
        None,
    )
    opportunities = list(
        await session.scalars(
            select(CompanyOpportunity)
            .where(CompanyOpportunity.company_id == company_id)
            .order_by(CompanyOpportunity.created_at.desc())
        )
    )
    signals = list(
        await session.scalars(
            select(OpportunitySignal)
            .where(OpportunitySignal.company_id == company_id)
            .order_by(OpportunitySignal.detected_at.desc())
        )
    )
    assessments = list(
        await session.scalars(
            select(OpportunityAssessment)
            .where(OpportunityAssessment.company_id == company_id)
            .order_by(OpportunityAssessment.created_at.desc())
        )
    )
    recommendations = list(
        await session.scalars(
            select(PositioningRecommendation)
            .where(PositioningRecommendation.company_id == company_id)
            .order_by(PositioningRecommendation.created_at.desc())
        )
    )
    research_runs = list(
        await session.scalars(
            select(ResearchRun)
            .where(ResearchRun.company_id == company_id)
            .order_by(ResearchRun.started_at.desc())
        )
    )
    company_facts = list(
        await session.scalars(
            select(CompanyFact)
            .where(CompanyFact.company_id == company_id)
            .order_by(CompanyFact.created_at.desc())
        )
    )
    task_hypotheses = list(
        await session.scalars(
            select(CompanyTaskHypothesis)
            .where(CompanyTaskHypothesis.company_id == company_id)
            .order_by(CompanyTaskHypothesis.created_at.desc())
        )
    )
    assessment_overrides = list(
        await session.scalars(
            select(OpportunityAssessmentOverride)
            .where(OpportunityAssessmentOverride.company_id == company_id)
            .order_by(OpportunityAssessmentOverride.created_at.desc())
        )
    )
    generation_runs = list(
        await session.scalars(
            select(GenerationRun)
            .where(GenerationRun.company_id == company_id)
            .order_by(GenerationRun.created_at.desc())
        )
    )
    letter_language = (
        request.state.outreach_language
        if request.state.outreach_language in {"ru", "en"}
        else request.state.dashboard_locale
    )
    message_drafts = list(
        await session.scalars(
            select(MessageDraft)
            .where(MessageDraft.company_id == company_id)
            .order_by(
                MessageDraft.created_at.desc(),
                MessageDraft.revision.desc(),
                MessageDraft.variant,
            )
        )
    )
    latest_drafts_by_variant: dict[str, MessageDraft] = {}
    draft_revisions_by_variant: dict[str, list[MessageDraft]] = {}
    latest_drafts_by_format_tone: dict[str, MessageDraft] = {}
    run_by_id = {item.id: item for item in generation_runs}
    # Keep saved drafts visible when the workspace language is switched.  A
    # missing translation must not make the owner's previous work disappear.
    for draft in message_drafts:
        draft_revisions_by_variant.setdefault(draft.variant, []).append(draft)
    required_draft_keys = {
        "expanded:professional",
        "expanded:friendly",
        "short:professional",
        "short:friendly",
    }
    draft_ids = [item.id for item in message_drafts]
    draft_approvals = (
        list(
            await session.scalars(
                select(DraftApproval)
                .where(DraftApproval.draft_id.in_(draft_ids))
                .order_by(DraftApproval.approved_at.desc())
            )
        )
        if draft_ids
        else []
    )
    valid_approval_by_draft = {
        item.draft_id: item
        for item in draft_approvals
        if item.invalidated_at is None and item.consumed_at is None
    }
    review_events = list(
        await session.scalars(
            select(DraftReviewEvent)
            .where(DraftReviewEvent.company_id == company_id)
            .order_by(DraftReviewEvent.created_at.desc())
        )
    )
    revision_kinds = {str(item.draft_id): item.action for item in review_events}
    outbound_messages = list(
        await session.scalars(
            select(OutboundMessage)
            .where(OutboundMessage.company_id == company_id)
            .order_by(OutboundMessage.created_at.desc())
        )
    )
    inbound_messages = list(
        await session.scalars(
            select(InboundMessage)
            .where(InboundMessage.company_id == company_id)
            .order_by(InboundMessage.received_at.desc())
        )
    )
    followups = list(
        await session.scalars(
            select(FollowUp)
            .where(FollowUp.company_id == company_id)
            .order_by(FollowUp.due_at.asc())
        )
    )
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    safety_policy = await session.scalar(
        select(OwnerSafetyPolicy).where(OwnerSafetyPolicy.owner_key == "primary")
    )
    gmail_connection = await session.scalar(
        select(MailboxConnection).where(MailboxConnection.provider == "gmail")
    )
    value_realism_score: float | None = None
    if assessments:
        breakdown = assessments[0].score_breakdown or {}
        contributions = breakdown.get("contributions", {}).get("value_proposition_realism", [])
        value_realism_score = round(sum(float(item.get("points", 0)) for item in contributions), 1)
    current_status = PipelineStatus(company.pipeline_status)
    opportunity_readiness = await evaluate_opportunity_readiness(
        session, company, locale=request.state.dashboard_locale
    )
    presentation: dict[str, Any] = {}
    synthesis = await get_or_build_decision_synthesis(
        session, company, locale=request.state.dashboard_locale
    )
    syntheses_by_locale = {request.state.dashboard_locale: synthesis.payload}
    draft_analysis_state: dict[UUID, str] = {}
    for draft in message_drafts:
        if draft.language not in syntheses_by_locale:
            localized_synthesis = await get_or_build_decision_synthesis(
                session, company, locale=draft.language
            )
            syntheses_by_locale[draft.language] = localized_synthesis.payload
        current_primary = draft_primary_match_for_contact(
            syntheses_by_locale[draft.language],
            next((item for item in company.contacts if item.id == draft.contact_id), None),
            draft.language,
        )
        current_fingerprint = primary_match_fingerprint(current_primary)
        stored_fingerprint = str(
            (run_by_id.get(draft.generation_run_id).input_entity_ids or {}).get(
                "primary_match_fingerprint", ""
            )
        ) if run_by_id.get(draft.generation_run_id) else ""
        draft_analysis_state[draft.id] = (
            "current"
            if current_fingerprint and stored_fingerprint == current_fingerprint
            else "stale"
        )
    for draft in message_drafts:
        if draft.language != letter_language or draft_analysis_state.get(draft.id) != "current":
            continue
        latest_drafts_by_variant.setdefault(draft.variant, draft)
        key = f"{draft.message_format}:{draft.tone}"
        latest_drafts_by_format_tone.setdefault(key, draft)
    if presentation.get("description"):
        opportunity_readiness.what_it_does = str(presentation["description"])
    discovered_contacts = sorted(
        (
            item
            for item in company.contacts
            if item.rank_label
            and not item.do_not_contact
            and any(channel.validation_status != "INVALID" for channel in item.channels)
        ),
        key=lambda item: item.discovery_score or 0,
        reverse=True,
    )[:5]
    selectable_contacts = sorted(
        (
            item
            for item in company.contacts
            if item.validation_status == "VERIFIED_CONTACT"
            and item.validated_at is not None
            and not item.do_not_contact
            and has_usable_verified_route(item)
        ),
        key=lambda item: (
            {"primary": 0, "secondary": 1, "alternative": 2}.get(item.rank_label or "", 3),
            -(item.discovery_score or 0),
        ),
    )
    preferred_contact_routes_for_owner = preferred_contact_routes(
        selectable_contacts, request.state.dashboard_locale
    )
    return templates.TemplateResponse(
        request=request,
        name="company_detail.html"
        if request.query_params.get("view") == "technical"
        else "opportunity.html",
        context={
            "company": company,
            "owner_viewed_from_inbox": bool(
                latest_inbox_event and latest_inbox_event.event_type == "owner_opened_from_inbox"
            ),
            "letter_language": letter_language,
            "pipeline_statuses": [
                current_status,
                *sorted(
                    (
                        item
                        for item in allowed_next_statuses(current_status)
                        if transition_is_allowed(current_status, item)
                    ),
                    key=str,
                ),
            ],
            "verification_statuses": list(VerificationStatus),
            "opportunities": opportunities,
            "signals": signals,
            "assessments": assessments,
            "value_realism_score": value_realism_score,
            "recommendations": recommendations,
            "research_runs": research_runs,
            "latest_deeper_run": next(
                (item for item in research_runs if "source_budget" in (item.result_summary or {})),
                None,
            ),
            "company_facts": company_facts,
            "task_hypotheses": task_hypotheses,
            "assessment_overrides": assessment_overrides,
            "generation_runs": generation_runs,
            "message_drafts": message_drafts,
            "draft_analysis_state": draft_analysis_state,
            # Old runs remain accessible through the per-variant history. They
            # must not keep the workspace in a warning state once a complete
            # current matrix has been generated.
            "requires_regeneration": bool(
                any(state == "stale" for state in draft_analysis_state.values())
                and not (required_draft_keys <= set(latest_drafts_by_format_tone))
            ),
            "latest_drafts_by_variant": latest_drafts_by_variant,
            "draft_revisions_by_variant": draft_revisions_by_variant,
            "latest_drafts_by_format_tone": latest_drafts_by_format_tone,
            "draft_matrix_complete": required_draft_keys <= set(latest_drafts_by_format_tone),
            "contacts_by_id": {item.id: item for item in company.contacts},
            "contact_presentation": {
                item.id: present_contact(item, request.state.dashboard_locale)
                for item in company.contacts
            },
            "gmail_connected": bool(gmail_connection and gmail_connection.status == "connected"),
            "real_send_capable": get_settings().allow_real_email,
            "real_send_enabled": bool(safety_policy and safety_policy.real_send_enabled),
            "valid_approval_by_draft": valid_approval_by_draft,
            "revision_kinds": revision_kinds,
            "outbound_messages": outbound_messages,
            "inbound_messages": inbound_messages,
            "followups": followups,
            "ai_rewrite_provider": get_settings().ai_rewrite_provider,
            "opportunity_readiness": opportunity_readiness,
            "discovered_contacts": discovered_contacts,
            "selectable_contacts": selectable_contacts,
            "preferred_contact_routes": preferred_contact_routes_for_owner,
            "preferred_contacts": [item.contact for item in preferred_contact_routes_for_owner],
            "profile": profile,
            "presentation": presentation,
            "brief": synthesis.payload,
            "decision_synthesis": synthesis,
            "positioning_label": (
                POSITIONING_LABELS_RU.get(company.recommended_positioning or "", "Не определено")
                if request.state.dashboard_locale == "ru"
                else POSITIONING_LABELS_EN.get(
                    company.recommended_positioning or "", "Not determined"
                )
            ),
            "work_formats_display": localized_values(
                company.recommended_workplace_formats, request.state.dashboard_locale
            ),
            "collaboration_formats_display": localized_values(
                company.recommended_collaboration_formats, request.state.dashboard_locale
            ),
            "opportunity_types": list(OpportunityType),
            "signal_types": list(OpportunitySignalType),
            "evidence_statuses": list(EvidenceStatus),
            "positioning_strategies": list(PositioningStrategy),
            "collaboration_formats": list(CollaborationFormat),
            "workplace_formats": list(WorkplaceFormat),
            "decision_maker_roles": list(DecisionMakerRole),
            "opportunity_decisions": [
                item
                for item in OpportunityDecision
                if item != OpportunityDecision.PENDING
                and (item != OpportunityDecision.OUTREACH or opportunity_readiness.actionable)
            ],
        },
    )


@router.post("/companies/{company_id}/feedback")
async def save_company_feedback(
    company_id: UUID,
    session: DbSession,
    decision: Annotated[str, Form()],
    reason: Annotated[str | None, Form()] = None,
    comment: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        await record_owner_feedback(
            session,
            category="company_owner_feedback",
            decision=decision,
            allowed_decisions=COMPANY_DECISIONS,
            reason=reason,
            comment=comment,
            company_id=company.id,
            context={"company_name": company.name, "normalized_domain": company.normalized_domain},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/companies/{company_id}?feedback=saved#learning", status_code=303)


@router.post("/companies/{company_id}/generation")
async def save_generated_drafts(
    company_id: UUID,
    request: Request,
    session: DbSession,
    contact_id: Annotated[UUID, Form()],
    recommendation_id: Annotated[UUID, Form()],
    campaign_goal: Annotated[str, Form()],
    language: Annotated[str, Form()] = "auto",
    min_words: Annotated[int, Form()] = 80,
    max_words: Annotated[int, Form()] = 160,
) -> RedirectResponse:
    await generate_company_drafts(
        company_id,
        GenerationCreate(
            contact_id=contact_id,
            recommendation_id=recommendation_id,
            campaign_goal=campaign_goal,
            language=language,
            min_words=min_words,
            max_words=max_words,
        ),
        request,
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#generation", status_code=303)


@router.post("/companies/{company_id}/prepare-letter")
async def prepare_company_letter(
    company_id: UUID,
    request: Request,
    session: DbSession,
    contact_id: Annotated[UUID, Form()],
    recommendation_id: Annotated[UUID, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    """Record the owner's outreach decision and create the two review drafts."""

    recommendation = await session.get(PositioningRecommendation, recommendation_id)
    if recommendation is None or recommendation.company_id != company_id:
        return RedirectResponse(
            f"/companies/{company_id}?letter_error=recommendation_not_found#decision",
            status_code=303,
        )
    company = await session.get(Company, company_id)
    contact = await session.get(Contact, contact_id)
    if company is None or contact is None or contact.company_id != company_id:
        return RedirectResponse(
            f"/companies/{company_id}?letter_error=contact_not_found#decision",
            status_code=303,
        )
    readiness = await evaluate_opportunity_readiness(
        session, company, locale=request.state.dashboard_locale
    )
    if not readiness.actionable or not readiness.primary_contact:
        return RedirectResponse(
            f"/companies/{company_id}?letter_error=opportunity_not_actionable#decision",
            status_code=303,
        )
    selected_language = (
        request.state.outreach_language
        if request.state.outreach_language in {"ru", "en"}
        else request.state.dashboard_locale
    )
    existing_drafts = list(
        await session.scalars(
            select(MessageDraft).where(
                MessageDraft.company_id == company_id,
                MessageDraft.recommendation_id == recommendation_id,
                MessageDraft.contact_id == contact_id,
                MessageDraft.language == selected_language,
            )
        )
    )
    synthesis = await get_or_build_decision_synthesis(
        session, company, locale=selected_language
    )
    current_primary = draft_primary_match_for_contact(
        synthesis.payload, contact, selected_language
    )
    current_fingerprint = primary_match_fingerprint(current_primary)
    existing_run_ids = {item.generation_run_id for item in existing_drafts}
    existing_runs = {
        item.id: item
        for item in (
            list(
                await session.scalars(
                    select(GenerationRun).where(GenerationRun.id.in_(existing_run_ids))
                )
            )
            if existing_run_ids
            else []
        )
    }
    existing_keys = {
        f"{item.message_format}:{item.tone}"
        for item in existing_drafts
        if str((existing_runs.get(item.generation_run_id).input_entity_ids or {}).get(
            "primary_match_fingerprint", ""
        )) == current_fingerprint
        and current_fingerprint
    }
    matrix_complete = {
        "expanded:professional",
        "expanded:friendly",
        "short:professional",
        "short:friendly",
    } <= existing_keys
    try:
        if recommendation.user_decision == "pending":
            await decide_recommendation(
                company_id,
                recommendation_id,
                OpportunityDecisionCreate(
                    version=version,
                    decision=OpportunityDecision.OUTREACH,
                    confirmed=True,
                    comment="Prepare letter — explicit owner decision",
                ),
                request,
                session,
            )
        selected_draft_id = existing_drafts[0].id if existing_drafts else None
        if not matrix_complete:
            generated = await generate_company_drafts(
                company_id,
                GenerationCreate(
                    contact_id=contact_id,
                    recommendation_id=recommendation_id,
                    campaign_goal="Discuss a practical collaboration opportunity",
                    language=selected_language,
                    min_words=100,
                    max_words=180,
                ),
                request,
                session,
            )
            if generated.drafts:
                selected_draft_id = generated.drafts[0].id
    except HTTPException as exc:
        detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("code", "draft_generation_failed"))
        return RedirectResponse(
            f"/companies/{company_id}?letter_error={code}#decision", status_code=303
        )
    notice = "letter_ready" if selected_draft_id else "letter_pending"
    return RedirectResponse(
        f"/companies/{company_id}?letter_notice={notice}#letter",
        status_code=303,
    )


@router.post("/companies/{company_id}/deeper-research")
async def deeper_research_company(
    company_id: UUID,
    request: Request,
    session: DbSession,
) -> RedirectResponse:
    """Run one bounded Local Pilot research and contact-validation pass."""

    company = await session.get(Company, company_id)
    if company is None:
        return RedirectResponse("/companies", status_code=303)
    active = await session.scalar(
        select(ResearchRun)
        .where(ResearchRun.company_id == company_id, ResearchRun.status == "fetching")
        .order_by(ResearchRun.started_at.desc())
    )
    if active is not None and "source_budget" in (active.result_summary or {}):
        return RedirectResponse(
            f"/companies/{company_id}?research_status=running#research-result",
            status_code=303,
        )
    try:
        run = await execute_deeper_research(
            session,
            company,
            request,
            get_safe_fetcher(),
            run_research,
            calculate_company_relevance,
        )
        await discover_company_contacts(session, company)
        await session.refresh(company)
        await refresh_decision_synthesis(session, company, locale=request.state.dashboard_locale)
    except Exception as exc:  # noqa: BLE001 - convert synchronous UI failure to persisted state
        failed = await session.scalar(
            select(ResearchRun)
            .where(ResearchRun.company_id == company_id, ResearchRun.status == "fetching")
            .order_by(ResearchRun.started_at.desc())
        )
        if failed is not None:
            failed.status = "failed"
            failed.error_code = "deeper_research_failed"
            failed.error_message = str(exc)[:500]
            failed.completed_at = datetime.now(UTC)
            await session.commit()
        return RedirectResponse(
            f"/companies/{company_id}?research_status=failed#research-result",
            status_code=303,
        )
    return RedirectResponse(
        f"/companies/{company_id}?research_status={run.status}&research_run={run.id}"
        "#research-result",
        status_code=303,
    )


@router.post("/companies/{company_id}/contact-discovery")
async def contact_discovery_company(
    company_id: UUID,
    session: DbSession,
) -> RedirectResponse:
    """Run one bounded public contact discovery pass without creating drafts."""

    company = await session.get(Company, company_id)
    if company is None:
        return RedirectResponse("/companies", status_code=303)
    try:
        report = await discover_company_contacts(session, company)
    except Exception as exc:  # noqa: BLE001 - persist a human-readable UI failure state
        await session.rollback()
        company = await session.get(Company, company_id)
        if company is None:
            return RedirectResponse("/companies", status_code=303)
        company.contact_discovery_status = "failed"
        company.contact_discovered_at = datetime.now(UTC)
        company.version += 1
        session.add(
            CommunicationEvent(
                company_id=company.id,
                event_type="contact_discovery_failed",
                summary="Contact discovery failed",
                metadata_json={"error": f"{type(exc).__name__}: {exc}"[:500]},
            )
        )
        await session.commit()
        return RedirectResponse(
            f"/companies/{company_id}?contact_status=failed#contacts", status_code=303
        )
    return RedirectResponse(
        f"/companies/{company_id}?contact_status={report.status}#contacts",
        status_code=303,
    )


@router.post("/companies/{company_id}/status")
async def save_company_status(
    company_id: UUID,
    session: DbSession,
    version: Annotated[int, Form()],
    pipeline_status: Annotated[PipelineStatus, Form()],
    next_action: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    await update_company(
        company_id,
        CompanyUpdate(
            version=version,
            pipeline_status=pipeline_status,
            next_action=next_action or None,
            note=note or None,
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}", status_code=303)


@router.post("/companies/{company_id}/contacts")
async def save_company_contact(
    company_id: UUID,
    session: DbSession,
    name: Annotated[str, Form()],
    role: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    telegram: Annotated[str, Form()] = "",
    linkedin: Annotated[str, Form()] = "",
    other_public_link: Annotated[str, Form()] = "",
    decision_maker_role: Annotated[DecisionMakerRole | None, Form()] = None,
    decision_priority: Annotated[int | None, Form()] = None,
    verification_status: Annotated[VerificationStatus, Form()] = VerificationStatus.UNVERIFIED,
    lawful_public_source_note: Annotated[str, Form()] = "",
    do_not_contact: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await create_contact(
        ContactCreate(
            company_id=company_id,
            name=name,
            role=role or None,
            email=email or None,
            telegram=telegram or None,
            linkedin=linkedin or None,
            other_public_link=other_public_link or None,
            decision_maker_role=decision_maker_role,
            decision_priority=decision_priority,
            verification_status=verification_status,
            lawful_public_source_note=lawful_public_source_note or None,
            do_not_contact=do_not_contact,
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#contacts", status_code=303)


@router.post("/companies/{company_id}/contacts/{contact_id}/validate")
async def validate_company_contact(
    company_id: UUID,
    contact_id: UUID,
    session: DbSession,
) -> RedirectResponse:
    contact = await validate_contact_record(
        contact_id,
        session,
        get_contact_validator(),
    )
    if contact.company_id != company_id:
        return RedirectResponse(f"/companies/{company_id}#contacts", status_code=303)
    return RedirectResponse(f"/companies/{company_id}#contacts", status_code=303)


@router.post("/companies/{company_id}/jobs")
async def save_company_job(
    company_id: UUID,
    session: DbSession,
    title: Annotated[str, Form()],
    url: Annotated[str, Form()],
    location: Annotated[str, Form()] = "",
    required_skills: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
) -> RedirectResponse:
    await create_job(
        JobCreate(
            company_id=company_id,
            title=title,
            url=url,
            location=location or None,
            required_skills=csv_values(required_skills),
            description=description or None,
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#jobs", status_code=303)


@router.post("/companies/{company_id}/timeline")
async def save_timeline_event(
    company_id: UUID,
    session: DbSession,
    event_type: Annotated[str, Form()],
    summary: Annotated[str, Form()],
) -> RedirectResponse:
    await create_timeline_event(
        TimelineEventCreate(company_id=company_id, event_type=event_type, summary=summary),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#timeline", status_code=303)


@router.post("/companies/{company_id}/research")
async def save_company_research(
    company_id: UUID,
    request: Request,
    session: DbSession,
    url: Annotated[str, Form()],
) -> RedirectResponse:
    await run_research(
        company_id,
        ResearchRequest(url=url),
        request,
        session,
        get_safe_fetcher(),
    )
    return RedirectResponse(f"/companies/{company_id}#research", status_code=303)


@router.post("/companies/{company_id}/sources")
async def save_company_source(
    company_id: UUID,
    session: DbSession,
    url: Annotated[str, Form()],
    source_type: Annotated[str, Form()] = "manual",
) -> RedirectResponse:
    await create_source(
        company_id,
        CompanySourceCreate(url=url, source_type=source_type),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#research", status_code=303)


@router.post("/companies/{company_id}/signals")
async def save_opportunity_signal(
    company_id: UUID,
    session: DbSession,
    signal_type: Annotated[OpportunitySignalType, Form()],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()],
    confidence: Annotated[float, Form()] = 0.5,
) -> RedirectResponse:
    await create_signal(
        company_id,
        OpportunitySignalCreate(
            signal_type=signal_type,
            title=title,
            description=description,
            detected_at=datetime.now(UTC),
            confidence=confidence,
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#opportunities", status_code=303)


@router.post("/companies/{company_id}/opportunities")
async def save_company_opportunity(
    company_id: UUID,
    session: DbSession,
    opportunity_type: Annotated[OpportunityType, Form()],
    rationale: Annotated[str, Form()],
    confidence: Annotated[float, Form()] = 0.5,
) -> RedirectResponse:
    await create_opportunity(
        company_id,
        CompanyOpportunityCreate(
            opportunity_type=opportunity_type,
            rationale=rationale,
            confidence=confidence,
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#opportunities", status_code=303)


@router.post("/companies/{company_id}/assessments")
async def save_opportunity_assessment(
    company_id: UUID,
    session: DbSession,
    candidate_profile_version: Annotated[int, Form()],
    business_fit_score: Annotated[float, Form()],
    ai_automation_fit_score: Annotated[float, Form()],
    hybrid_fit_score: Annotated[float, Form()],
    format_fit_score: Annotated[float, Form()],
    geography_fit_score: Annotated[float, Form()],
    timing_signal_score: Annotated[float, Form()],
    contactability_score: Annotated[float, Form()],
    overall_opportunity_score: Annotated[float, Form()],
    next_action: Annotated[str, Form()] = "",
) -> RedirectResponse:
    formula_version = "manual-stage2-v1"
    await create_assessment(
        company_id,
        OpportunityAssessmentCreate(
            candidate_profile_version=candidate_profile_version,
            business_fit_score=business_fit_score,
            ai_automation_fit_score=ai_automation_fit_score,
            hybrid_fit_score=hybrid_fit_score,
            format_fit_score=format_fit_score,
            geography_fit_score=geography_fit_score,
            timing_signal_score=timing_signal_score,
            contactability_score=contactability_score,
            overall_opportunity_score=overall_opportunity_score,
            score_breakdown=ScoreBreakdown(
                formula_version=formula_version,
                weights={},
                contributions={},
                warnings=[
                    "Manual Stage 2 assessment; deterministic scoring is implemented in Stage 4"
                ],
            ),
            next_action=next_action or None,
            model_or_rule_version=formula_version,
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#opportunities", status_code=303)


@router.post("/companies/{company_id}/relevance/calculate")
async def save_calculated_relevance(
    company_id: UUID,
    session: DbSession,
    core_fit: Annotated[float, Form()] = 0.40,
    format_fit_score: Annotated[float, Form()] = 0.15,
    geography_fit_score: Annotated[float, Form()] = 0.10,
    timing_signal_score: Annotated[float, Form()] = 0.10,
    contactability_score: Annotated[float, Form()] = 0.10,
    value_proposition_realism: Annotated[float, Form()] = 0.15,
) -> RedirectResponse:
    await calculate_company_relevance(
        company_id,
        session,
        RelevanceCalculationRequest(
            weights=ScoringWeights(
                core_fit=core_fit,
                format_fit_score=format_fit_score,
                geography_fit_score=geography_fit_score,
                timing_signal_score=timing_signal_score,
                contactability_score=contactability_score,
                value_proposition_realism=value_proposition_realism,
            )
        ),
    )
    return RedirectResponse(f"/companies/{company_id}#opportunities", status_code=303)


@router.post("/companies/{company_id}/assessments/{assessment_id}/override")
async def save_assessment_override(
    company_id: UUID,
    assessment_id: UUID,
    request: Request,
    session: DbSession,
    overridden_score: Annotated[float, Form()],
    reason: Annotated[str, Form()],
) -> RedirectResponse:
    await override_assessment(
        company_id,
        assessment_id,
        AssessmentOverrideCreate(overridden_score=overridden_score, reason=reason),
        request,
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#opportunities", status_code=303)


@router.post("/companies/{company_id}/recommendations")
async def save_positioning_recommendation(
    company_id: UUID,
    session: DbSession,
    assessment_id: Annotated[UUID, Form()],
    primary_strategy: Annotated[PositioningStrategy, Form()],
    primary_message_line: Annotated[str, Form()],
    secondary_advantage: Annotated[str, Form()],
    rationale: Annotated[str, Form()],
    value_proposition: Annotated[str, Form()],
    concrete_first_message_offer: Annotated[str, Form()],
    primary_decision_maker_role: Annotated[DecisionMakerRole, Form()],
    secondary_decision_maker_role: Annotated[DecisionMakerRole, Form()],
    collaboration_format: Annotated[CollaborationFormat, Form()],
    possible_role: Annotated[str, Form()],
    workplace_formats: Annotated[str, Form()] = "",
) -> RedirectResponse:
    await create_recommendation(
        company_id,
        PositioningRecommendationCreate(
            assessment_id=assessment_id,
            primary_strategy=primary_strategy,
            primary_message_line=primary_message_line,
            secondary_advantage=secondary_advantage,
            rationale=rationale,
            value_proposition=value_proposition,
            concrete_first_message_offer=concrete_first_message_offer,
            primary_decision_maker_role=primary_decision_maker_role,
            secondary_decision_maker_role=secondary_decision_maker_role,
            collaboration_format=collaboration_format,
            possible_role=possible_role,
            workplace_formats=[WorkplaceFormat(item) for item in csv_values(workplace_formats)],
        ),
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#opportunities", status_code=303)


@router.post("/companies/{company_id}/recommendations/{recommendation_id}/decision")
async def save_opportunity_decision(
    company_id: UUID,
    recommendation_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    decision: Annotated[OpportunityDecision, Form()],
    confirmed: Annotated[bool, Form()] = False,
    comment: Annotated[str, Form()] = "",
) -> RedirectResponse:
    await decide_recommendation(
        company_id,
        recommendation_id,
        OpportunityDecisionCreate(
            version=version,
            decision=decision,
            confirmed=confirmed,
            comment=comment or None,
        ),
        request,
        session,
    )
    return RedirectResponse(f"/companies/{company_id}#letter", status_code=303)


@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request, session: DbSession) -> HTMLResponse:
    companies = list(await session.scalars(select(Company).order_by(Company.updated_at.desc())))
    columns = [
        {
            "label": label,
            "companies": [company for company in companies if company.pipeline_status in statuses],
        }
        for label, statuses in PIPELINE_COLUMNS
    ]
    return templates.TemplateResponse(
        request=request,
        name="pipeline.html",
        context={"columns": columns},
    )


@router.get("/contacts", response_class=HTMLResponse)
async def contacts_page(request: Request, session: DbSession) -> HTMLResponse:
    contacts = list(
        await session.scalars(
            select(Contact)
            .options(selectinload(Contact.company))
            .order_by(Contact.updated_at.desc())
        )
    )
    return templates.TemplateResponse(
        request=request, name="contacts.html", context={"contacts": contacts}
    )


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, session: DbSession) -> HTMLResponse:
    jobs = list(
        await session.scalars(
            select(JobOpening)
            .options(selectinload(JobOpening.company))
            .order_by(JobOpening.updated_at.desc())
        )
    )
    return templates.TemplateResponse(request=request, name="jobs.html", context={"jobs": jobs})


@router.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page(request: Request, session: DbSession) -> HTMLResponse:
    campaigns = list(await session.scalars(select(Campaign).order_by(Campaign.updated_at.desc())))
    return templates.TemplateResponse(
        request=request,
        name="campaigns.html"
        if request.query_params.get("view") == "technical"
        else "campaign_inbox.html",
        context={
            "campaigns": campaigns,
            "campaign_statuses": list(CampaignStatus),
            "campaign_tones": list(CampaignTone),
        },
    )


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_page(campaign_id: UUID, request: Request, session: DbSession) -> HTMLResponse:
    return await companies_page(request, session, campaign_id)


@router.post("/campaigns")
async def save_campaign(
    session: DbSession,
    name: Annotated[str, Form()],
    goal: Annotated[str, Form()],
    preferred_language: Annotated[str, Form()] = "auto",
    tone_defaults: Annotated[CampaignTone, Form()] = CampaignTone.PROFESSIONAL,
    opportunity_types: Annotated[str, Form()] = "",
    positioning_strategies: Annotated[str, Form()] = "",
    collaboration_formats: Annotated[str, Form()] = "",
    daily_limit: Annotated[int, Form()] = 10,
    followup_interval_business_days: Annotated[int, Form(ge=1, le=60)] = 7,
    max_followups: Annotated[int, Form(ge=0, le=5)] = 1,
    status_value: Annotated[CampaignStatus, Form(alias="status")] = CampaignStatus.DRAFT,
) -> RedirectResponse:
    await create_campaign(
        CampaignCreate(
            name=name,
            goal=goal,
            preferred_language=preferred_language,
            tone_defaults=tone_defaults,
            opportunity_types=[OpportunityType(item) for item in csv_values(opportunity_types)],
            positioning_strategies=[
                PositioningStrategy(item) for item in csv_values(positioning_strategies)
            ],
            collaboration_formats=[
                CollaborationFormat(item) for item in csv_values(collaboration_formats)
            ],
            daily_limit=daily_limit,
            followup_policy={
                "enabled": max_followups > 0,
                "interval_business_days": followup_interval_business_days,
                "max_followups": max_followups,
                "automatic_send_allowed": False,
            },
            status=status_value,
        ),
        session,
    )
    return RedirectResponse("/campaigns", status_code=303)


@router.get("/communications", response_class=HTMLResponse)
async def communications_page(request: Request, session: DbSession) -> HTMLResponse:
    events = list(
        await session.scalars(
            select(CommunicationEvent)
            .options(selectinload(CommunicationEvent.company))
            .order_by(CommunicationEvent.occurred_at.desc())
            .limit(250)
        )
    )
    return templates.TemplateResponse(
        request=request, name="communications.html", context={"events": events}
    )
