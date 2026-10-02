# ruff: noqa: E501
"""Create the owner-approved Stage 10 first local pilot wave.

The operation is idempotent by company domain and does not create drafts,
approve outreach, or send messages. Official public sources and conservative
hypotheses are stored with provenance for owner review.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.api.crm import add_event, create_company, create_job, update_company
from app.api.opportunities import (
    create_opportunity,
    create_recommendation,
    create_source,
    update_opportunity,
)
from app.api.relevance import calculate_company_relevance
from app.api.research import run_research
from app.infrastructure.db.session import SessionFactory, close_database
from app.modules.crm.models import Company, CompanySource, JobOpening
from app.modules.crm.schemas import CompanyCreate, CompanyUpdate, JobCreate, PipelineStatus
from app.modules.generation.models import MessageDraft
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    PositioningRecommendation,
)
from app.modules.opportunities.schemas import (
    CollaborationFormat,
    CompanyOpportunityCreate,
    CompanyOpportunityUpdate,
    CompanySourceCreate,
    DecisionMakerRole,
    EvidenceStatus,
    OpportunityType,
    PositioningRecommendationCreate,
    PositioningStrategy,
    WorkplaceFormat,
)
from app.modules.research.fetcher import SafeFetcher
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis, ResearchRun
from app.modules.research.schemas import ResearchRequest

WAVE: list[dict[str, Any]] = [
    {
        "name": "Airalo",
        "domain": "airalo.com",
        "country": "Singapore",
        "regions": ["Global", "Europe", "Asia", "Middle East", "Americas"],
        "industry": "Travel technology and global connectivity",
        "stage": "international growth company",
        "description": (
            "Global eSIM and connectivity company used to test Business First, "
            "international growth and distributed operations fit."
        ),
        "source_url": "https://www.airalo.com/airalo-careers/working-at-airalo/",
        "source_fragment": "Our team is spread across 60+ countries and six continents.",
        "fact_type": "international_operating_model",
        "fact_value": "Airalo publicly describes a distributed team spanning 60+ countries and six continents.",
        "hypothesis_title": "International growth and operations coordination",
        "hypothesis_description": (
            "Airalo may have project needs around cross-functional growth, partner coordination "
            "and repeatable operating processes across countries."
        ),
        "hypothesis_rationale": (
            "The official careers page confirms a geographically distributed global operating model."
        ),
        "hypothesis_risks": [
            "A distributed team does not itself prove an unadvertised hiring or consulting need",
            "Public vacancies may target a more senior or narrower specialist profile",
        ],
        "opportunities": [
            (
                OpportunityType.BUSINESS_EXPANSION,
                "Global operations create a plausible need for structured cross-functional growth delivery.",
                0.72,
            ),
            (
                OpportunityType.OPERATIONS_IMPROVEMENT,
                "Distributed work can make repeatable operating workflows and coordination valuable.",
                0.64,
            ),
            (
                OpportunityType.ACTIVE_HIRING,
                "The official careers site publicly presents current recruitment activity.",
                0.75,
            ),
        ],
        "strategy": PositioningStrategy.BUSINESS_FIRST,
        "message_line": "Lead with international project, business-development and operational delivery experience.",
        "secondary_advantage": "Use practical AI and Python automation as a process-improvement amplifier, not as a senior-engineering claim.",
        "rationale": "Airalo primarily tests transferable business and operating experience in a global remote company.",
        "value_proposition": "Help structure a cross-functional growth or partner workflow and turn it into a clear, repeatable operating process.",
        "first_offer": "Map one growth or partner-operations workflow and identify a small measurable improvement pilot.",
        "primary_dm": DecisionMakerRole.HEAD_OF_BUSINESS_DEVELOPMENT,
        "secondary_dm": DecisionMakerRole.HEAD_OF_OPERATIONS,
        "collaboration": CollaborationFormat.FULL_TIME,
        "workplaces": [WorkplaceFormat.REMOTE],
        "possible_role": "Business Development / Operations Project Manager",
    },
    {
        "name": "Bolt",
        "domain": "bolt.eu",
        "country": "Estonia",
        "regions": ["Europe", "Africa", "Global"],
        "industry": "Mobility, delivery and marketplace operations",
        "stage": "global scale-up",
        "description": (
            "Global mobility platform used to test Expansion and Operations positioning, "
            "including market launches, partnerships and operational playbooks."
        ),
        "source_url": "https://bolt.eu/en/careers/teams/global-operations/",
        "source_fragment": (
            "Operating across more than 50 countries requires systems that scale. "
            "Global teams build the programmes, partnerships, tools, and standards that help markets grow, launch new services, and deliver a consistent experience across the Bolt platform."
        ),
        "fact_type": "global_operations_model",
        "fact_value": "Bolt states that Global Operations supports markets across more than 50 countries with programmes, partnerships, tools and standards.",
        "hypothesis_title": "Multi-market expansion and operational playbook execution",
        "hypothesis_description": (
            "Bolt may value experience coordinating launches, partners, risks and execution "
            "while translating central standards into local operating action."
        ),
        "hypothesis_rationale": (
            "The official Global Operations page describes market growth, service launches and scalable operating standards."
        ),
        "hypothesis_risks": [
            "The current Expansion Lead role is full-time, hybrid and based in Tallinn",
            "Direct fit must be assessed without overstating marketplace or mobility experience",
        ],
        "opportunities": [
            (
                OpportunityType.OPEN_VACANCY,
                "Bolt currently publishes an Expansion Lead role in Global Operations.",
                0.92,
            ),
            (
                OpportunityType.BUSINESS_EXPANSION,
                "The team explicitly supports market growth and new-service launches.",
                0.88,
            ),
            (
                OpportunityType.OPERATIONS_IMPROVEMENT,
                "The official page emphasizes scalable programmes, tools and standards.",
                0.82,
            ),
        ],
        "job": {
            "title": "Expansion Lead",
            "url": "https://bolt.eu/en/careers/positions/52844f34-29a1-4b81-a84c-af758834e655/",
            "location": "Tallinn, Estonia · Hybrid",
            "description": "Full-time Global Operations role shown on Bolt's official careers site.",
        },
        "strategy": PositioningStrategy.BUSINESS_FIRST,
        "message_line": "Lead with more than ten years of project delivery, launches, partners, contractors, negotiations and regulated operations.",
        "secondary_advantage": "Add practical automation capability for playbooks, reporting and operational workflow improvement.",
        "rationale": "Bolt is the strongest direct test of Expansion and Operations fit, with a current official role and clear relocation constraints.",
        "value_proposition": "Connect central expansion priorities with disciplined local execution, partner coordination and practical process improvement.",
        "first_offer": "Compare the Expansion Lead scope with two relevant launch examples and identify the strongest evidence-backed fit.",
        "primary_dm": DecisionMakerRole.HEAD_OF_EXPANSION,
        "secondary_dm": DecisionMakerRole.HIRING_MANAGER,
        "collaboration": CollaborationFormat.FULL_TIME,
        "workplaces": [WorkplaceFormat.HYBRID, WorkplaceFormat.RELOCATION],
        "possible_role": "Expansion Lead / Expansion Project Manager",
    },
    {
        "name": "n8n",
        "domain": "n8n.io",
        "country": "Germany",
        "regions": ["Europe", "United Kingdom", "United States", "Global remote"],
        "industry": "AI orchestration and workflow automation",
        "stage": "high-growth technology company",
        "description": (
            "Workflow automation and AI-orchestration company used to test honest AI First "
            "positioning grounded in practical projects and business-process understanding."
        ),
        "source_url": "https://n8n.io/careers/",
        "source_fragment": (
            "You’re genuinely excited by AI and automation - not as hyped trends, but as meaningful tools for outcomes."
        ),
        "fact_type": "ai_automation_culture",
        "fact_value": "n8n publicly describes an outcome-oriented builder culture focused on practical AI and automation.",
        "hypothesis_title": "AI workflow implementation and operations enablement",
        "hypothesis_description": (
            "n8n may value a business-aware automation practitioner for implementation, "
            "customer workflows, internal operations or project coordination."
        ),
        "hypothesis_rationale": (
            "The official careers page emphasizes builders, AI-first processes, operational excellence and practical outcomes."
        ),
        "hypothesis_risks": [
            "The candidate must not be positioned as a senior AI or Python engineer",
            "A suitable opening and employment geography still require role-level verification",
        ],
        "opportunities": [
            (
                OpportunityType.AI_ADOPTION,
                "The company builds and uses AI orchestration as a core product and operating principle.",
                0.92,
            ),
            (
                OpportunityType.PROCESS_AUTOMATION,
                "Workflow automation is the company's core public product domain.",
                0.96,
            ),
            (
                OpportunityType.HYBRID_OPPORTUNITY,
                "The company explicitly combines technical building with business and operational outcomes.",
                0.78,
            ),
        ],
        "strategy": PositioningStrategy.AI_FIRST,
        "message_line": "Lead with practical n8n, Python, API and AI-automation projects at an honest developing level.",
        "secondary_advantage": "Differentiate through substantial project-management and business-process experience.",
        "rationale": "n8n directly tests whether the AI Automation profile is credible without inflating technical seniority.",
        "value_proposition": "Translate a real business workflow into a controlled automation prototype with clear human approval points.",
        "first_offer": "Build or map one small n8n workflow that demonstrates practical product understanding and measurable user value.",
        "primary_dm": DecisionMakerRole.HEAD_OF_OPERATIONS,
        "secondary_dm": DecisionMakerRole.TALENT_ACQUISITION,
        "collaboration": CollaborationFormat.PROJECT_BASED,
        "workplaces": [WorkplaceFormat.REMOTE],
        "possible_role": "AI Automation Project Specialist / Operations Automation",
    },
    {
        "name": "what3words",
        "domain": "what3words.com",
        "country": "United Kingdom",
        "regions": ["Global", "Europe", "Asia", "Africa", "Americas"],
        "industry": "Location technology and global partnerships",
        "stage": "international technology company",
        "description": (
            "Location-technology company used to test opportunity-first outreach without "
            "depending on a matching public vacancy."
        ),
        "source_url": "https://what3words.com/jobs",
        "source_fragment": (
            "Our BD team works with businesses around the world – from multinational car companies and logistics firms to thousands of SMEs using what3words to make their business more efficient."
        ),
        "fact_type": "global_partnership_model",
        "fact_value": "what3words describes a global business-development model spanning multinational companies, logistics firms and SMEs.",
        "hypothesis_title": "Partnership operations improvement without a vacancy dependency",
        "hypothesis_description": (
            "what3words may have project or advisory needs around partner onboarding, "
            "cross-functional delivery and scalable customer-operations workflows."
        ),
        "hypothesis_rationale": (
            "The official careers page describes global BD, Growth and Customer Operations functions but does not expose a matching open role in the reviewed page content."
        ),
        "hypothesis_risks": [
            "No matching public vacancy or explicit internal need was verified",
            "An unsolicited approach must offer a specific small value hypothesis rather than request a generic job",
        ],
        "opportunities": [
            (
                OpportunityType.GENERAL_COMPETENCE_FIT,
                "Global partnerships and customer operations plausibly match business and project experience.",
                0.62,
            ),
            (
                OpportunityType.OPERATIONS_IMPROVEMENT,
                "The company publicly links CRM, customer service, sales data and billing as scaling concerns.",
                0.66,
            ),
            (
                OpportunityType.CONSULTING,
                "A small discovery or workflow-mapping engagement can test fit without assuming a vacancy.",
                0.48,
            ),
        ],
        "strategy": PositioningStrategy.BUSINESS_FIRST,
        "message_line": "Lead with partnership-facing project delivery and the ability to structure complex cross-functional work.",
        "secondary_advantage": "Offer practical workflow automation as a bounded improvement tool for partner or customer operations.",
        "rationale": "what3words tests opportunity-first contact where competence fit exists but no matching vacancy is assumed.",
        "value_proposition": "Help map and simplify one partner-onboarding or customer-operations workflow across teams and systems.",
        "first_offer": "Share a one-page workflow map for one public partner journey and ask whether that operational problem is real.",
        "primary_dm": DecisionMakerRole.HEAD_OF_BUSINESS_DEVELOPMENT,
        "secondary_dm": DecisionMakerRole.HEAD_OF_OPERATIONS,
        "collaboration": CollaborationFormat.CONSULTING,
        "workplaces": [WorkplaceFormat.REMOTE],
        "possible_role": "Partnership Operations Project Specialist",
    },
    {
        "name": "Einride",
        "domain": "einride.tech",
        "country": "Sweden",
        "regions": ["Europe", "United States", "Middle East"],
        "industry": "Electric and autonomous freight technology",
        "stage": "international industrial technology scale-up",
        "description": (
            "Electric and autonomous freight company used to test transfer of infrastructure, "
            "launch and operations experience into a new technology-enabled industry."
        ),
        "source_url": "https://www.einride.tech/",
        "source_fragment": (
            "Road freight, redesigned. Autonomous and electric trucks, smart charging, and software—all connected through one platform."
        ),
        "fact_type": "integrated_freight_platform",
        "fact_value": "Einride publicly combines autonomous and electric trucks, charging infrastructure and AI-powered software in one operating platform.",
        "hypothesis_title": "Deployment coordination for technology-enabled freight operations",
        "hypothesis_description": (
            "Einride may value transferable experience in infrastructure deployment, partners, "
            "contractors, regulated launches and operational coordination."
        ),
        "hypothesis_rationale": (
            "The official site describes live end-to-end deployments across Europe, the US and the Middle East."
        ),
        "hypothesis_risks": [
            "The candidate has no verified direct electric-freight or autonomous-vehicle experience",
            "The message must lead with transferable delivery skills and avoid claiming sector expertise",
        ],
        "opportunities": [
            (
                OpportunityType.NEW_PRODUCT_OR_DIRECTION,
                "Einride is deploying an integrated electric, autonomous, charging and software platform.",
                0.82,
            ),
            (
                OpportunityType.OPERATIONS_IMPROVEMENT,
                "The product requires planning, deployment and ongoing freight operations.",
                0.78,
            ),
            (
                OpportunityType.HYBRID_OPPORTUNITY,
                "The opportunity combines physical infrastructure, operations and AI-enabled software.",
                0.84,
            ),
        ],
        "strategy": PositioningStrategy.HYBRID,
        "message_line": "Lead with infrastructure launches, contractors, partners, risks and operational project delivery.",
        "secondary_advantage": "Add practical AI-automation understanding as a bridge to software-enabled operations.",
        "rationale": "Einride tests honest transfer into a new industry where management experience matters more than claimed domain tenure.",
        "value_proposition": "Support a bounded deployment workstream by structuring stakeholders, risks, execution steps and lightweight automation.",
        "first_offer": "Map one deployment workstream and identify where coordination or reporting automation could reduce execution friction.",
        "primary_dm": DecisionMakerRole.HEAD_OF_OPERATIONS,
        "secondary_dm": DecisionMakerRole.HEAD_OF_PROJECTS,
        "collaboration": CollaborationFormat.PROJECT_BASED,
        "workplaces": [WorkplaceFormat.REMOTE, WorkplaceFormat.RELOCATION],
        "possible_role": "Deployment / Operations Project Manager",
    },
]


async def ensure_company(session: Any, item: dict[str, Any]) -> Company:
    company = await session.scalar(
        select(Company).where(Company.normalized_domain == item["domain"])
    )
    if company is not None:
        if company.is_synthetic:
            raise RuntimeError(f"Refusing to reuse synthetic company for {item['domain']}")
        return company
    return await create_company(
        CompanyCreate(
            name=item["name"],
            normalized_domain=item["domain"],
            is_synthetic=False,
            country=item["country"],
            operating_regions=item["regions"],
            industry=item["industry"],
            maturity_stage=item["stage"],
            description=item["description"],
            language_signals=["en"],
            next_action="Complete official-source research",
            note="Stage 10 first local pilot wave; no draft or external send without owner decision.",
        ),
        session,
    )


async def ensure_research_run(
    session: Any, company: Company, item: dict[str, Any], fetcher: SafeFetcher
) -> str:
    existing = await session.scalar(
        select(ResearchRun).where(
            ResearchRun.company_id == company.id,
            ResearchRun.requested_url == item["source_url"],
        )
    )
    if existing is not None:
        return existing.status
    request = SimpleNamespace(state=SimpleNamespace(request_id="stage10-first-wave"))
    try:
        result = await run_research(
            company.id,
            ResearchRequest(url=item["source_url"]),
            request,
            session,
            fetcher,
        )
        return result.run.status.value
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return f"failed:{detail.get('code', exc.status_code)}"


async def ensure_official_source(
    session: Any, company: Company, item: dict[str, Any]
) -> CompanySource:
    source = await session.scalar(
        select(CompanySource).where(
            CompanySource.company_id == company.id,
            CompanySource.url == item["source_url"],
        )
    )
    now = datetime.now(UTC)
    if source is None:
        text = item["source_fragment"]
        source = await create_source(
            company.id,
            CompanySourceCreate(
                url=item["source_url"],
                source_type="official_public_web",
                fetched_at=now,
                http_status=200,
                content_hash=sha256(text.encode("utf-8")).hexdigest(),
                extracted_text=text,
                language="en",
                trust_level="official_public",
                freshness_status="current",
            ),
            session,
        )
    else:
        source.source_type = "official_public_web"
        source.trust_level = "official_public"
        source.freshness_status = "current"
        source.error = None
        if not source.extracted_text:
            source.extracted_text = item["source_fragment"]
        await session.commit()
        await session.refresh(source)
    return source


async def ensure_verified_fact(
    session: Any, company: Company, source: CompanySource, item: dict[str, Any]
) -> CompanyFact:
    fact = await session.scalar(
        select(CompanyFact).where(
            CompanyFact.company_id == company.id,
            CompanyFact.source_id == source.id,
            CompanyFact.fact_type == item["fact_type"],
        )
    )
    if fact is None:
        fact = CompanyFact(
            company_id=company.id,
            source_id=source.id,
            fact_type=item["fact_type"],
            value=item["fact_value"],
            confidence=0.9,
            exact_fragment=item["source_fragment"],
            status="verified",
        )
        session.add(fact)
        add_event(
            session,
            company_id=company.id,
            event_type="company_fact_verified",
            summary=f"Official public fact verified: {item['fact_type']}",
            metadata={"source_id": str(source.id)},
        )
    else:
        fact.value = item["fact_value"]
        fact.exact_fragment = item["source_fragment"]
        fact.confidence = 0.9
        fact.status = "verified"
        fact.version += 1
    await session.commit()
    await session.refresh(fact)
    return fact


async def ensure_hypothesis(
    session: Any, company: Company, source: CompanySource, item: dict[str, Any]
) -> CompanyTaskHypothesis:
    hypothesis = await session.scalar(
        select(CompanyTaskHypothesis).where(
            CompanyTaskHypothesis.company_id == company.id,
            CompanyTaskHypothesis.title == item["hypothesis_title"],
        )
    )
    if hypothesis is None:
        hypothesis = CompanyTaskHypothesis(
            company_id=company.id,
            source_ids=[str(source.id)],
            title=item["hypothesis_title"],
            description=item["hypothesis_description"],
            rationale=item["hypothesis_rationale"],
            confidence=0.55,
            status="hypothesis",
            risks=item["hypothesis_risks"],
        )
        session.add(hypothesis)
        add_event(
            session,
            company_id=company.id,
            event_type="task_hypothesis_added",
            summary=f"Owner-review hypothesis added: {item['hypothesis_title']}",
            metadata={"source_id": str(source.id)},
        )
        await session.commit()
        await session.refresh(hypothesis)
    return hypothesis


async def ensure_opportunities(
    session: Any, company: Company, source: CompanySource, item: dict[str, Any]
) -> list[CompanyOpportunity]:
    results: list[CompanyOpportunity] = []
    for opportunity_type, rationale, confidence in item["opportunities"]:
        existing = await session.scalar(
            select(CompanyOpportunity).where(
                CompanyOpportunity.company_id == company.id,
                CompanyOpportunity.opportunity_type == opportunity_type.value,
            )
        )
        source_ids = list(
            dict.fromkeys([*(existing.source_ids if existing else []), str(source.id)])
        )
        if existing is None:
            existing = await create_opportunity(
                company.id,
                CompanyOpportunityCreate(
                    opportunity_type=opportunity_type,
                    rationale=rationale,
                    confidence=confidence,
                    source_ids=[source.id],
                    status=EvidenceStatus.VERIFIED,
                ),
                session,
            )
        else:
            existing = await update_opportunity(
                company.id,
                existing.id,
                CompanyOpportunityUpdate(
                    version=existing.version,
                    rationale=rationale,
                    confidence=confidence,
                    source_ids=source_ids,
                    status=EvidenceStatus.VERIFIED,
                ),
                session,
            )
        results.append(existing)
    return results


async def ensure_job(
    session: Any, company: Company, source: CompanySource, item: dict[str, Any]
) -> None:
    job_data = item.get("job")
    if not job_data:
        return
    existing = await session.scalar(
        select(JobOpening).where(
            JobOpening.company_id == company.id,
            JobOpening.url == job_data["url"],
        )
    )
    if existing is None:
        await create_job(
            JobCreate(
                company_id=company.id,
                source_id=source.id,
                title=job_data["title"],
                url=job_data["url"],
                location=job_data["location"],
                description=job_data["description"],
            ),
            session,
        )


async def ensure_recommendation(
    session: Any, company: Company, item: dict[str, Any]
) -> tuple[OpportunityAssessment, PositioningRecommendation]:
    recommendation = await session.scalar(
        select(PositioningRecommendation)
        .where(PositioningRecommendation.company_id == company.id)
        .order_by(PositioningRecommendation.created_at.desc())
    )
    if recommendation is not None:
        assessment = await session.get(OpportunityAssessment, recommendation.assessment_id)
        if assessment is None:
            raise RuntimeError(f"{company.name}: recommendation assessment is missing")
        return assessment, recommendation
    assessment = await calculate_company_relevance(company.id, session)
    recommendation = await create_recommendation(
        company.id,
        PositioningRecommendationCreate(
            assessment_id=assessment.id,
            primary_strategy=item["strategy"],
            primary_message_line=item["message_line"],
            secondary_advantage=item["secondary_advantage"],
            rationale=item["rationale"],
            value_proposition=item["value_proposition"],
            concrete_first_message_offer=item["first_offer"],
            primary_decision_maker_role=item["primary_dm"],
            secondary_decision_maker_role=item["secondary_dm"],
            collaboration_format=item["collaboration"],
            workplace_formats=item["workplaces"],
            possible_role=item["possible_role"],
        ),
        session,
    )
    return assessment, recommendation


async def advance_to_owner_decision(session: Any, company: Company) -> Company:
    await session.refresh(company)
    current = PipelineStatus(company.pipeline_status)
    if current == PipelineStatus.NEEDS_REVIEW:
        company = await update_company(
            company.id,
            CompanyUpdate(
                version=company.version, pipeline_status=PipelineStatus.OPPORTUNITY_IDENTIFIED
            ),
            session,
        )
        current = PipelineStatus(company.pipeline_status)
    if current != PipelineStatus.OPPORTUNITY_IDENTIFIED:
        if current == PipelineStatus.DECISION_PENDING:
            return company
        raise RuntimeError(f"{company.name}: scoring ended in unsupported status {current.value}")
    for target in (
        PipelineStatus.STRATEGY_SELECTED,
        PipelineStatus.CONTACT_MISSING,
        PipelineStatus.DECISION_PENDING,
    ):
        company = await update_company(
            company.id,
            CompanyUpdate(
                version=company.version,
                pipeline_status=target,
                next_action=(
                    "Owner decision required: outreach, deeper research, defer, watchlist or not relevant"
                    if target == PipelineStatus.DECISION_PENDING
                    else None
                ),
            ),
            session,
        )
    return company


async def main() -> None:
    results: list[dict[str, Any]] = []
    fetcher = SafeFetcher()
    async with SessionFactory() as session:
        for item in WAVE:
            company = await ensure_company(session, item)
            research_status = await ensure_research_run(session, company, item, fetcher)
            source = await ensure_official_source(session, company, item)
            fact = await ensure_verified_fact(session, company, source, item)
            hypothesis = await ensure_hypothesis(session, company, source, item)
            opportunities = await ensure_opportunities(session, company, source, item)
            await ensure_job(session, company, source, item)
            assessment, recommendation = await ensure_recommendation(session, company, item)
            company = await advance_to_owner_decision(session, company)
            results.append(
                {
                    "id": str(company.id),
                    "name": company.name,
                    "domain": company.normalized_domain,
                    "research": research_status,
                    "source": str(source.id),
                    "verified_fact": str(fact.id),
                    "hypothesis": str(hypothesis.id),
                    "opportunities": [entry.opportunity_type for entry in opportunities],
                    "score": assessment.overall_opportunity_score,
                    "positioning": recommendation.primary_strategy,
                    "primary_decision_maker_role": recommendation.primary_decision_maker_role,
                    "pipeline_status": company.pipeline_status,
                    "decision": recommendation.user_decision,
                }
            )
        drafts = list(await session.scalars(select(MessageDraft)))
        if drafts:
            raise RuntimeError("Safety check failed: first-wave preparation must not create drafts")
    print({"wave": results, "draft_count": 0})
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
