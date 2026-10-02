"""Actionable Opportunity acceptance criteria and public-contact readiness."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.candidate_profile.models import CandidateProfile
from app.modules.crm.models import Company, CompanySource, Contact, JobOpening
from app.modules.opportunities.models import CompanyOpportunity, PositioningRecommendation
from app.modules.opportunities.presentation import localized_dynamic_text
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis, ResearchRun


class ContactStatus(StrEnum):
    FOUND = "CONTACT_FOUND"
    PARTIAL = "CONTACT_PARTIAL"
    RESEARCH_REQUIRED = "CONTACT_RESEARCH_REQUIRED"
    NO_VALID_CONTACT = "NO_VALID_CONTACT"


class OpportunityStage(StrEnum):
    ACTIONABLE = "ACTIONABLE_OPPORTUNITY"
    CANDIDATE = "COMPANY_CANDIDATE"


class RecommendedAction(StrEnum):
    OUTREACH = "OUTREACH"
    CONTACT_RESEARCH_REQUIRED = "CONTACT_RESEARCH_REQUIRED"
    DEEPER_RESEARCH = "DEEPER_RESEARCH"


class ContactPathSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    role: str | None
    why_relevant: str
    contact_type: str
    channel: str
    source: str
    confidence: float
    validation_status: str
    validated_at: datetime | None
    validation_http_status: int | None
    validation_final_url: str | None


class OpportunityReadiness(BaseModel):
    stage: OpportunityStage
    actionable: bool
    contact_status: ContactStatus
    recommended_action: RecommendedAction
    research_confidence: float = Field(ge=0, le=1)
    checks: dict[str, bool]
    blockers: list[str]
    primary_contact: ContactPathSummary | None
    alternative_contact: ContactPathSummary | None
    what_it_does: str
    why_selected: str
    most_realistic_opportunity: str
    why_user_fits: str
    collaboration_scenarios: list[str]
    work_format: str
    geography: str
    language_risk: str
    vacancy_status: str
    main_upside: str
    main_risk: str


VERIFIED_CONTACT_STATUSES = {"verified", "verified_public", "provider_verified"}
VERIFIED_PATH_STATUS = "VERIFIED_CONTACT"

AIRALO_DESCRIPTION = (
    "Global eSIM and connectivity company used to test Business First, international growth "
    "and distributed operations fit."
)
AIRALO_HYPOTHESIS = (
    "Airalo may have project needs around cross-functional growth, partner coordination and "
    "repeatable operating processes across countries."
)
AIRALO_PROFILE_FIT = (
    "Airalo primarily tests transferable business and operating experience in a global remote "
    "company."
)
AIRALO_VALUE_PROPOSITION = (
    "Help structure a cross-functional growth or partner workflow and turn it into a clear, "
    "repeatable operating process."
)

RU_PRESENTATION_TEXT = {
    AIRALO_DESCRIPTION: (
        "Международная Travel Tech / eSIM-компания с распределённой командой и глобальной "
        "партнёрской моделью."
    ),
    "The official careers site publicly presents current recruitment activity.": (
        "Компания работает глобально и публично развивает международную команду."
    ),
    AIRALO_HYPOTHESIS: (
        "Наиболее реалистична проектная помощь в координации партнёров, международных "
        "операций и создании повторяемых рабочих процессов."
    ),
    AIRALO_PROFILE_FIT: (
        "Подходит управленческий опыт Рината в развитии бизнеса, запусках, переговорах и "
        "координации сложных процессов; AI Automation выступает дополнительным усилителем."
    ),
    "Global operations create a plausible need for structured cross-functional growth delivery.": (
        "Проектная координация международного роста и межфункциональных задач."
    ),
    "Distributed work can make repeatable operating workflows and coordination valuable.": (
        "Структурирование повторяемых операционных и партнёрских процессов."
    ),
    AIRALO_VALUE_PROPOSITION: (
        "Предложить небольшой диагностический проект по партнёрскому или операционному "
        "процессу и превратить его в понятный повторяемый workflow."
    ),
    "No explicit public need or timing signal was detected": (
        "Не подтверждена конкретная потребность Airalo в такой роли или проекте прямо сейчас."
    ),
    "Selection rationale requires research": "Причина выбора требует дополнительного исследования.",
    "Opportunity hypothesis requires research": (
        "Гипотеза возможности требует дополнительного исследования."
    ),
    "Personal fit requires assessment": "Соответствие профиля требует оценки.",
    "Description requires research": "Описание компании требует исследования.",
    "Requires positioning": "Необходимо определить позиционирование.",
    "Risk review required": "Необходимо проверить риски.",
}

RU_FORMATS = {
    "full_time": "полная занятость",
    "part_time": "частичная занятость",
    "project_based": "проектная работа",
    "contract": "контракт",
    "consulting": "консалтинг",
    "advisory": "экспертная поддержка",
    "remote": "удалённо",
    "hybrid": "гибридно",
    "on_site": "на месте",
    "relocation": "с переездом",
}


def _presentation_text(value: str, locale: str) -> str:
    return localized_dynamic_text(value, locale)


def _channel(contact: Contact) -> tuple[str, str] | None:
    verified_channels = sorted(
        (item for item in contact.channels if item.validation_status == "VERIFIED"),
        key=lambda item: item.confidence,
        reverse=True,
    )
    if verified_channels:
        best = verified_channels[0]
        return best.channel_type, best.url or best.value
    if contact.email:
        return "business_email", contact.email
    if contact.linkedin:
        return "professional_profile", contact.linkedin
    if contact.telegram:
        return "public_messaging", contact.telegram
    if contact.other_public_link:
        return "official_contact_form_or_profile", contact.other_public_link
    return None


def _valid_contact(contact: Contact) -> bool:
    verified_channel = next(
        (item for item in contact.channels if item.validation_status == "VERIFIED"), None
    )
    return bool(
        not contact.do_not_contact
        and contact.verification_status in VERIFIED_CONTACT_STATUSES
        and contact.validation_status == VERIFIED_PATH_STATUS
        and contact.validated_at is not None
        and _channel(contact)
        and (
            contact.lawful_public_source_note
            or contact.source_id
            or (verified_channel and verified_channel.source_url)
        )
    )


def _contact_summary(contact: Contact, locale: str) -> ContactPathSummary:
    contact_type, channel = _channel(contact) or ("missing", "")
    relevance = contact.decision_maker_role or contact.role or "public company contact"
    relevance_ru = {
        "head_of_operations": "руководитель операционного направления",
        "head_of_business_development": "руководитель развития бизнеса",
        "country_manager": "руководитель направления в стране",
        "recruiter": "специалист по подбору персонала",
        "public company contact": "официальный контакт компании",
        "Public contact": "официальный контакт компании",
    }.get(relevance, localized_dynamic_text(relevance, "ru"))
    return ContactPathSummary(
        id=str(contact.id),
        name=(
            "Официальный контакт компании"
            if locale == "ru" and contact.name == "Public company contact"
            else contact.name
        ),
        role=(
            "Официальный публичный канал"
            if locale == "ru" and contact.role == "Public contact"
            else contact.role
        ),
        why_relevant=(
            f"Публичный канал для релевантной роли: {relevance_ru}"
            if locale == "ru"
            else f"Public path for the relevant role: {relevance}"
        ),
        contact_type=contact_type,
        channel=channel,
        source=(
            "Официальный публичный источник"
            if locale == "ru"
            else "Official public source"
        ),
        confidence=float(contact.confidence or 0),
        validation_status=contact.validation_status,
        validated_at=contact.validated_at,
        validation_http_status=contact.validation_http_status,
        validation_final_url=contact.validation_final_url,
    )


def _contact_status(contacts: list[Contact]) -> tuple[ContactStatus, list[Contact]]:
    valid = [item for item in contacts if _valid_contact(item)]
    if valid:
        return ContactStatus.FOUND, valid
    partial = [
        item
        for item in contacts
        if not item.do_not_contact
        and _channel(item)
        and item.validation_status != "INVALID_CONTACT"
    ]
    if partial:
        return ContactStatus.PARTIAL, partial
    if contacts:
        return ContactStatus.NO_VALID_CONTACT, []
    return ContactStatus.RESEARCH_REQUIRED, []


def _best(items: list[Any], attribute: str, default: Any = None) -> Any:
    if not items:
        return default
    return max(items, key=lambda item: float(getattr(item, attribute, 0) or 0))


def _source_backed_scenarios(opportunities: list[CompanyOpportunity]) -> list[str]:
    """Return draft-eligible scenarios with persisted provenance."""

    return [
        item.rationale
        for item in opportunities
        if is_source_backed_opportunity(item)
    ][:3]


def is_source_backed_opportunity(item: CompanyOpportunity) -> bool:
    """Accept an opportunity only when it is not rejected and carries provenance."""

    return item.status != "rejected" and bool(item.source_ids or item.signal_ids)


async def evaluate_opportunity_readiness(
    session: AsyncSession, company: Company, *, locale: str = "en"
) -> OpportunityReadiness:
    company_id = company.id
    sources = list(
        await session.scalars(
            select(CompanySource).where(CompanySource.company_id == company_id)
        )
    )
    facts = list(
        await session.scalars(select(CompanyFact).where(CompanyFact.company_id == company_id))
    )
    hypotheses = list(
        await session.scalars(
            select(CompanyTaskHypothesis).where(
                CompanyTaskHypothesis.company_id == company_id,
                CompanyTaskHypothesis.status != "rejected",
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
    recommendations = list(
        await session.scalars(
            select(PositioningRecommendation)
            .where(PositioningRecommendation.company_id == company_id)
            .order_by(PositioningRecommendation.created_at.desc())
        )
    )
    contacts = list(
        await session.scalars(
            select(Contact)
            .where(Contact.company_id == company_id)
            .options(selectinload(Contact.channels))
            .order_by(
                Contact.discovery_score.desc().nullslast(),
                Contact.decision_priority.asc().nullslast(),
                Contact.created_at,
            )
        )
    )
    jobs = list(
        await session.scalars(
            select(JobOpening).where(
                JobOpening.company_id == company_id,
                JobOpening.active.is_(True),
            )
        )
    )
    research_runs = list(
        await session.scalars(
            select(ResearchRun).where(ResearchRun.company_id == company_id)
        )
    )
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )

    provenance_sources = [
        item
        for item in sources
        if item.trust_level == "official_public"
        or (
            item.http_status is not None
            and 200 <= item.http_status < 300
            and item.fetched_at is not None
            and item.freshness_status == "current"
            and not item.error
        )
    ]
    provenance_source_ids = {item.id for item in provenance_sources}
    verified_facts = [
        item
        for item in facts
        if item.status == "verified" and item.source_id in provenance_source_ids
    ]
    verified_opportunities = [item for item in opportunities if item.status == "verified"]
    official_sources = [item for item in sources if item.trust_level == "official_public"]
    current_sources = [item for item in official_sources if item.freshness_status == "current"]
    completed_research = [item for item in research_runs if item.status == "completed"]
    recommendation = recommendations[0] if recommendations else None
    hypothesis = _best(hypotheses, "confidence")
    opportunity = _best(verified_opportunities or opportunities, "confidence")

    research_confidence = min(
        1.0,
        (0.4 if verified_facts else 0)
        + (0.2 if hypothesis and hypothesis.confidence >= 0.4 else 0)
        + (0.2 if verified_opportunities else 0)
        + (0.1 if current_sources else 0)
        + (0.1 if completed_research or official_sources else 0),
    )
    contact_status, usable_contacts = _contact_status(contacts)
    primary_contact = (
        _contact_summary(usable_contacts[0], locale) if usable_contacts else None
    )
    alternative_contact = (
        _contact_summary(usable_contacts[1], locale) if len(usable_contacts) > 1 else None
    )

    # A scenario is source-backed when the opportunity carries direct source or
    # signal provenance. Older executor runs could leave that record in
    # ``proposed`` even though the evidence links were already persisted. Do not
    # block an owner-requested draft merely because of that stale workflow label;
    # rejected or unsupported opportunities remain excluded.
    scenarios = _source_backed_scenarios(opportunities)
    feasibility = bool(
        recommendation
        and recommendation.collaboration_format
        and recommendation.workplace_formats
        and company.country
        and company.language_signals
    )
    vacancy_status = (
        f"OPEN_VACANCY_RECORDED: {jobs[0].title}"
        if jobs
        else "NO_MATCHING_VACANCY_RECORDED (not proof that no vacancy exists)"
    )
    risks = [risk for item in hypotheses for risk in (item.risks or [])]
    checks = {
        "company_identity": bool(company.name and company.normalized_domain),
        "source_backed_description": bool(company.description and verified_facts),
        "opportunity_hypothesis": hypothesis is not None,
        "personal_fit_explained": bool(recommendation and recommendation.rationale),
        "collaboration_scenarios": bool(scenarios),
        "feasibility_checked": feasibility,
        "vacancy_status_known": bool(vacancy_status),
        "main_risks_recorded": bool(completed_research),
        "overall_recommendation": recommendation is not None,
        "public_contact_path": contact_status == ContactStatus.FOUND,
        "major_facts_have_provenance": bool(verified_facts and provenance_sources),
        "research_confidence_sufficient": research_confidence >= 0.7,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    actionable = not blockers
    if actionable:
        recommended_action = RecommendedAction.OUTREACH
    elif contact_status != ContactStatus.FOUND:
        recommended_action = RecommendedAction.CONTACT_RESEARCH_REQUIRED
    else:
        recommended_action = RecommendedAction.DEEPER_RESEARCH

    language_level = profile.language_level if profile else None
    localized_language_level = (
        localized_dynamic_text(language_level, locale) if language_level else None
    )
    language_risk = (
        "English company context; candidate English level: "
        f"{localized_language_level or 'not confirmed'}"
        if "en" in company.language_signals
        else f"Company language signals: {', '.join(company.language_signals) or 'unknown'}"
    )
    workplace_values = recommendation.workplace_formats if recommendation else []
    workplace = ", ".join(
        RU_FORMATS.get(item, item) if locale == "ru" else item for item in workplace_values
    ) or ("не определено" if locale == "ru" else "unknown")
    collaboration_value = recommendation.collaboration_format if recommendation else "unknown"
    collaboration = (
        RU_FORMATS.get(collaboration_value, collaboration_value)
        if locale == "ru"
        else collaboration_value
    )
    if locale == "ru":
        vacancy_status = (
            f"ОТКРЫТАЯ ВАКАНСИЯ: {jobs[0].title}"
            if jobs
            else "ПОДХОДЯЩАЯ ВАКАНСИЯ НЕ НАЙДЕНА — это не доказывает её отсутствие"
        )
        language_risk = (
            "Язык коммуникации: английский. Уровень английского кандидата: "
            f"{localized_language_level or 'не подтверждён'}"
            if "en" in company.language_signals
            else "Языковые сигналы компании: "
            f"{', '.join(company.language_signals) or 'не определены'}"
        )
    hypothesis_text = (
        hypothesis.description if hypothesis else "Opportunity hypothesis requires research"
    )
    return OpportunityReadiness(
        stage=OpportunityStage.ACTIONABLE if actionable else OpportunityStage.CANDIDATE,
        actionable=actionable,
        contact_status=contact_status,
        recommended_action=recommended_action,
        research_confidence=round(research_confidence, 2),
        checks=checks,
        blockers=blockers,
        primary_contact=primary_contact,
        alternative_contact=alternative_contact,
        what_it_does=_presentation_text(
            company.description or "Description requires research", locale
        ),
        why_selected=(
            _presentation_text(
                opportunity.rationale if opportunity else "Selection rationale requires research",
                locale,
            )
        ),
        most_realistic_opportunity=(
            _presentation_text(
                hypothesis_text,
                locale,
            )
        ),
        why_user_fits=(
            _presentation_text(
                recommendation.rationale if recommendation else "Personal fit requires assessment",
                locale,
            )
        ),
        collaboration_scenarios=[_presentation_text(item, locale) for item in scenarios],
        work_format=f"{collaboration}; {workplace}",
        geography=(
            f"{localized_dynamic_text(company.country, locale)}; {workplace}"
            if company.country
            else f"{'не определено' if locale == 'ru' else 'unknown'}; {workplace}"
        ),
        language_risk=language_risk,
        vacancy_status=vacancy_status,
        main_upside=(
            _presentation_text(
                recommendation.value_proposition if recommendation else "Requires positioning",
                locale,
            )
        ),
        main_risk=_presentation_text(risks[0] if risks else "Risk review required", locale),
    )
