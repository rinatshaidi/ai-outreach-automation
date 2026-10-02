"""Idempotently seed a synthetic opportunity portfolio for the local demo."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.infrastructure.db.session import SessionFactory
from app.modules.crm.models import (
    Campaign,
    CommunicationEvent,
    Company,
    CompanySource,
    Contact,
    JobOpening,
)

SYNTHETIC_COMPANIES = (
    {
        "name": "Northstar Labs (Synthetic)",
        "domain": "northstar-labs.example",
        "country": "Finland",
        "industry": "Developer Tools",
        "company_size": "51-200",
        "maturity_stage": "scaleup",
        "opportunity_types": ["active_vacancy", "process_automation"],
        "positioning": "business_first",
        "collaboration": ["full_time"],
        "workplace": ["remote"],
        "role": "Operations-minded Engineering Lead",
        "scores": (84, 71, 80, 84),
        "pipeline": "decision_pending",
        "next_action": "Review the synthetic vacancy opportunity",
        "contact": ("Alex Example", "Engineering Manager", "head_of_operations"),
        "job": "Senior Python Engineer (Synthetic)",
    },
    {
        "name": "Atlas Industrial Group (Synthetic)",
        "domain": "atlas-industrial.example",
        "country": "Germany",
        "industry": "Industrial Services",
        "company_size": "1000+",
        "maturity_stage": "mature",
        "opportunity_types": ["general_competence_fit", "process_automation"],
        "positioning": "hybrid",
        "collaboration": ["project_based", "consulting"],
        "workplace": ["remote", "business_travel"],
        "role": "Operational transformation partner",
        "scores": (88, 82, 91, 89),
        "pipeline": "project_discussion",
        "next_action": "Prepare a synthetic project discussion agenda",
        "contact": ("Morgan Example", "COO", "coo"),
        "job": None,
    },
    {
        "name": "Orbit Commerce (Synthetic)",
        "domain": "orbit-commerce.example",
        "country": "Netherlands",
        "industry": "E-commerce",
        "company_size": "11-50",
        "maturity_stage": "early_stage",
        "opportunity_types": ["ai_automation_opportunity"],
        "positioning": "ai_first",
        "collaboration": ["project_based"],
        "workplace": ["remote"],
        "role": "Workflow automation advisor",
        "scores": (68, 90, 81, 82),
        "pipeline": "watchlist",
        "next_action": "Revisit synthetic automation signals next month",
        "contact": ("Taylor Example", "Head of Operations", "head_of_operations"),
        "job": None,
    },
)


async def seed_database() -> int:
    created = 0
    async with SessionFactory() as session:
        for fixture in SYNTHETIC_COMPANIES:
            existing = await session.scalar(
                select(Company).where(Company.normalized_domain == fixture["domain"])
            )
            if existing is not None:
                continue
            company_id = uuid4()
            contact_id = uuid4()
            business, ai, hybrid, overall = fixture["scores"]
            company = Company(
                id=company_id,
                name=fixture["name"],
                normalized_domain=fixture["domain"],
                is_synthetic=True,
                country=fixture["country"],
                industry=fixture["industry"],
                company_size=fixture["company_size"],
                maturity_stage=fixture["maturity_stage"],
                description="Synthetic company used only for the local product demo.",
                language_signals=["en"],
                opportunity_types=fixture["opportunity_types"],
                recommended_positioning=fixture["positioning"],
                recommended_collaboration_formats=fixture["collaboration"],
                recommended_workplace_formats=fixture["workplace"],
                recommended_role=fixture["role"],
                business_fit_score=business,
                ai_automation_fit_score=ai,
                hybrid_fit_score=hybrid,
                overall_opportunity_score=overall,
                relevance_score=overall,
                relevance_status="opportunity_identified",
                pipeline_status=fixture["pipeline"],
                next_action=fixture["next_action"],
                last_researched_at=datetime.now(UTC),
            )
            contact_name, contact_role, decision_role = fixture["contact"]
            source_id = uuid4()
            records: list[object] = [
                company,
                CompanySource(
                    id=source_id,
                    company_id=company_id,
                    url=f"https://{fixture['domain']}/about",
                    source_type="company_website",
                    fetched_at=datetime.now(UTC),
                    http_status=200,
                    content_hash=f"synthetic-{company_id}",
                    extracted_text="Synthetic public company description.",
                    language="en",
                    trust_level="verified",
                    freshness_status="fresh",
                ),
                Contact(
                    id=contact_id,
                    company_id=company_id,
                    name=contact_name,
                    role=contact_role,
                    email=f"contact@{fixture['domain']}",
                    verification_status="verified",
                    confidence=1.0,
                    lawful_public_source_note="Synthetic team page in the local demo fixture",
                    decision_maker_role=decision_role,
                    decision_priority=1,
                    source_id=source_id,
                ),
            ]
            if fixture["job"]:
                records.append(
                    JobOpening(
                        id=uuid4(),
                        company_id=company_id,
                        source_id=source_id,
                        title=fixture["job"],
                        location="Remote, Europe",
                        url=f"https://{fixture['domain']}/jobs/synthetic-role",
                        required_skills=["Python", "FastAPI", "PostgreSQL"],
                    )
                )
            session.add_all(records)
            created += len(records)
            await session.flush()
            session.add(
                CommunicationEvent(
                    id=uuid4(),
                    company_id=company_id,
                    contact_id=contact_id,
                    event_type="synthetic_demo_seeded",
                    summary="Synthetic opportunity portfolio record added",
                )
            )
            created += 1
            await session.flush()

        campaign = await session.scalar(
            select(Campaign).where(Campaign.name == "Synthetic opportunity portfolio")
        )
        if campaign is None:
            session.add(
                Campaign(
                    id=uuid4(),
                    name="Synthetic opportunity portfolio",
                    goal="Evaluate opportunity-first analytics using synthetic data",
                    opportunity_types=[
                        "general_competence_fit",
                        "process_automation",
                        "active_vacancy",
                    ],
                    positioning_strategies=["business_first", "ai_first", "hybrid"],
                    preferred_language="en",
                    daily_limit=5,
                    followup_policy={
                        "enabled": True,
                        "interval_business_days": 5,
                        "max_followups": 1,
                    },
                    status="draft",
                )
            )
            created += 1
        await session.commit()
        return created


def main() -> None:
    settings = get_settings()
    if not settings.demo_mode or settings.allow_real_email:
        raise RuntimeError("Synthetic seed requires DEMO_MODE=true and ALLOW_REAL_EMAIL=false")
    records = asyncio.run(seed_database())
    print(json.dumps({"event": "synthetic_seed_completed", "records": records}))


if __name__ == "__main__":
    main()
