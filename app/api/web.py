"""Server-rendered web routes."""

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.crm import DbSession, dashboard_summary
from app.api.profile_review import pilot_readiness
from app.config import get_settings
from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateSkill,
    CandidateStrength,
)
from app.modules.crm.models import Company, Contact, ContactChannel
from app.modules.crm.schemas import DashboardSummary
from app.modules.delivery.models import OutboundMessage
from app.modules.delivery.service import mask_email
from app.modules.feedback.service import owner_feedback_summary
from app.modules.followups.models import FollowUp
from app.modules.generation.models import DraftApproval, DraftReviewEvent, MessageDraft
from app.modules.mailbox.models import InboundMessage, MailboxConnection
from app.modules.opportunities.display import format_local_datetime, localized_risk
from app.modules.opportunities.presentation import (
    localized_blockers,
    localized_dynamic_text,
    localized_status,
    localized_values,
)
from app.modules.opportunities.quality import language_matches
from app.modules.safety.models import OwnerSafetyPolicy

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


templates.env.filters["prettyjson"] = pretty_json
templates.env.filters["ui_text"] = localized_dynamic_text
templates.env.filters["ui_status"] = localized_status
templates.env.filters["ui_blockers"] = localized_blockers
templates.env.filters["ui_values"] = localized_values
templates.env.filters["local_dt"] = format_local_datetime
templates.env.filters["ui_risk"] = localized_risk
templates.env.filters["language_ok"] = language_matches


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: DbSession) -> RedirectResponse:
    """The product entry point is the agent-curated company list."""

    return RedirectResponse("/companies", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
async def technical_dashboard(request: Request, session: DbSession) -> HTMLResponse:
    settings = get_settings()
    readiness = {
        "profile_sections": {},
        "profile_ready": False,
        "authentication_required": settings.auth_required,
        "safe_local_flags": False,
        "companies_available": 0,
        "pilot_first_wave_ready": False,
        "owner_acceptance_required": True,
    }
    try:
        summary = await dashboard_summary(session)
        readiness = await pilot_readiness(session)
    except (OSError, SQLAlchemyError):
        summary = DashboardSummary(
            companies=0,
            researched=0,
            opportunities_identified=0,
            opportunities_with_vacancy=0,
            opportunities_without_vacancy=0,
            business_first=0,
            ai_first=0,
            hybrid=0,
            remote_opportunities=0,
            relocation_opportunities=0,
            project_opportunities=0,
            watchlist=0,
            decision_pending=0,
            verified_contacts=0,
            active_jobs=0,
            active_campaigns=0,
            waiting_review=0,
            sent=0,
            replies=0,
            interviews=0,
            project_discussions=0,
            consulting_discussions=0,
            offers_or_agreements=0,
            followups_due=0,
            recent_events=[],
        )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "settings": settings.safe_summary(),
            "summary": summary,
            "pilot_readiness": readiness,
        },
    )


@router.get("/letters", response_class=HTMLResponse)
async def letters_page(request: Request, session: DbSession) -> HTMLResponse:
    """One owner-facing inbox for drafts, deliveries, replies and follow-ups."""

    tab = request.query_params.get("tab", "drafts")
    allowed_tabs = {"drafts", "deferred", "sent", "replies", "followups"}
    if tab not in allowed_tabs:
        tab = "drafts"

    all_drafts = list(
        await session.scalars(select(MessageDraft).order_by(MessageDraft.created_at.desc()))
    )
    latest_drafts: dict[tuple[object, str], MessageDraft] = {}
    for draft in all_drafts:
        key = (draft.company_id, draft.variant)
        if key not in latest_drafts:
            latest_drafts[key] = draft

    messages = list(
        await session.scalars(select(OutboundMessage).order_by(OutboundMessage.created_at.desc()))
    )
    companies = {item.id: item for item in await session.scalars(select(Company))}
    followups = list(await session.scalars(select(FollowUp).order_by(FollowUp.due_at.asc())))
    replies = list(
        await session.scalars(select(InboundMessage).order_by(InboundMessage.received_at.desc()))
    )
    contacts = {item.id: item for item in await session.scalars(select(Contact))}
    contact_channels: dict[object, ContactChannel] = {}
    for channel in await session.scalars(
        select(ContactChannel)
        .where(ContactChannel.validation_status == "VERIFIED")
        .order_by(ContactChannel.confidence.desc(), ContactChannel.created_at)
    ):
        contact_channels.setdefault(channel.contact_id, channel)
    active_approvals = list(
        await session.scalars(
            select(DraftApproval).where(
                DraftApproval.invalidated_at.is_(None), DraftApproval.consumed_at.is_(None)
            )
        )
    )
    approved_draft_ids = {item.draft_id for item in active_approvals}
    drafts_by_id = {item.id: item for item in all_drafts}
    approved_by_company = {
        selected_draft.company_id: selected_draft.id
        for item in active_approvals
        if (selected_draft := drafts_by_id.get(item.draft_id)) is not None
    }
    sent_company_ids = {item.company_id for item in messages if item.delivery_status == "sent"}
    active_drafts = [
        draft
        for draft in latest_drafts.values()
        if companies[draft.company_id].pipeline_status not in {"deferred", "rejected"}
        and draft.company_id not in sent_company_ids
        and (
            draft.company_id not in approved_by_company
            or approved_by_company[draft.company_id] == draft.id
        )
    ]
    review_events = list(
        await session.scalars(
            select(DraftReviewEvent)
            .where(DraftReviewEvent.action.in_(["deferred", "rejected"]))
            .order_by(DraftReviewEvent.created_at.desc())
        )
    )
    deferred_drafts: list[MessageDraft] = []
    deferred_at: dict[object, object] = {}
    closed_drafts: list[MessageDraft] = []
    closed_at: dict[object, object] = {}
    seen_deferred_companies: set[object] = set()
    seen_closed_companies: set[object] = set()
    for event in review_events:
        company = companies.get(event.company_id)
        draft = drafts_by_id.get(event.draft_id)
        if company is None or draft is None:
            continue
        if (
            event.action == "deferred"
            and company.pipeline_status == "deferred"
            and event.company_id not in seen_deferred_companies
        ):
            deferred_drafts.append(draft)
            deferred_at[draft.id] = event.created_at
            seen_deferred_companies.add(event.company_id)
        if (
            event.action == "rejected"
            and company.pipeline_status == "rejected"
            and event.company_id not in seen_closed_companies
        ):
            closed_drafts.append(draft)
            closed_at[draft.id] = event.created_at
            seen_closed_companies.add(event.company_id)
    return templates.TemplateResponse(
        request=request,
        name="letters.html",
        context={
            "active_tab": tab,
            "drafts": active_drafts,
            "deferred_drafts": deferred_drafts,
            "deferred_at": deferred_at,
            "closed_drafts": closed_drafts,
            "closed_at": closed_at,
            "messages": messages,
            "replies": replies,
            "followups": followups,
            "companies": companies,
            "contacts": contacts,
            "contact_channels": contact_channels,
            "approved_draft_ids": approved_draft_ids,
        },
    )


@router.get("/profile", response_class=HTMLResponse)
async def my_profile_page(request: Request, session: DbSession) -> HTMLResponse:
    """Readable profile summary; the existing editor remains the advanced screen."""

    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    experiences: list[CandidateExperience] = []
    skills: list[CandidateSkill] = []
    strengths: list[CandidateStrength] = []
    facts: list[CandidateFact] = []
    contacts: list[CandidateContact] = []
    if profile:
        experiences = list(
            await session.scalars(
                select(CandidateExperience)
                .where(CandidateExperience.profile_id == profile.id)
                .order_by(CandidateExperience.started_at.desc().nullslast())
            )
        )
        skills = list(
            await session.scalars(
                select(CandidateSkill)
                .where(CandidateSkill.profile_id == profile.id)
                .order_by(CandidateSkill.name)
            )
        )
        strengths = list(
            await session.scalars(
                select(CandidateStrength)
                .where(CandidateStrength.profile_id == profile.id)
                .order_by(CandidateStrength.priority, CandidateStrength.created_at)
            )
        )
        facts = list(
            await session.scalars(
                select(CandidateFact)
                .where(CandidateFact.profile_id == profile.id)
                .order_by(CandidateFact.created_at)
            )
        )
        contacts = list(
            await session.scalars(
                select(CandidateContact)
                .where(CandidateContact.profile_id == profile.id)
                .order_by(CandidateContact.contact_type)
            )
        )
    return templates.TemplateResponse(
        request=request,
        name="my_profile.html",
        context={
            "profile": profile,
            "experiences": experiences,
            "skills": skills,
            "strengths": strengths,
            "facts": facts,
            "contacts": contacts,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, session: DbSession) -> HTMLResponse:
    settings = get_settings()
    feedback_summary = await owner_feedback_summary(session)
    gmail_connection = await session.scalar(
        select(MailboxConnection).where(MailboxConnection.provider == "gmail")
    )
    safety_policy = await session.scalar(
        select(OwnerSafetyPolicy).where(OwnerSafetyPolicy.owner_key == "primary")
    )
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": settings.safe_summary(),
            "followup_business_days": 7,
            "gmail_connection": gmail_connection,
            "gmail_account_masked": (
                mask_email(gmail_connection.account_email)
                if gmail_connection and gmail_connection.account_email
                else None
            ),
            "gmail_oauth_ready": settings.gmail_oauth_enabled,
            "real_email_enabled": settings.allow_real_email,
            "owner_real_send_enabled": bool(safety_policy and safety_policy.real_send_enabled),
            "feedback_summary": feedback_summary,
        },
    )


@router.get("/ui/health", response_class=HTMLResponse)
async def health_badge(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/health_badge.html",
        context={"status": "ok"},
    )
