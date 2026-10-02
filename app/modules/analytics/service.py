"""Explainable read-only analytics calculated from normalized CRM records."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.analytics.schemas import (
    AnalyticsResponse,
    BreakdownItem,
    FunnelStage,
    PortfolioCompany,
)
from app.modules.crm.models import Company, CompanySource, Contact, JobOpening
from app.modules.delivery.models import OutboundMessage
from app.modules.followups.models import FollowUp
from app.modules.generation.models import DraftApproval, DraftReviewEvent, MessageDraft
from app.modules.opportunities.models import PositioningRecommendation
from app.modules.research.models import ResearchRun

VERIFIED_CONTACT_STATUSES = {"verified", "verified_public", "provider_verified"}
OUTCOME_STATUSES = {
    "replied",
    "interview",
    "project_discussion",
    "consulting_discussion",
    "rejected",
    "offer",
    "agreement",
}
FUNNEL_GROUPS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("discovery", "Новые", frozenset({"new", "research_pending"})),
    (
        "opportunity",
        "Opportunity",
        frozenset({"researched", "opportunity_identified", "needs_review"}),
    ),
    (
        "decision",
        "Решение",
        frozenset(
            {
                "strategy_selected",
                "contact_found",
                "contact_missing",
                "decision_pending",
                "watchlist",
                "deferred",
            }
        ),
    ),
    (
        "draft_review",
        "Draft / Review",
        frozenset({"approved_for_outreach", "draft_ready", "review", "approved"}),
    ),
    ("sent", "Отправлено", frozenset({"sent", "waiting_reply"})),
    ("reply", "Ответ", frozenset({"replied"})),
    (
        "discussion",
        "Interview / Project / Consulting",
        frozenset({"interview", "project_discussion", "consulting_discussion"}),
    ),
    (
        "outcome",
        "Offer / Agreement / Closed",
        frozenset({"offer", "agreement", "rejected", "not_relevant", "closed"}),
    ),
)


def add_company_filter(
    query: Select[tuple[Company]], key: str, value: str | None
) -> Select[tuple[Company]]:
    if not value:
        return query
    if key == "q":
        pattern = f"%{value.strip()}%"
        return query.where(Company.name.ilike(pattern) | Company.normalized_domain.ilike(pattern))
    if key == "opportunity_type":
        return query.where(Company.opportunity_types.contains([value]))
    if key == "positioning_strategy":
        return query.where(Company.recommended_positioning == value)
    if key == "vacancy":
        has_job = exists(
            select(JobOpening.id).where(
                JobOpening.company_id == Company.id, JobOpening.active.is_(True)
            )
        )
        return query.where(has_job if value == "with" else ~has_job)
    if key == "company_size":
        return query.where(Company.company_size == value)
    if key == "maturity_stage":
        return query.where(Company.maturity_stage == value)
    if key == "country":
        return query.where(Company.country == value)
    if key == "collaboration_format":
        return query.where(Company.recommended_collaboration_formats.contains([value]))
    if key == "workplace_format":
        return query.where(Company.recommended_workplace_formats.contains([value]))
    if key == "decision_maker_role":
        return query.where(
            exists(
                select(Contact.id).where(
                    Contact.company_id == Company.id,
                    Contact.decision_maker_role == value,
                )
            )
        )
    if key == "source_trust":
        return query.where(
            exists(
                select(CompanySource.id).where(
                    CompanySource.company_id == Company.id,
                    CompanySource.trust_level == value,
                )
            )
        )
    if key == "signal_freshness":
        return query.where(
            exists(
                select(CompanySource.id).where(
                    CompanySource.company_id == Company.id,
                    CompanySource.freshness_status == value,
                )
            )
        )
    if key == "pipeline_status":
        return query.where(Company.pipeline_status == value)
    if key == "user_decision":
        return query.where(
            exists(
                select(PositioningRecommendation.id).where(
                    PositioningRecommendation.company_id == Company.id,
                    PositioningRecommendation.user_decision == value,
                )
            )
        )
    if key == "outcome":
        return query.where(Company.pipeline_status == value)
    return query


def breakdown(counter: Counter[str]) -> list[BreakdownItem]:
    return [
        BreakdownItem(key=key, companies=count)
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def count_scalar(values: list[Any], attribute: str, *, missing: str = "unknown") -> Counter[str]:
    return Counter(str(getattr(item, attribute) or missing) for item in values)


def count_multi(values: list[Company], attribute: str, *, missing: str = "none") -> Counter[str]:
    result: Counter[str] = Counter()
    for item in values:
        entries = set(getattr(item, attribute) or [])
        if not entries:
            result[missing] += 1
        else:
            result.update(str(entry) for entry in entries)
    return result


async def build_analytics(
    session: AsyncSession,
    *,
    timezone_name: str,
    filters: dict[str, str | None],
) -> AnalyticsResponse:
    query: Select[tuple[Company]] = select(Company).where(Company.is_synthetic.is_(False)).options(
        selectinload(Company.contacts),
        selectinload(Company.jobs),
        selectinload(Company.sources),
    )
    for key, value in filters.items():
        query = add_company_filter(query, key, value)
    companies = list(await session.scalars(query.order_by(Company.updated_at.desc())))
    ids = [item.id for item in companies]
    applied = {key: value for key, value in filters.items() if value}
    if not ids:
        return AnalyticsResponse(
            metrics={key: 0 for key in metric_names()},
            funnel=[
                FunnelStage(key=key, label=label, companies=0) for key, label, _ in FUNNEL_GROUPS
            ],
            breakdowns={},
            portfolio=[],
            applied_filters=applied,
        )

    drafts = list(
        await session.scalars(select(MessageDraft).where(MessageDraft.company_id.in_(ids)))
    )
    draft_ids = [item.id for item in drafts]
    approvals = (
        list(
            await session.scalars(
                select(DraftApproval).where(DraftApproval.draft_id.in_(draft_ids))
            )
        )
        if draft_ids
        else []
    )
    reviews = (
        list(
            await session.scalars(
                select(DraftReviewEvent).where(DraftReviewEvent.company_id.in_(ids))
            )
        )
        if ids
        else []
    )
    messages = list(
        await session.scalars(select(OutboundMessage).where(OutboundMessage.company_id.in_(ids)))
    )
    followups = list(await session.scalars(select(FollowUp).where(FollowUp.company_id.in_(ids))))
    recommendations = list(
        await session.scalars(
            select(PositioningRecommendation).where(PositioningRecommendation.company_id.in_(ids))
        )
    )
    sources = [source for company in companies for source in company.sources]
    contacts = [contact for company in companies for contact in company.contacts]
    research_runs = list(
        await session.scalars(select(ResearchRun).where(ResearchRun.company_id.in_(ids)))
    )

    local_now = datetime.now(ZoneInfo(timezone_name))
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
    day_start = local_start.astimezone(UTC)
    opportunity_companies = [
        item
        for item in companies
        if item.relevance_status == "opportunity_identified" or item.opportunity_types
    ]
    with_vacancy = {
        item.id for item in opportunity_companies if any(job.active for job in item.jobs)
    }
    verified_contacts = [
        item for item in contacts if item.verification_status in VERIFIED_CONTACT_STATUSES
    ]
    reviewed_drafts = {item.draft_id for item in reviews}
    now = datetime.now(UTC)
    durations = [
        (item.updated_at - item.created_at).total_seconds() / 3600
        for item in companies
        if item.pipeline_status != "new" and item.updated_at >= item.created_at
    ]
    metrics: dict[str, int | float] = {
        "companies_added": len(companies),
        "companies_analyzed": sum(item.last_researched_at is not None for item in companies),
        "companies_added_today": sum(item.created_at >= day_start for item in companies),
        "companies_processed_today": sum(
            item.updated_at >= day_start and item.pipeline_status != "new" for item in companies
        ),
        "opportunities_identified": len(opportunity_companies),
        "opportunities_with_vacancy": len(with_vacancy),
        "opportunities_without_vacancy": len(opportunity_companies) - len(with_vacancy),
        "business_first": sum(
            item.recommended_positioning == "business_first" for item in companies
        ),
        "ai_first": sum(item.recommended_positioning == "ai_first" for item in companies),
        "hybrid": sum(item.recommended_positioning == "hybrid" for item in companies),
        "remote_opportunities": sum(
            "remote" in item.recommended_workplace_formats for item in companies
        ),
        "relocation_opportunities": sum(
            "relocation" in item.recommended_workplace_formats for item in companies
        ),
        "project_opportunities": sum(
            "project_based" in item.recommended_collaboration_formats for item in companies
        ),
        "watchlist": sum(item.pipeline_status == "watchlist" for item in companies),
        "decision_pending": sum(item.pipeline_status == "decision_pending" for item in companies),
        "contacts_verified": len(verified_contacts),
        "drafts_created": len(drafts),
        "drafts_blocked": sum(item.status == "blocked" for item in drafts),
        "reviewed": len(reviewed_drafts),
        "approved": len(approvals),
        "test_sent": sum(
            item.delivery_mode == "test" and item.delivery_status == "sent" for item in messages
        ),
        "real_sent": sum(
            item.delivery_mode == "real" and item.delivery_status == "sent" for item in messages
        ),
        "delivery_failed": sum(item.delivery_status == "failed" for item in messages),
        "replies": sum(item.pipeline_status == "replied" for item in companies),
        "positive_replies": sum(
            item.pipeline_status in OUTCOME_STATUSES - {"rejected"} for item in companies
        ),
        "interviews": sum(item.pipeline_status == "interview" for item in companies),
        "project_discussions": sum(
            item.pipeline_status == "project_discussion" for item in companies
        ),
        "consulting_discussions": sum(
            item.pipeline_status == "consulting_discussion" for item in companies
        ),
        "offers": sum(item.pipeline_status == "offer" for item in companies),
        "agreements": sum(item.pipeline_status == "agreement" for item in companies),
        "followups_due": sum(
            item.status in {"planned", "due", "draft_ready", "deferred"} and item.due_at <= now
            for item in followups
        ),
        "errors": sum(item.delivery_status == "failed" for item in messages)
        + sum(item.status in {"failed", "blocked"} for item in research_runs),
        "average_hours_to_current_stage": round(sum(durations) / len(durations), 2)
        if durations
        else 0.0,
    }

    funnel = [
        FunnelStage(
            key=key,
            label=label,
            companies=sum(item.pipeline_status in statuses for item in companies),
        )
        for key, label, statuses in FUNNEL_GROUPS
    ]
    vacancy_counter: Counter[str] = Counter(
        "with_vacancy" if any(job.active for job in item.jobs) else "without_vacancy"
        for item in opportunity_companies
    )
    decision_roles: Counter[str] = Counter(
        item.decision_maker_role or "unknown" for item in contacts if item.decision_priority == 1
    )
    if not decision_roles:
        decision_roles.update(item.decision_maker_role or "unknown" for item in contacts)
    user_decisions: dict[Any, set[str]] = defaultdict(set)
    for recommendation in recommendations:
        user_decisions[recommendation.user_decision].add(str(recommendation.company_id))
    breakdowns = {
        "opportunity_type": breakdown(count_multi(companies, "opportunity_types")),
        "positioning_strategy": breakdown(count_scalar(companies, "recommended_positioning")),
        "vacancy": breakdown(vacancy_counter),
        "company_size": breakdown(count_scalar(companies, "company_size")),
        "maturity_stage": breakdown(count_scalar(companies, "maturity_stage")),
        "country": breakdown(count_scalar(companies, "country")),
        "collaboration_format": breakdown(
            count_multi(companies, "recommended_collaboration_formats")
        ),
        "workplace_format": breakdown(count_multi(companies, "recommended_workplace_formats")),
        "decision_maker_role": breakdown(decision_roles),
        "source_trust": breakdown(count_scalar(sources, "trust_level")),
        "signal_freshness": breakdown(count_scalar(sources, "freshness_status")),
        "pipeline_status": breakdown(count_scalar(companies, "pipeline_status")),
        "user_decision": breakdown(
            Counter({key: len(value) for key, value in user_decisions.items()})
        ),
        "outcome": breakdown(
            Counter(
                item.pipeline_status
                for item in companies
                if item.pipeline_status in OUTCOME_STATUSES
            )
        ),
    }

    drafts_by_company: Counter[Any] = Counter(item.company_id for item in drafts)
    real_by_company: Counter[Any] = Counter(
        item.company_id
        for item in messages
        if item.delivery_mode == "real" and item.delivery_status == "sent"
    )
    followup_by_company: dict[Any, FollowUp] = {}
    for followup in sorted(followups, key=lambda value: value.updated_at):
        followup_by_company[followup.company_id] = followup
    portfolio = []
    for company in companies:
        primary_contacts = sorted(
            company.contacts,
            key=lambda item: (item.decision_priority is None, item.decision_priority or 999),
        )
        portfolio.append(
            PortfolioCompany(
                id=company.id,
                name=company.name,
                domain=company.normalized_domain,
                country=company.country,
                company_size=company.company_size,
                maturity_stage=company.maturity_stage,
                overall_score=company.overall_opportunity_score,
                opportunity_types=company.opportunity_types,
                positioning_strategy=company.recommended_positioning,
                collaboration_formats=company.recommended_collaboration_formats,
                workplace_formats=company.recommended_workplace_formats,
                pipeline_status=company.pipeline_status,
                has_active_vacancy=any(job.active for job in company.jobs),
                verified_contacts=sum(
                    item.verification_status in VERIFIED_CONTACT_STATUSES
                    for item in company.contacts
                ),
                primary_decision_maker_role=(
                    primary_contacts[0].decision_maker_role if primary_contacts else None
                ),
                drafts=drafts_by_company[company.id],
                real_messages=real_by_company[company.id],
                outcome=company.pipeline_status
                if company.pipeline_status in OUTCOME_STATUSES
                else None,
                followup_status=(
                    followup_by_company[company.id].status
                    if company.id in followup_by_company
                    else None
                ),
                next_action=company.next_action,
            )
        )
    return AnalyticsResponse(
        metrics=metrics,
        funnel=funnel,
        breakdowns=breakdowns,
        portfolio=portfolio,
        applied_filters=applied,
    )


def metric_names() -> tuple[str, ...]:
    return (
        "companies_added",
        "companies_analyzed",
        "companies_added_today",
        "companies_processed_today",
        "opportunities_identified",
        "opportunities_with_vacancy",
        "opportunities_without_vacancy",
        "business_first",
        "ai_first",
        "hybrid",
        "remote_opportunities",
        "relocation_opportunities",
        "project_opportunities",
        "watchlist",
        "decision_pending",
        "contacts_verified",
        "drafts_created",
        "drafts_blocked",
        "reviewed",
        "approved",
        "test_sent",
        "real_sent",
        "delivery_failed",
        "replies",
        "positive_replies",
        "interviews",
        "project_discussions",
        "consulting_discussions",
        "offers",
        "agreements",
        "followups_due",
        "errors",
        "average_hours_to_current_stage",
    )
