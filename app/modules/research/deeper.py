"""Bounded deeper-research orchestration for the Local Pilot."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.contact_validation import (
    classify_contact_for_outreach,
    validate_contact_path,
)
from app.modules.crm.models import CommunicationEvent, Company, CompanySource, Contact
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    OpportunitySignal,
    PositioningRecommendation,
)
from app.modules.research.fetcher import SafeFetcher
from app.modules.research.models import CompanyFact, ResearchRun
from app.modules.research.schemas import ResearchRequest
from app.modules.research.synthesis import refresh_decision_synthesis

ResearchRunner = Callable[..., Awaitable[Any]]
ScoringRunner = Callable[..., Awaitable[OpportunityAssessment]]

MAX_RESEARCH_SOURCES = 5
logger = logging.getLogger("app.deeper_research")


def _research_category(url: str) -> str:
    lowered = url.casefold()
    for category in ("vacancy", "career", "leadership", "team", "news", "blog", "about"):
        if category in lowered:
            return category
    return "official"


def select_research_urls(company: Company, sources: list[CompanySource]) -> list[str]:
    """Select a stable 2-5 URL research budget without crawling the whole site."""

    current = [
        item.url
        for item in sorted(
            sources,
            key=lambda item: item.fetched_at or item.created_at,
            reverse=True,
        )
        if item.http_status is not None and 200 <= item.http_status < 300 and not item.error
    ]
    if not current:
        current = [f"https://{company.normalized_domain}"]
    selected: list[str] = []
    seen_categories: set[str] = set()
    for url in current:
        category = _research_category(url)
        if category in seen_categories and len(selected) >= 2:
            continue
        selected.append(url)
        seen_categories.add(category)
        if len(selected) == MAX_RESEARCH_SOURCES:
            break
    return selected


async def discover_gap_urls(
    company: Company,
    sources: list[CompanySource],
    facts: list[CompanyFact],
    signals: list[OpportunitySignal],
) -> tuple[list[str], list[str]]:
    """Search for new source categories based on explicit first-pass gaps."""

    gaps: list[str] = []
    queries: list[str] = []
    fact_types = {item.fact_type for item in facts if item.status == "verified"}
    if "company_scale" not in fact_types:
        gaps.append("company_scale")
        queries.append(f"site:{company.normalized_domain} {company.name} about employees company")
    if not any(item in fact_types for item in {"leadership", "founders", "management"}):
        gaps.append("leadership")
        queries.append(f"site:{company.normalized_domain} {company.name} founder leadership team")
    if not any(item.status == "verified" for item in signals):
        gaps.append("current_signals")
        queries.append(f"site:{company.normalized_domain} {company.name} news careers jobs 2026")
    if company.geography_verification_status != "verified":
        gaps.append("geography")
        queries.append(f"{company.name} official headquarters address company")
    if not any("contact" in item.url.casefold() for item in sources):
        gaps.append("contacts")
        queries.append(f"site:{company.normalized_domain} {company.name} contact")

    if not queries:
        return [], gaps
    # Local import avoids making public-search resolution a research module dependency.
    from app.modules.search_tasks.executor import PublicSearchResolver, registrable_domain

    resolver = PublicSearchResolver()
    known = {item.url for item in sources}
    urls: list[str] = []
    for query in queries[:4]:
        try:
            results = await resolver.public_search(query)
        except Exception as exc:  # noqa: BLE001 - one gap query must not fail the full pass
            logger.info("deeper_research_gap_query_failed error_type=%s", type(exc).__name__)
            continue
        for result in results:
            from urllib.parse import urlparse

            host = urlparse(result.url).hostname
            if not host or registrable_domain(host) != company.normalized_domain:
                continue
            if result.url not in known and result.url not in urls:
                urls.append(result.url)
            if len(urls) >= MAX_RESEARCH_SOURCES:
                return urls, gaps
    return urls, gaps


def _event(
    session: AsyncSession,
    company_id: Any,
    event_type: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        CommunicationEvent(
            company_id=company_id,
            event_type=event_type,
            summary=summary,
            metadata_json=metadata or {},
        )
    )


async def _verify_completed_sources(
    session: AsyncSession,
    company: Company,
    source_ids: set[Any],
    opportunity_sources: dict[Any, set[Any]],
) -> tuple[int, int]:
    facts = list(
        await session.scalars(
            select(CompanyFact).where(
                CompanyFact.company_id == company.id,
                CompanyFact.source_id.in_(source_ids),
            )
        )
    )
    for fact in facts:
        fact.status = "verified"
        fact.confidence = max(fact.confidence, 0.8)
        fact.version += 1
    signals = list(
        await session.scalars(
            select(OpportunitySignal).where(
                OpportunitySignal.company_id == company.id,
                OpportunitySignal.source_id.in_(source_ids),
            )
        )
    )
    for signal in signals:
        signal.status = "verified"
        signal.confidence = max(signal.confidence, 0.7)
        signal.version += 1
    source_keys = {str(value) for value in source_ids}
    opportunities = list(
        await session.scalars(
            select(CompanyOpportunity).where(CompanyOpportunity.company_id == company.id)
        )
    )
    verified_opportunities = 0
    for opportunity in opportunities:
        direct_sources = opportunity_sources.get(opportunity.id, set())
        if direct_sources:
            opportunity.source_ids = list(
                dict.fromkeys(
                    [*(opportunity.source_ids or []), *(str(value) for value in direct_sources)]
                )
            )
        if direct_sources or source_keys.intersection(opportunity.source_ids or []):
            opportunity.status = "verified"
            opportunity.confidence = max(opportunity.confidence, 0.65)
            opportunity.rationale = (
                "Official public research confirms the company activity or hiring signal. "
                "A specific internal need remains a cautious hypothesis for owner review."
            )
            opportunity.version += 1
            verified_opportunities += 1
    return len(facts), verified_opportunities


async def _validate_contacts(
    session: AsyncSession,
    company: Company,
    source_ids: set[Any],
    fetcher: SafeFetcher,
) -> tuple[list[Contact], list[Contact]]:
    sources = {
        item.id: item
        for item in await session.scalars(
            select(CompanySource).where(CompanySource.id.in_(source_ids))
        )
    }
    contacts = list(
        await session.scalars(
            select(Contact).where(
                Contact.company_id == company.id,
                Contact.source_id.in_(source_ids),
            )
        )
    )
    verified: list[Contact] = []
    invalid: list[Contact] = []
    for contact in contacts:
        source = sources.get(contact.source_id) if contact.source_id is not None else None
        result = await validate_contact_path(
            contact,
            company,
            fetcher=fetcher,
            source_url=source.url if source else None,
            source_text=source.extracted_text if source else None,
            source_http_status=source.http_status if source else None,
        )
        contact.validation_status = result.status.value
        contact.validated_at = result.validated_at
        contact.validation_http_status = result.http_status
        contact.validation_final_url = result.final_url
        contact.validation_error = result.error
        contact.version += 1
        if result.status.value == "VERIFIED_CONTACT":
            classify_contact_for_outreach(contact, company.name)
            contact.verification_status = "verified_public"
            contact.confidence = max(contact.confidence or 0, 0.8)
            if not contact.do_not_contact:
                verified.append(contact)
        elif result.status.value == "INVALID_CONTACT":
            invalid.append(contact)
    return verified, invalid


async def execute_deeper_research(
    session: AsyncSession,
    company: Company,
    request: Request,
    fetcher: SafeFetcher,
    research_runner: ResearchRunner,
    scoring_runner: ScoringRunner,
) -> ResearchRun:
    """Run a synchronous, bounded research and contact-validation calibration pass."""

    sources_before = list(
        await session.scalars(select(CompanySource).where(CompanySource.company_id == company.id))
    )
    facts_before_records = list(
        await session.scalars(select(CompanyFact).where(CompanyFact.company_id == company.id))
    )
    signals_before_records = list(
        await session.scalars(
            select(OpportunitySignal).where(OpportunitySignal.company_id == company.id)
        )
    )
    gap_urls, research_gaps = await discover_gap_urls(
        company, sources_before, facts_before_records, signals_before_records
    )
    urls = list(dict.fromkeys([*gap_urls, *select_research_urls(company, sources_before)]))[
        :MAX_RESEARCH_SOURCES
    ]
    score_before = company.overall_opportunity_score
    fact_count_before = len(facts_before_records)
    run = ResearchRun(
        company_id=company.id,
        requested_url=urls[0],
        normalized_url=urls[0],
        status="fetching",
        result_summary={
            "phase": "research_started",
            "source_budget": len(urls),
            "research_gaps": research_gaps,
        },
    )
    session.add(run)
    await session.flush()
    _event(
        session,
        company.id,
        "deeper_research_started",
        "Deeper research started",
        {"run_id": str(run.id), "source_budget": len(urls)},
    )
    await session.commit()
    await session.refresh(run)

    completed_source_ids: set[Any] = set()
    opportunity_sources: dict[Any, set[Any]] = {}
    unavailable: list[dict[str, str]] = []
    for url in urls:
        try:
            result = await research_runner(
                company.id,
                ResearchRequest(url=url),
                request,
                session,
                fetcher,
            )
            child = await session.get(ResearchRun, result.run.id)
            if child and child.source_id:
                completed_source_ids.add(child.source_id)
                for opportunity_id in result.opportunity_ids:
                    opportunity_sources.setdefault(opportunity_id, set()).add(child.source_id)
                source = await session.get(CompanySource, child.source_id)
                if source:
                    source.source_type = "official_public_web"
                    source.trust_level = "official_public"
                    source.freshness_status = "current"
        except Exception as exc:  # noqa: BLE001 - each bounded source is isolated
            detail = getattr(exc, "detail", None)
            unavailable.append({"url": url, "reason": str(detail or exc)[:300]})

    _event(
        session,
        company.id,
        "deeper_research_sources_checked",
        "Public sources checked",
        {"completed": len(completed_source_ids), "unavailable": len(unavailable)},
    )
    await session.commit()

    verified_facts, verified_opportunities = await _verify_completed_sources(
        session, company, completed_source_ids, opportunity_sources
    )
    _event(session, company.id, "deeper_research_contact_search", "Contact research started")
    contact_source_ids = completed_source_ids | {
        item.id
        for item in sources_before
        if item.trust_level == "official_public"
        and item.freshness_status == "current"
        and not item.error
    }
    verified_contacts, invalid_contacts = await _validate_contacts(
        session, company, contact_source_ids, fetcher
    )
    await session.commit()

    assessment = await scoring_runner(company.id, session)
    recommendation = await session.scalar(
        select(PositioningRecommendation)
        .where(PositioningRecommendation.company_id == company.id)
        .order_by(PositioningRecommendation.created_at.desc())
    )
    recommendation_change = "unchanged"
    if recommendation is not None:
        recommendation.assessment_id = assessment.id
        if recommendation.user_decision == "deeper_research":
            recommendation.user_decision = "pending"
            recommendation.decided_at = None
            recommendation_change = "reopened_for_owner_decision"
        recommendation.version += 1

    company.pipeline_status = "decision_pending"
    company.next_action = "Owner decision after deeper research"
    company.last_researched_at = datetime.now(UTC)
    company.version += 1
    fact_count_after = len(
        list(await session.scalars(select(CompanyFact).where(CompanyFact.company_id == company.id)))
    )
    facts_added = max(0, fact_count_after - fact_count_before)
    sources_added = len(
        [
            item
            for item in completed_source_ids
            if item not in {source.id for source in sources_before}
        ]
    )
    sufficiently_complete = (
        len(completed_source_ids) >= min(3, len(urls))
        and bool(verified_contacts)
        and verified_opportunities > 0
    )
    run.status = "completed" if sufficiently_complete else "partial"
    run.completed_at = datetime.now(UTC)
    run.source_id = next(iter(completed_source_ids), None)
    run.result_summary = {
        "phase": "research_completed" if sufficiently_complete else "research_partial",
        "source_budget": len(urls),
        "sources_attempted": len(urls),
        "sources_completed": len(completed_source_ids),
        "unavailable_sources": unavailable,
        "facts_before": fact_count_before,
        "facts_after": fact_count_after,
        "facts_added": facts_added,
        "sources_added": sources_added,
        "research_gaps": research_gaps,
        "verified_facts": verified_facts,
        "verified_opportunities": verified_opportunities,
        "verified_contacts": [str(item.id) for item in verified_contacts],
        "invalid_contacts": [str(item.id) for item in invalid_contacts],
        "score_before": score_before,
        "score_after": assessment.overall_opportunity_score,
        "recommendation_change": recommendation_change,
        "new_confirmed_data": bool(facts_added or sources_added or verified_contacts),
    }
    synthesis = await refresh_decision_synthesis(
        session,
        company,
        locale=getattr(request.state, "dashboard_locale", "ru"),
    )
    run.result_summary["synthesis_version"] = synthesis.version
    _event(
        session,
        company.id,
        "deeper_research_completed" if sufficiently_complete else "deeper_research_partial",
        "Deeper research completed" if sufficiently_complete else "Deeper research partial",
        {"run_id": str(run.id), **run.result_summary},
    )
    await session.commit()
    await session.refresh(run)
    return run
