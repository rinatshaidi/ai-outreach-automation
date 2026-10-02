"""Evidence-backed company decision synthesis for the owner workspace.

Only public company material is sent to the optional AI provider. Candidate
Profile records and owner personal data never leave the application here.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.modules.candidate_profile.models import CandidateProfile
from app.modules.crm.contact_presentation import present_contact
from app.modules.crm.contact_shortlist import has_usable_verified_route
from app.modules.crm.models import Company, CompanySource, Contact, JobOpening
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    OpportunitySignal,
    PositioningRecommendation,
)
from app.modules.opportunities.quality import (
    CAPABILITIES,
    build_match_theses,
    company_evidence_excerpt,
    job_risks,
    language_matches,
    profile_records,
)
from app.modules.research.models import CompanyDecisionSynthesis, CompanyFact

MAX_SOURCE_CHARS = 3500
QUALITY_VERSION = 5
# Public-evidence summaries are short.  A bounded timeout keeps one stalled
# provider request from blocking the search worker or a calibration batch.
COMPANY_SYNTHESIS_TIMEOUT_SECONDS = 45.0


def _clean(value: str | None, limit: int = 900) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    # Do not leave owner-facing evidence hanging on a cut-off word. Prefer a
    # complete sentence; otherwise cut at a word boundary and disclose it.
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    complete: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*complete, sentence])
        if len(candidate) > limit:
            break
        complete.append(sentence)
    if complete:
        return " ".join(complete)
    return cleaned[: limit - 1].rsplit(" ", maxsplit=1)[0].rstrip(" ,;:") + "…"


def _first_sentence(value: str | None, limit: int = 260) -> str:
    cleaned = _clean(value, limit * 2)
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)
    return parts[0][:limit]


def _outreach_company_fact(value: str | None, limit: int = 240) -> str:
    """Return one complete, recipient-safe company fact for a message.

    The research card may retain a longer evidence excerpt. A letter must not
    quote an unfinished scrape, a truncated list, or a raw source fragment.
    """

    raw = " ".join((value or "").split())
    if not raw or raw.endswith("…"):
        return ""
    complete = re.search(r"^(.{1," + str(limit) + r"}[.!?])(?:\s|$)", raw)
    return complete.group(1).strip() if complete else ""


def _recommendation(company: Company, has_contact: bool) -> str:
    if (
        company.identity_verification_status != "verified"
        or company.geography_verification_status == "mismatch"
    ):
        return "not_recommended"
    score = float(company.overall_opportunity_score or 0)
    if score >= 75 and has_contact:
        return "high_interest"
    if score >= 50:
        return "worth_considering"
    return "weak_match"


def _fit_text(strategy: str | None, locale: str) -> str:
    if locale == "ru":
        values = {
            "business_first": (
                "Наиболее реалистична управленческая линия: запуск проектов, развитие бизнеса, "
                "координация команд и подрядчиков. AI Automation стоит использовать как "
                "дополнительное преимущество, а не как заявление уровня senior ML engineer."
            ),
            "ai_first": (
                "Совпадение строится на практических AI/Python automation-проектах и способности "
                "перевести бизнес-задачу в рабочий процесс. Позиционирование должно оставаться "
                "честным: практик автоматизации, не senior AI/ML engineer."
            ),
            "hybrid": (
                "Лучшее совпадение — на пересечении управления, развития бизнеса и практической "
                "автоматизации: понять процесс, организовать запуск и довести решение "
                "до результата."
            ),
        }
        return values.get(strategy or "", "Соответствие профилю требует решения владельца.")
    values = {
        "business_first": (
            "The strongest angle is project delivery, business development and cross-functional "
            "coordination, with AI Automation as a supporting capability rather than a senior "
            "ML claim."
        ),
        "ai_first": (
            "The fit is based on practical AI/Python automation work and translating business "
            "needs "
            "into workflows, without positioning as a senior AI/ML engineer."
        ),
        "hybrid": (
            "The strongest fit combines project and business execution with practical automation: "
            "understand the process, organize delivery and launch a useful solution."
        ),
    }
    return values.get(strategy or "", "The owner should review the profile fit.")


def _missing(locale: str, kind: str) -> str:
    ru = {
        "scale": "Надёжных данных о размере команды в проверенных открытых источниках не найдено.",
        "current": "Сильного актуального сигнала после проверки доступных источников не найдено.",
        "contact": (
            "Проверенный публичный контакт пока не найден; поиск контакта следует продолжить."
        ),
        "founders": "Проверенные сведения об основателях или руководстве пока не найдены.",
    }
    en = {
        "scale": "No reliable team-size data was found in the checked public sources.",
        "current": "No strong current signal was found in the checked sources.",
        "contact": (
            "No verified public contact path has been found; contact research should continue."
        ),
        "founders": "Verified founder or leadership information has not yet been found.",
    }
    return (ru if locale == "ru" else en)[kind]


def _primary_match(
    match: dict[str, Any] | None, contact: Contact | None, locale: str
) -> dict[str, Any]:
    """Make one source-of-truth collaboration angle for the owner workflow.

    It is deliberately deterministic: public company evidence and already
    verified profile evidence are linked locally. No owner data is sent to an
    external provider and no generic positioning recommendation can replace it.
    """

    if not match:
        return {}
    ru = locale == "ru"
    company_context = _clean(match.get("company_evidence"), 360)
    outreach_company_fact = _outreach_company_fact(match.get("company_evidence"))
    candidate_evidence = _clean(match.get("candidate_evidence") or match.get("label"), 420)
    value_hypothesis = _clean(match.get("contribution"), 360)
    contact_role = _clean((contact.role if contact else ""), 160)
    contact_view = present_contact(contact, locale) if contact else None
    if ru:
        intersection = (
            f"Компания публично сообщает: {company_context}. Ваш подтверждённый опыт: "
            f"{candidate_evidence}. Это создаёт обоснованную гипотезу: {value_hypothesis}."
        )
        collaboration_format = (
            "Короткий исследовательский разговор о конкретной задаче; формат сотрудничества "
            "определяется только после этого разговора."
        )
        outreach_angle = (
            "Мне было бы интересно коротко обсудить, может ли такой опыт быть полезен "
            "для разбора или автоматизации конкретного рабочего процесса."
        )
        outreach_guidance = (
            "Связать подтверждённый факт компании с опытом кандидата и не утверждать, "
            "что у команды есть неподтверждённая внутренняя задача."
        )
        confidence = "Подтверждены публичный сигнал компании и релевантный факт профиля."
        limitations = [
            "Внутренняя потребность компании не подтверждена; это гипотеза для первого разговора."
        ]
        if contact and contact_view:
            contact_rationale = (
                f"Выбран канал «{contact_view.role_label.lower()}»: "
                f"{contact_role or 'публичный канал компании'}. {contact_view.guidance}"
            )
        else:
            contact_rationale = "Подтверждённый адресный контакт пока не найден."
            limitations.append("Перед обращением нужен адресный публичный контакт или канал.")
    else:
        intersection = (
            f"The company publicly states: {company_context}. Your verified experience: "
            f"{candidate_evidence}. This supports a practical hypothesis: {value_hypothesis}."
        )
        collaboration_format = (
            "A short exploratory conversation about one concrete task; a working format is "
            "only determined after that conversation."
        )
        outreach_angle = (
            "I would welcome a short conversation about whether this experience could help "
            "with analysing or automating one concrete workflow."
        )
        outreach_guidance = (
            "Connect the verified company fact to the candidate evidence without claiming an "
            "unconfirmed internal need."
        )
        confidence = "A public company signal and relevant profile evidence are confirmed."
        limitations = [
            "An internal company need is not confirmed; this is a hypothesis for a "
            "first conversation."
        ]
        if contact and contact_view:
            contact_rationale = (
                f"Selected {contact_view.role_label.lower()}: "
                f"{contact_role or 'public company route'}. {contact_view.guidance}"
            )
        else:
            contact_rationale = "No verified targeted contact has been found yet."
            limitations.append("A targeted public contact or channel is required before outreach.")
    return {
        **match,
        "company_context": company_context,
        "outreach_company_fact": outreach_company_fact,
        "relevant_candidate_evidence": candidate_evidence,
        "intersection": intersection,
        "value_hypothesis": value_hypothesis,
        "collaboration_format": collaboration_format,
        "outreach_angle": outreach_angle,
        "outreach_guidance": outreach_guidance,
        "contact_rationale": contact_rationale,
        "confidence": confidence,
        "limitations": limitations,
    }


def draft_primary_match_for_contact(
    payload: dict[str, Any] | None, contact: Contact | None, locale: str
) -> dict[str, Any]:
    """Apply only recipient-specific route evidence to the immutable draft thesis."""

    primary = dict((payload or {}).get("draft_primary_match") or {})
    if not primary:
        return {}
    if contact is None:
        return primary
    contact_view = present_contact(contact, locale)
    primary["contact_rationale"] = contact_view.guidance
    primary["contact_category"] = contact_view.category
    return primary


class OpenAICompanySynthesisProvider:
    """Summarize public evidence only; never receives Candidate Profile data."""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self.client = client

    @property
    def available(self) -> bool:
        return bool(
            (
                self.settings.ai_rewrite_provider == "openai"
                or self.settings.openai_company_discovery_enabled
            )
            and self.settings.openai_api_key is not None
        )

    async def synthesize(self, public_evidence: dict[str, Any], locale: str) -> dict[str, Any]:
        if not self.available or self.settings.openai_api_key is None:
            raise RuntimeError("provider_unavailable")
        schema = {
            "type": "object",
            "properties": {
                "one_line": {"type": "string"},
                "overview": {"type": "string"},
                "current_activity": {"type": "array", "items": {"type": "string"}},
                "scale_summary": {"type": "string"},
                "leadership_summary": {"type": "string"},
                "markets_summary": {"type": "string"},
                "country_summary": {"type": "string"},
                "industry_summary": {"type": "string"},
                "localized_facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "value": {"type": "string"}},
                        "required": ["id", "value"],
                        "additionalProperties": False,
                    },
                },
                "vacancies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "requirements": {"type": "string"},
                        },
                        "required": ["id", "title", "summary", "requirements"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "one_line",
                "overview",
                "current_activity",
                "scale_summary",
                "leadership_summary",
                "markets_summary",
                "country_summary",
                "industry_summary",
                "localized_facts",
                "vacancies",
            ],
            "additionalProperties": False,
        }
        payload = {
            "model": self.settings.openai_rewrite_model,
            "store": False,
            "instructions": (
                "Create a concise evidence-grounded company brief in "
                f"{'Russian' if locale == 'ru' else 'English'}. "
                "Use only the supplied public evidence. Do not infer numbers, geography, clients, "
                "founders, funding, vacancies or current events. An empty string/list is required "
                "when evidence is insufficient. Do not discuss the candidate or owner. "
                "Translate all prose, including vacancy titles and requirements, into "
                "the requested "
                "language; preserve proper names. Vacancy IDs must come from supplied vacancies. "
                "Requirements must only describe explicit obligations, never assumed constraints."
                " Translate verified facts faithfully into localized_facts, retaining their IDs."
            ),
            "input": json.dumps(public_evidence, ensure_ascii=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "company_decision_public_summary",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(COMPANY_SYNTHESIS_TIMEOUT_SECONDS, connect=10.0)
        )
        try:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key.get_secret_value()}"
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            output = "".join(
                content.get("text", "")
                for item in body.get("output", [])
                for content in item.get("content", [])
                if content.get("type") == "output_text"
            )
            parsed = json.loads(output)
            if not isinstance(parsed, dict):
                raise TypeError("synthesis must be an object")
            return parsed
        finally:
            if owns_client:
                await client.aclose()


async def refresh_decision_synthesis(
    session: AsyncSession,
    company: Company,
    *,
    locale: str,
    provider: OpenAICompanySynthesisProvider | None = None,
    allow_ai: bool = True,
) -> CompanyDecisionSynthesis:
    existing = await session.scalar(
        select(CompanyDecisionSynthesis).where(
            CompanyDecisionSynthesis.company_id == company.id,
            CompanyDecisionSynthesis.locale == locale,
        )
    )
    sources = list(
        await session.scalars(
            select(CompanySource)
            .where(
                CompanySource.company_id == company.id,
                CompanySource.http_status >= 200,
                CompanySource.http_status < 300,
                CompanySource.error.is_(None),
            )
            .order_by(CompanySource.fetched_at.desc().nullslast())
        )
    )
    source_ids = {item.id for item in sources}
    facts = list(
        await session.scalars(
            select(CompanyFact).where(
                CompanyFact.company_id == company.id,
                CompanyFact.source_id.in_(source_ids),
                CompanyFact.status == "verified",
            )
        )
    )
    signals = list(
        await session.scalars(
            select(OpportunitySignal)
            .where(
                OpportunitySignal.company_id == company.id, OpportunitySignal.status == "verified"
            )
            .order_by(OpportunitySignal.detected_at.desc())
        )
    )
    opportunities = list(
        await session.scalars(
            select(CompanyOpportunity)
            .where(CompanyOpportunity.company_id == company.id)
            .order_by(CompanyOpportunity.confidence.desc())
        )
    )
    recommendation = await session.scalar(
        select(PositioningRecommendation)
        .where(PositioningRecommendation.company_id == company.id)
        .order_by(PositioningRecommendation.created_at.desc())
    )
    assessment = await session.scalar(
        select(OpportunityAssessment)
        .where(OpportunityAssessment.company_id == company.id)
        .order_by(OpportunityAssessment.created_at.desc())
    )
    contacts = list(
        await session.scalars(
            select(Contact)
            .where(Contact.company_id == company.id, Contact.do_not_contact.is_(False))
            .options(selectinload(Contact.channels))
            .order_by(Contact.discovery_score.desc().nullslast())
        )
    )
    verified_contacts = [
        item
        for item in contacts
        if item.validation_status == "VERIFIED_CONTACT" and has_usable_verified_route(item)
    ]

    jobs = list(
        await session.scalars(
            select(JobOpening).where(
                JobOpening.company_id == company.id,
                JobOpening.active.is_(True),
                JobOpening.source_id.in_(source_ids),
            )
        )
    )
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    records = await profile_records(session, profile.id if profile else None)
    matches = build_match_theses(
        records,
        facts,
        opportunities,
        signals,
        contacts,
        locale,
    )
    # A deterministic locale/schema refresh must not discard a previously
    # localized, source-backed thesis merely because the raw public source is
    # currently in another language.  Provider-backed research may translate
    # it later; until then preserve the existing owner-visible evidence.
    if not matches and not allow_ai and existing and (existing.payload or {}).get("matches"):
        matches = list(existing.payload["matches"])

    public_evidence = {
        "vacancies": [
            {
                "id": str(j.id),
                "title": j.title,
                "description": _clean(j.description, 2000),
                "location": j.location,
                "required_skills": j.required_skills,
            }
            for j in jobs[:10]
        ],
        "company": {
            "name": company.name,
            "website": f"https://{company.normalized_domain}",
            "verified_country": (
                company.country if company.geography_verification_status == "verified" else ""
            ),
            "industry": company.industry or "",
            "company_size": company.company_size or "",
        },
        "sources": [
            {
                "url": item.url,
                "text": _clean(item.extracted_text, MAX_SOURCE_CHARS),
            }
            for item in sources[:6]
        ],
        "verified_facts": [
            {"id": str(item.id), "type": item.fact_type, "value": _clean(item.value, 1200)}
            for item in facts[:20]
        ],
        "verified_signals": [
            {"title": item.title, "evidence": _clean(item.exact_fragment, 700)}
            for item in signals[:8]
        ],
    }
    ai_payload: dict[str, Any] = {}
    provider_name = "deterministic"
    error_message: str | None = None
    if allow_ai:
        selected_provider = provider or OpenAICompanySynthesisProvider()
        try:
            ai_payload = await selected_provider.synthesize(public_evidence, locale)
            provider_name = "openai-public-evidence"
        except Exception as exc:  # noqa: BLE001 - deterministic UX must remain available
            error_message = type(exc).__name__

    source_description = next(
        (_clean(item.value, 900) for item in facts if item.fact_type == "company_activity"),
        _clean(company.description, 900),
    )
    one_line = _clean(ai_payload.get("one_line"), 300) or _first_sentence(source_description)
    if not one_line:
        one_line = (
            "Описание деятельности подтверждается источниками, но краткая формулировка "
            "требует проверки."
            if locale == "ru"
            else "The sources confirm company activity, but the short description needs review."
        )
    current_activity = [
        _clean(value, 450) for value in ai_payload.get("current_activity", []) if _clean(value)
    ]
    if not current_activity:
        current_activity = [
            _clean(item.exact_fragment or item.description, 450) for item in signals[:3]
        ]

    opportunity = opportunities[0] if opportunities else None
    why_selected = _clean(opportunity.rationale, 700) if opportunity else ""
    if locale == "ru" and why_selected:
        why_selected = (
            "Компания прошла проверку обязательных ограничений и имеет подтверждённую "
            "деятельность, "
            "для которой возможен осторожный анализ профессионального соответствия."
        )
    elif not why_selected:
        why_selected = (
            "Компания прошла проверку запроса; конкретная возможность остаётся гипотезой."
            if locale == "ru"
            else (
                "The company passed query qualification; the specific opportunity remains "
                "a hypothesis."
            )
        )

    contact = verified_contacts[0] if verified_contacts else None
    contact_summary = (
        {
            "status": "verified",
            "name": contact.name,
            "role": contact.role or "",
            "channel": contact.email or contact.linkedin or contact.other_public_link or "",
        }
        if contact
        else {"status": "search_in_progress", "summary": _missing(locale, "contact")}
    )
    risks = list(assessment.risks if assessment else [])
    if company.geography_verification_status != "verified":
        risks.insert(
            0,
            "География не подтверждена достаточным источником."
            if locale == "ru"
            else "Geography is not confirmed by sufficient evidence.",
        )
    if not risks:
        risks = [
            "Конкретная внутренняя потребность компании публично не подтверждена."
            if locale == "ru"
            else "A specific internal company need is not publicly confirmed."
        ]

    decision = _recommendation(company, bool(contact))
    payload = {
        "one_line": one_line,
        "overview": _clean(ai_payload.get("overview"), 1400) or source_description,
        "country": company.country if company.geography_verification_status == "verified" else "",
        "geography_status": company.geography_verification_status,
        "scale": _clean(ai_payload.get("scale_summary"), 500)
        or company.company_size
        or _missing(locale, "scale"),
        "leadership": _clean(ai_payload.get("leadership_summary"), 600)
        or _missing(locale, "founders"),
        "markets": _clean(ai_payload.get("markets_summary"), 600),
        "why_selected": why_selected,
        "current_activity": current_activity,
        "current_activity_summary": current_activity[0]
        if current_activity
        else _missing(locale, "current"),
        "fit": _fit_text(recommendation.primary_strategy if recommendation else None, locale),
        "opportunity": (
            _clean(opportunity.rationale, 800)
            if opportunity
            else (
                "Конкретная возможность ещё не сформирована."
                if locale == "ru"
                else "A specific opportunity has not yet been formed."
            )
        ),
        "reason_to_write": (
            _clean(recommendation.concrete_first_message_offer, 700)
            if recommendation
            else (
                "Сначала требуется дополнительное исследование."
                if locale == "ru"
                else "Deeper research is required first."
            )
        ),
        "contact": contact_summary,
        "upside": (
            _clean(recommendation.value_proposition, 700) if recommendation else why_selected
        ),
        "risk": _clean(risks[0], 700),
        "risks": [_clean(item, 700) for item in risks[:5]],
        "recommendation": decision,
        "score": round(float(company.overall_opportunity_score or 0)),
        "research_status": "complete" if sources and facts else "in_progress",
        "research_date": (company.last_researched_at or datetime.now(UTC)).isoformat(),
        "source_count": len(sources),
    }

    # Only localized, evidenced prose enters the decision screen. Source text
    # remains available by URL; a failed translation never masquerades as ready.
    names = [company.name, *(item.name for item in verified_contacts)]

    def localized(value: str | None) -> str:
        value = _clean(value, 1400)
        return value if language_matches(value, locale, names) else ""

    localized_base_risks = [localized(item) for item in risks]
    payload.update(
        {
            "quality_version": QUALITY_VERSION,
            "one_line": localized(ai_payload.get("one_line") or source_description),
            "overview": localized(ai_payload.get("overview") or source_description),
            "country": localized(ai_payload.get("country_summary") or company.country)
            if company.geography_verification_status == "verified"
            else "",
            "industry": localized(ai_payload.get("industry_summary") or company.industry),
            "matches": matches,
            "why_selected": " ".join(m["explanation"] for m in matches),
            "fit": " ".join(m["explanation"] for m in matches),
            "opportunity": " ".join(m["scenario"] for m in matches),
            "current_activity": [v for v in current_activity if localized(v)],
            "vacancies": [],
            # Keep an evidence-aware limitation even when no vacancy matched.
            # An empty list would be rendered as “no material risks”, which is
            # stronger than the available public evidence supports.
            "risks": [item for item in localized_base_risks if item],
        }
    )
    translated_facts = {
        item.get("id"): localized(item.get("value"))
        for item in ai_payload.get("localized_facts", [])
        if isinstance(item, dict)
    }

    def localize_matches(items):
        result = []
        for match in items:
            translated = translated_facts.get(match["company_fact_id"])
            evidence = company_evidence_excerpt(translated or "") or company_evidence_excerpt(
                localized(match["company_evidence"])
            )
            if not evidence:
                continue
            match["company_evidence"] = evidence
            label = match["label"]
            candidate_evidence = _clean(match.get("candidate_evidence"), 420)
            # Candidate profile data stays local. When its saved language does
            # not match the workspace locale, retain the already localized
            # capability label instead of leaking mixed-language prose.
            match["candidate_evidence"] = (
                candidate_evidence
                if language_matches(candidate_evidence, locale)
                else label
            )
            match["explanation"] = (
                f"{evidence} Ваш подтверждённый опыт: {label}."
                if locale == "ru"
                else f"{evidence} Your verified experience: {label}."
            )
            result.append(match)
        return result

    matches = localize_matches(matches)
    payload["matches"] = matches
    payload["why_selected"] = " ".join(m["explanation"] for m in matches)
    payload["fit"] = payload["why_selected"]
    payload["opportunity"] = " ".join(m["scenario"] for m in matches)
    payload["current_activity_summary"] = next(iter(payload["current_activity"]), "")
    jobs_by_id = {str(j.id): j for j in jobs}
    localized_jobs = ai_payload.get("vacancies", [])
    if not localized_jobs:
        localized_jobs = [
            {"id": str(j.id), "title": j.title, "summary": j.description or "", "requirements": ""}
            for j in jobs
        ]
    reviewed_job_ids = set()
    for entry in localized_jobs:
        job = jobs_by_id.get(entry.get("id"))
        if job is None or not localized(entry.get("title")):
            continue
        if job.description and not localized(entry.get("summary")):
            continue
        if job.required_skills and not localized(entry.get("requirements")):
            continue
        if str(job.id) in reviewed_job_ids:
            continue
        reviewed_job_ids.add(str(job.id))
        # Relevance requires at least one evidenced capability in the actual job.
        job_text = " ".join(
            [job.title, job.description or "", *(job.required_skills or [])]
        ).casefold()
        matching_keys = {m["key"] for m in matches}
        if not any(
            key in matching_keys and any(marker in job_text for marker in markers)
            for key, _, _, markers, _ in CAPABILITIES
        ):
            continue
        requirements = localized(entry.get("requirements"))
        payload["vacancies"].append(
            {
                "title": localized(entry.get("title")),
                "summary": localized(entry.get("summary")),
                "url": job.url,
                "requirements": requirements,
            }
        )
        payload["risks"].extend(job_risks(job, profile, records, locale))
    payload["vacancy_reviewed"] = bool(sources and facts) and (
        set(jobs_by_id).issubset(reviewed_job_ids)
    )
    # Vacancy review and risk review are related but not interchangeable.
    # A company with no open vacancy can still have a completed research pass
    # and an explicit uncertainty recorded above.
    payload["risk_reviewed"] = bool(sources and facts and payload["risks"])
    # Country is deliberately absent from the owner brief for a worldwide
    # search: it is context, not a required geographic constraint.  Requiring
    # it here would incorrectly withhold an otherwise localized brief.
    country_ready = (
        company.geography_verification_status == "not_required" or bool(payload["country"])
    )
    payload["locale_validated"] = bool(
        payload["one_line"] and payload["overview"] and country_ready
    )
    payload["draft_matches"] = localize_matches(
        build_match_theses(
            records,
            facts,
            opportunities,
            signals,
            contacts,
            locale,
            permission="use_in_draft",
        )
    )
    if not payload["draft_matches"] and not allow_ai and existing:
        payload["draft_matches"] = list((existing.payload or {}).get("draft_matches") or [])
    for match in payload["matches"] + payload["draft_matches"]:
        match["source_url"] = next((s.url for s in sources if str(s.id) == match["source_id"]), "")
        # Keep the precise match evidence separate from the general company
        # summary. The former is the outreach anchor.
        match["company_summary"] = payload["one_line"]

    # The same selected thesis drives the owner brief and every generated
    # draft. A draft is blocked when its permitted evidence cannot support the
    # selected owner-facing angle; it must never silently switch to another one.
    primary_match = _primary_match(matches[0] if matches else None, contact, locale)
    draft_base_match = next(
        (
            item
            for item in payload["draft_matches"]
            if primary_match and item.get("key") == primary_match.get("key")
        ),
        None,
    )
    payload["primary_match"] = primary_match
    payload["draft_primary_match"] = _primary_match(draft_base_match, contact, locale)

    synthesis = existing
    if synthesis is None:
        synthesis = CompanyDecisionSynthesis(
            company_id=company.id,
            locale=locale,
            recommendation=decision,
            payload=payload,
            source_ids=[str(item.id) for item in sources],
            provider=provider_name,
            error_message=error_message,
            generated_at=datetime.now(UTC),
        )
        session.add(synthesis)
    else:
        synthesis.status = "ready"
        synthesis.recommendation = decision
        synthesis.payload = payload
        synthesis.source_ids = [str(item.id) for item in sources]
        synthesis.provider = provider_name
        synthesis.error_message = error_message
        synthesis.generated_at = datetime.now(UTC)
        synthesis.version += 1
    await session.commit()
    await session.refresh(synthesis)
    return synthesis


async def get_or_build_decision_synthesis(
    session: AsyncSession, company: Company, *, locale: str
) -> CompanyDecisionSynthesis:
    existing = await session.scalar(
        select(CompanyDecisionSynthesis).where(
            CompanyDecisionSynthesis.company_id == company.id,
            CompanyDecisionSynthesis.locale == locale,
        )
    )
    if existing is not None:
        # Do not silently downgrade an already prepared localized brief during
        # a page GET. A deterministic schema upgrade is safe, however: it
        # preserves the same local evidence and adds no provider request.
        if (existing.payload or {}).get("quality_version") == QUALITY_VERSION:
            return existing
        return await refresh_decision_synthesis(session, company, locale=locale, allow_ai=False)
    # A page view must never block on an external AI call. The executor and
    # deeper-research workflow create the AI-backed synthesis in advance; this
    # path is only a deterministic compatibility fallback for legacy records.
    return await refresh_decision_synthesis(session, company, locale=locale, allow_ai=False)
