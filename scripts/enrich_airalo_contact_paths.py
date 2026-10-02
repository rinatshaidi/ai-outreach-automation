"""Calibrate Airalo contactability with lawful official public sources only.

The operation is idempotent. It does not create drafts, make an owner outreach
decision, send messages, or research any other first-wave company.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.api.crm import (
    add_event,
    create_contact,
    get_contact_validator,
    update_company,
)
from app.api.crm import (
    validate_contact as validate_contact_record,
)
from app.api.opportunities import create_source
from app.infrastructure.db.session import SessionFactory, close_database
from app.modules.crm.models import Company, CompanySource, Contact
from app.modules.crm.schemas import (
    CompanyUpdate,
    ContactCreate,
    PipelineStatus,
    VerificationStatus,
)
from app.modules.opportunities.readiness import evaluate_opportunity_readiness
from app.modules.opportunities.schemas import CompanySourceCreate, DecisionMakerRole
from app.modules.research.models import CompanyFact

AIRALO_DOMAIN = "airalo.com"
PARTNERS_URL = "https://partners.airalo.com/"
CONTACT_SALES_URL = (
    "https://app.partners.airalo.com/onboarding/contact-us?utm_content=cms-value-landing-pages"
)
COO_PROFILE_URL = "https://www.airalo.com/ka/about-us/abraham-burak"
GENERAL_CONTACT_URL = "https://www.airalo.com/more-info/contact/"


async def ensure_source(
    session: object,
    company: Company,
    *,
    url: str,
    source_type: str,
    extracted_text: str,
) -> CompanySource:
    existing = await session.scalar(  # type: ignore[attr-defined]
        select(CompanySource).where(
            CompanySource.company_id == company.id,
            CompanySource.url == url,
        )
    )
    if existing is not None:
        return existing
    return await create_source(
        company.id,
        CompanySourceCreate(
            url=url,
            source_type=source_type,
            fetched_at=datetime.now(UTC),
            http_status=200,
            extracted_text=extracted_text,
            language="en",
            trust_level="official_public",
            freshness_status="current",
        ),
        session,  # type: ignore[arg-type]
    )


async def ensure_contact(
    session: object,
    company: Company,
    source: CompanySource,
    *,
    name: str,
    role: str,
    url: str,
    decision_maker_role: DecisionMakerRole,
    priority: int,
    confidence: float,
    source_note: str,
) -> Contact:
    existing = await session.scalar(  # type: ignore[attr-defined]
        select(Contact).where(
            Contact.company_id == company.id,
            Contact.other_public_link == url,
        )
    )
    if existing is not None:
        return existing
    return await create_contact(
        ContactCreate(
            company_id=company.id,
            name=name,
            role=role,
            other_public_link=url,
            verification_status=VerificationStatus.VERIFIED_PUBLIC,
            confidence=confidence,
            lawful_public_source_note=source_note,
            decision_maker_role=decision_maker_role,
            decision_priority=priority,
            source_id=source.id,
        ),
        session,  # type: ignore[arg-type]
    )


async def main() -> None:
    async with SessionFactory() as session:
        company = await session.scalar(
            select(Company).where(Company.normalized_domain == AIRALO_DOMAIN)
        )
        if company is None:
            raise RuntimeError("Airalo company candidate is missing")

        before = await evaluate_opportunity_readiness(session, company)
        if (
            company.pipeline_status == PipelineStatus.DECISION_PENDING.value
            and not before.actionable
        ):
            company = await update_company(
                company.id,
                CompanyUpdate(
                    version=company.version,
                    pipeline_status=PipelineStatus.CONTACT_RESEARCH_REQUIRED,
                    next_action="Complete lawful public contact research before owner decision",
                ),
                session,
            )

        partners_source = await ensure_source(
            session,
            company,
            url=PARTNERS_URL,
            source_type="official_partnership_page",
            extracted_text=(
                "Airalo Partners presents business partnership products and links to an official "
                "Contact sales form."
            ),
        )
        contact_source = await ensure_source(
            session,
            company,
            url=CONTACT_SALES_URL,
            source_type="official_contact_form",
            extracted_text="Official Airalo Partners Contact sales form.",
        )
        coo_source = await ensure_source(
            session,
            company,
            url=COO_PROFILE_URL,
            source_type="official_leadership_profile",
            extracted_text="Official Airalo profile for Co-Founder and COO Abraham Burak.",
        )
        general_contact_source = await ensure_source(
            session,
            company,
            url=GENERAL_CONTACT_URL,
            source_type="official_contact_page",
            extracted_text=(
                "Official Airalo Contact us page offers support and partnership inquiries."
            ),
        )

        contact_fact = await session.scalar(
            select(CompanyFact).where(
                CompanyFact.company_id == company.id,
                CompanyFact.fact_type == "official_contact_path",
                CompanyFact.source_id == partners_source.id,
            )
        )
        if contact_fact is None:
            contact_fact = CompanyFact(
                company_id=company.id,
                source_id=partners_source.id,
                fact_type="official_contact_path",
                value="Airalo publishes an official Contact sales path for business partnerships.",
                confidence=0.98,
                exact_fragment="Contact sales",
                status="verified",
            )
            session.add(contact_fact)
            add_event(
                session,
                company_id=company.id,
                event_type="company_fact_verified",
                summary="Official Airalo partnership contact path verified",
                metadata={"source_id": str(partners_source.id)},
            )
            await session.commit()

        primary = await ensure_contact(
            session,
            company,
            contact_source,
            name="Airalo Partners Sales Team",
            role="Official business and partnership contact path",
            url=CONTACT_SALES_URL,
            decision_maker_role=DecisionMakerRole.HEAD_OF_BUSINESS_DEVELOPMENT,
            priority=1,
            confidence=0.98,
            source_note=(
                "Official Airalo Partners page links directly to this public Contact sales form."
            ),
        )
        invalid_alternative = await ensure_contact(
            session,
            company,
            coo_source,
            name="Abraham Burak",
            role="Co-Founder and COO",
            url=COO_PROFILE_URL,
            decision_maker_role=DecisionMakerRole.COO,
            priority=2,
            confidence=0.9,
            source_note=(
                "Official public Airalo leadership profile identifies the Co-Founder and COO."
            ),
        )
        alternative = await ensure_contact(
            session,
            company,
            general_contact_source,
            name="Airalo Contact and Partnership Support",
            role="Official alternative contact path for partnership inquiries",
            url=GENERAL_CONTACT_URL,
            decision_maker_role=DecisionMakerRole.HEAD_OF_BUSINESS_DEVELOPMENT,
            priority=2,
            confidence=0.9,
            source_note=(
                "Official Airalo Contact us page explicitly includes partnership opportunities."
            ),
        )

        validator = get_contact_validator()
        invalid_alternative = await validate_contact_record(
            invalid_alternative.id,
            session,
            validator,
        )
        if invalid_alternative.validation_status == "INVALID_CONTACT":
            coo_source.http_status = invalid_alternative.validation_http_status
            coo_source.fetched_at = invalid_alternative.validated_at
            coo_source.freshness_status = "stale"
            coo_source.error = invalid_alternative.validation_error
            coo_source.version += 1
            await session.commit()
        primary = await validate_contact_record(primary.id, session, validator)
        alternative = await validate_contact_record(alternative.id, session, validator)

        after = await evaluate_opportunity_readiness(session, company)
        if after.actionable and company.pipeline_status == PipelineStatus.CONTACT_RESEARCH_REQUIRED:
            for target, next_action in (
                (PipelineStatus.CONTACT_FOUND, "Review the actionable Airalo opportunity"),
                (PipelineStatus.DECISION_PENDING, "Owner decision required; no draft created"),
            ):
                company = await update_company(
                    company.id,
                    CompanyUpdate(
                        version=company.version,
                        pipeline_status=target,
                        next_action=next_action,
                    ),
                    session,
                )

        final = await evaluate_opportunity_readiness(session, company)
        print(
            {
                "company_id": str(company.id),
                "before": before.model_dump(mode="json"),
                "after": final.model_dump(mode="json"),
                "pipeline_status": company.pipeline_status,
                "primary_contact_id": str(primary.id),
                "alternative_contact_id": str(alternative.id),
                "invalid_contact_id": str(invalid_alternative.id),
                "primary_validation": primary.validation_status,
                "alternative_validation": alternative.validation_status,
                "invalid_validation": invalid_alternative.validation_status,
                "drafts_created": 0,
                "messages_sent": 0,
            }
        )
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
