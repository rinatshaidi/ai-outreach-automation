"""Structured local adapter and deterministic generation guardrails."""

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol

from app.modules.candidate_profile.models import CandidateContact, CandidateFact, CandidateRule
from app.modules.crm.models import Company, Contact
from app.modules.generation.models import ApprovedWritingExample, SenderVoiceProfile
from app.modules.generation.schemas import (
    AdapterDraft,
    DraftFormat,
    DraftTone,
    DraftVariant,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunitySignal,
    PositioningRecommendation,
)
from app.modules.research.models import CompanyFact

PROVIDER = "deterministic-local"
MODEL = "personalized-voice-v2"


@dataclass(frozen=True)
class LanguageChoice:
    code: str
    confidence: float
    reason: str
    needs_review: bool = False


@dataclass(frozen=True)
class GenerationContext:
    company: Company
    contact: Contact
    recommendation: PositioningRecommendation
    opportunities: list[CompanyOpportunity]
    signals: list[OpportunitySignal]
    company_facts: list[CompanyFact]
    candidate_facts: list[CandidateFact]
    signature_contacts: list[CandidateContact]
    rules: list[CandidateRule]
    language: LanguageChoice
    campaign_goal: str
    prompt_version: str
    min_words: int
    max_words: int
    sender_name: str = ""
    decision_brief: dict = field(default_factory=dict)
    sender_voice_profile: SenderVoiceProfile | None = None
    approved_examples: list[ApprovedWritingExample] = field(default_factory=list)


class GenerationAdapter(Protocol):
    async def generate(self, context: GenerationContext) -> list[AdapterDraft]: ...


def choose_language(company: Company, manual: str, source_languages: list[str]) -> LanguageChoice:
    if manual != "auto":
        return LanguageChoice(manual, 1.0, "Explicit owner selection")
    signals = [item.casefold() for item in company.language_signals + source_languages if item]
    ru = sum(item.startswith("ru") or "russian" in item for item in signals)
    en = sum(item.startswith("en") or "english" in item for item in signals)
    if ru > en:
        return LanguageChoice("ru", 0.8, "Company/source language signals prefer Russian")
    if en > ru:
        return LanguageChoice("en", 0.8, "Company/source language signals prefer English")
    return LanguageChoice(
        "en", 0.4, "Language signals are ambiguous; English fallback requires review", True
    )


def _short(text: str, limit: int = 150) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else f"{clean[: limit - 1].rstrip()}…"


CANDIDATE_FACT_EN = {
    "Более 10 лет опыта управления проектами, развития бизнеса и запуска новых направлений.": (
        "more than 10 years of project management, business development, and new initiative "
        "launch experience"
    ),
    (
        "Опыт формирования и управления командами, распределения ответственности "
        "и построения рабочих процессов."
    ): ("experience building teams, assigning responsibilities, and structuring workflows"),
    (
        "Опыт управления подрядчиками, поставщиками, сроками, бюджетами, рисками "
        "и реализацией проектов до запуска."
    ): (
        "experience managing contractors, suppliers, schedules, budgets, risks, and delivery "
        "through launch"
    ),
    "Опыт развития бизнеса, территорий, новых объектов и направлений.": (
        "business development experience across territories, facilities, and new initiatives"
    ),
    "Практический опыт создания собственных AI- и Python-automation решений.": (
        "practical experience building independent AI and Python automation solutions"
    ),
}


def _company_evidence(facts: list[CompanyFact]) -> str:
    evidence_phrases = (
        (
            "Global Operations supports markets across more than 50 countries",
            "its Global Operations team supports markets in more than 50 countries through "
            "programmes, partnerships, tools, and standards",
        ),
        (
            "outcome-oriented builder culture focused on practical AI and automation",
            "it promotes an outcome-oriented builder culture focused on practical AI and "
            "automation",
        ),
        (
            "distributed team spanning 60+ countries",
            "its distributed team spans 60+ countries and six continents",
        ),
        (
            "100+ open roles",
            "its official careers page lists more than 100 open roles",
        ),
        (
            "fastest-growing financial institution",
            "its official About page describes a fast-growing digital bank in Mexico",
        ),
        (
            "authorization to operate as a bank",
            "its official site reports authorization to operate as a bank in Mexico",
        ),
        (
            "more than 3 million",
            "its official site reports more than 3 million active credit-card customers",
        ),
    )
    for marker, phrase in evidence_phrases:
        for fact in facts:
            if marker.casefold() in fact.value.casefold():
                return phrase
    return _short(facts[0].value, 190) if facts else "the company’s public activity"


def _has_fact(facts: list[CompanyFact], marker: str) -> bool:
    return any(marker.casefold() in fact.value.casefold() for fact in facts)


def _company_reaction(context: GenerationContext) -> tuple[str, str]:
    """Return a natural reaction and its reason, grounded only in available company facts."""
    facts = context.company_facts
    name = context.company.name
    language = context.language.code
    if "plata" in name.casefold() and (
        _has_fact(facts, "fastest-growing financial institution")
        or _has_fact(facts, "more than 3 million")
        or _has_fact(facts, "100+ open roles")
    ):
        if language == "ru":
            return (
                "Меня заинтересовало, как быстро Plata развивается в Мексике: от кредитного "
                "продукта к более широкому цифровому банку и большой растущей команде.",
                "rapid_growth",
            )
        return (
            "I was interested to see how quickly Plata is developing in Mexico, moving from a "
            "credit product toward a broader digital bank while continuing to grow its team.",
            "rapid_growth",
        )
    if _has_fact(facts, "outcome-oriented builder culture focused on practical AI"):
        if language == "ru":
            return (
                f"В {name} меня особенно заинтересовала культура людей, которые создают "
                "практические продукты вокруг AI и автоматизации.",
                "ai_builder_culture",
            )
        return (
            f"What stood out to me about {name} is its builder culture and the practical way "
            "the team approaches AI and automation.",
            "ai_builder_culture",
        )
    if _has_fact(facts, "Global Operations supports markets across more than 50 countries"):
        if language == "ru":
            return (
                f"В {name} мне близок масштаб международных операций и работа с рынками, "
                "партнёрствами и едиными рабочими стандартами.",
                "international_operations",
            )
        return (
            f"I was drawn to the scale of {name}'s international operations and the way its "
            "teams support markets through partnerships, tools, and shared standards.",
            "international_operations",
        )
    if _has_fact(facts, "distributed team spanning 60+ countries"):
        if language == "ru":
            return (
                f"Меня привлекло то, как {name} строит международный продукт распределённой "
                "командой в десятках стран.",
                "international_team",
            )
        return (
            f"I was interested in how {name} is building an international product with a "
            "distributed team spanning dozens of countries.",
            "international_team",
        )
    evidence = _company_evidence(facts)
    if language == "ru":
        return (f"Я изучил {name}, и моё внимание привлекло следующее: {evidence}.", "company_fact")
    return (
        f"I looked into {name}, and one detail that caught my attention was that {evidence}.",
        "company_fact",
    )


def _example_style(context: GenerationContext) -> dict[str, bool]:
    """Extract abstract style signals from approved examples without copying their wording."""
    examples = [
        item
        for item in context.approved_examples
        if item.approved and item.language == context.language.code
    ]
    texts = [item.text.strip() for item in examples]
    return {
        "uses_questions": any("?" in text for text in texts),
        "uses_exclamation": any("!" in text for text in texts),
        "has_reference": bool(texts),
    }


def _opening(context: GenerationContext, tone: DraftTone) -> str:
    profile = context.sender_voice_profile
    configured = (
        profile.preferred_openings.get(context.language.code, []) if profile is not None else []
    )
    if context.language.code == "ru":
        base = configured[0] if configured else "Добрый день"
        return f"{base}, {context.contact.name}."
    recipient = _recipient_label(context.company, context.contact, context.language.code)
    if tone == DraftTone.PROFESSIONAL:
        preferred = next((item for item in configured if item.casefold() == "dear"), "Dear")
        return f"{preferred} {recipient},"
    preferred = next((item for item in configured if item.casefold() == "hello"), "Hello")
    return f"{preferred} {recipient},"


def _professional_match(context: GenerationContext) -> tuple[str, str | None]:
    candidate = _candidate_evidence(context.candidate_facts, context.language.code)
    automation = _candidate_automation_evidence(context.candidate_facts, context.language.code)
    return candidate, automation


def _candidate_evidence(facts: list[CandidateFact], language: str) -> str:
    if not facts:
        return "relevant operational and automation experience"
    ordered = sorted(facts, key=lambda item: item.fact_type != "experience")
    value = ordered[0].text
    if language == "en":
        return CANDIDATE_FACT_EN.get(
            value,
            "verified project, business development, and practical automation experience",
        )
    return _short(value)


def _candidate_automation_evidence(facts: list[CandidateFact], language: str) -> str | None:
    automation = next(
        (
            item
            for item in facts
            if item.fact_type in {"technology", "ai"}
            or "automation" in item.text.casefold()
            or "автоматиза" in item.text.casefold()
        ),
        None,
    )
    if automation is None:
        return None
    if language == "en":
        return CANDIDATE_FACT_EN.get(
            automation.text,
            "practical experience building independent AI and Python automation solutions",
        )
    return _short(automation.text)


def _recipient_label(company: Company, contact: Contact, language: str) -> str:
    label = contact.name.strip()
    if language == "en" and label.casefold().startswith(company.name.casefold()):
        label = label[len(company.name) :].strip(" -/·")
    if not label:
        label = contact.role or "team"
    if language == "en" and "team" not in label.casefold() and not contact.email:
        label = f"{label} team"
    return label


def _format_name(value: str, language: str) -> str:
    if language == "en":
        return value.replace("_", "-")
    return {
        "project_based": "проектной работы",
        "full_time": "полной занятости",
        "part_time": "частичной занятости",
        "consulting": "консалтинга",
        "contract": "контрактной работы",
    }.get(value, value.replace("_", " "))


_PRIMARY_MATCH_FINGERPRINT_FIELDS = (
    "key",
    "track",
    "opportunity_id",
    "signal_id",
    "candidate_ids",
    "company_fact_id",
    "source_id",
    "company_context",
    "outreach_company_fact",
    "relevant_candidate_evidence",
    "intersection",
    "value_hypothesis",
    "collaboration_format",
    "outreach_angle",
    "contact_category",
    "contact_rationale",
    "confidence",
    "limitations",
)


def primary_match_fingerprint(primary_match: dict[str, object] | None) -> str:
    """Stable analysis identity carried by every generated draft run.

    A draft is current only when the owner-visible evidence and collaboration
    thesis that produced it still match the current one.  Text itself is not
    included: manual edits remain immutable historical revisions.
    """

    if not primary_match:
        return ""
    payload = {
        key: primary_match.get(key)
        for key in _PRIMARY_MATCH_FINGERPRINT_FIELDS
        if primary_match.get(key) not in (None, "", [], {})
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


class LocalStructuredGenerationAdapter:
    """Four owner-facing messages from the same approved evidence, rendered locally."""

    async def generate(self, context: GenerationContext) -> list[AdapterDraft]:
        from app.modules.opportunities.quality import language_matches

        locale = context.language.code
        ru = locale == "ru"
        primary_match = context.decision_brief.get("draft_primary_match") or {}
        required = (
            "outreach_company_fact",
            "relevant_candidate_evidence",
            "value_hypothesis",
            "outreach_angle",
        )
        if not all(primary_match.get(key) for key in required):
            raise ValueError("draft_primary_match_missing")
        company_text = _short(str(primary_match["outreach_company_fact"]), 240)
        if not company_text.endswith((".", "!", "?")) or company_text.endswith("…"):
            raise ValueError("draft_primary_match_missing")
        candidate_evidence = _short(str(primary_match["relevant_candidate_evidence"]), 260)
        value_hypothesis = _short(str(primary_match["value_hypothesis"]), 260)
        outreach_angle = _short(str(primary_match["outreach_angle"]), 280)
        localized_company = language_matches(company_text, locale, [context.company.name])
        localized_candidate = language_matches(candidate_evidence, locale)
        if not localized_company or not localized_candidate:
            raise ValueError("draft_localized_research_missing")
        sender = context.sender_name.strip()
        signature = (
            ("\n\nС уважением,\n" if ru else "\n\nBest regards,\n") + sender if sender else ""
        )
        for contact in context.signature_contacts:
            if contact.verified and contact.store_private and contact.use_in_signature:
                signature += "\n" + contact.value
        name = context.company.name
        hello = _opening(context, DraftTone.PROFESSIONAL)
        warm = _opening(context, DraftTone.FRIENDLY)
        if not language_matches(hello, locale, [context.contact.name]):
            hello = "Здравствуйте." if ru else "Hello,"
        if not language_matches(warm, locale, [context.contact.name]):
            warm = hello
        if ru:
            context_line = f"Меня заинтересовала {name}: {company_text.rstrip('.')}."
            fit = f"Мой подтверждённый релевантный опыт: {candidate_evidence}."
            question = "Есть ли у вашей команды задача, для которой такой опыт мог бы быть полезен?"
            short = (
                f"{warm}\n\n{_short(context_line, 180)} {fit} Возможный вклад: "
                f"{value_hypothesis}. Буду рад коротко обсудить, есть ли у команды "
                "подходящая задача."
            )
            business = (
                f"{hello}\n\n{context_line}\n\n{fit} {outreach_angle} {question} "
                "Это исследовательское обращение, а не отклик на подтверждённую вакансию. "
                "Если вы не занимаетесь такими вопросами, "
                f"буду признателен за рекомендацию подходящего коллеги."
            )
            long = (
                f"{hello}\n\n{context_line}\n\n{fit} Возможный практический вклад — "
                f"{value_hypothesis}. {outreach_angle}\n\n"
                "Понимаю, что публичные материалы не подтверждают внутреннюю потребность "
                "и не раскрывают приоритеты команды. Поэтому предлагаю короткий разговор "
                "об одной конкретной задаче, а не предположение о готовой роли. "
                "Готов подстроить разговор под удобный для команды контекст и формат. "
                f"{question}\n\nЕсли вопрос находится "
                f"в зоне ответственности другого коллеги, буду признателен за подсказку, "
                f"к кому лучше обратиться."
            )
            friendly = (
                f"{warm}\n\n{context_line}\n\n{fit} Мне кажется, здесь может быть "
                f"полезное пересечение: {value_hypothesis}. {outreach_angle}\n\n"
                "Не хочу делать выводы о внутренних приоритетах только по сайту, поэтому "
                "буду рад коротко познакомиться и понять, есть ли сейчас тема для разговора. "
                "Если нет — это тоже полезно знать; это поможет не тратить время команды.\n\n"
                "Буду рад вашему "
                f"ответу. Если с этим вопросом лучше обратиться к другому человеку, "
                f"подскажите, пожалуйста, к кому."
            )
            subject = f"Возможное сотрудничество с {name}"
        else:
            context_line = f"I was interested in {name}: {company_text.rstrip('.')}."
            fit = f"My verified relevant experience: {candidate_evidence}."
            question = "Does your team have a task where this experience could be useful?"
            short = (
                f"{warm}\n\n{_short(context_line, 180)} {fit} A possible contribution is "
                f"{value_hypothesis}. I would be glad to discuss whether there is a relevant task."
            )
            business = (
                f"{hello}\n\n{context_line}\n\n{fit} {outreach_angle} {question} "
                "This is exploratory outreach, not an application to a confirmed vacancy. "
                "If another colleague handles "
                f"this, I would appreciate an introduction or a pointer to the right "
                f"person."
            )
            long = (
                f"{hello}\n\n{context_line}\n\n{fit} A practical contribution could be "
                f"{value_hypothesis}. {outreach_angle}\n\n"
                "I understand that public information does not confirm an internal need or "
                "describe current priorities. Rather than assume a ready-made role, I would "
                "welcome a short conversation about one concrete task and adapt it to the "
                f"right team context. {question} "
                f"If another colleague is responsible for this area, I would appreciate "
                f"a pointer to the right person."
            )
            friendly = (
                f"{warm}\n\n{context_line}\n\n{fit} There may be a useful connection: "
                f"{value_hypothesis}. {outreach_angle}\n\n"
                "I would rather hear about priorities from the team than infer them from a "
                "website, so I would value a short introductory conversation. If there is no "
                "relevant task, that is useful to know as well and avoids wasting the team's "
                "time or creating unnecessary follow-up.\n\nI would "
                f"be glad to hear your thoughts. If someone else is better placed to "
                f"discuss this, a pointer would be much appreciated."
            )
            subject = f"Possible collaboration with {name}"
        specs = (
            (DraftVariant.A, DraftFormat.EXPANDED, DraftTone.PROFESSIONAL, long),
            (DraftVariant.B, DraftFormat.EXPANDED, DraftTone.FRIENDLY, friendly),
            (DraftVariant.C, DraftFormat.SHORT, DraftTone.PROFESSIONAL, business),
            (DraftVariant.D, DraftFormat.SHORT, DraftTone.FRIENDLY, short),
        )
        return [
            AdapterDraft(
                variant=variant,
                message_format=fmt,
                tone=tone,
                subject=subject,
                body=body + signature,
                language=locale,
                explanation="Evidence-grounded local rendering",
                opportunity_type_ids=[
                    i.id
                    for i in context.opportunities
                    if str(i.id) == str(primary_match.get("opportunity_id", ""))
                ],
                opportunity_signal_ids=[
                    i.id
                    for i in context.signals
                    if str(i.id) == str(primary_match.get("signal_id", ""))
                ],
                positioning_strategy=context.recommendation.primary_strategy,
                collaboration_format=context.recommendation.collaboration_format,
                value_proposition=context.recommendation.value_proposition,
                candidate_fact_ids=[
                    i.id
                    for i in context.candidate_facts
                    if str(i.id) in {str(value) for value in primary_match.get("candidate_ids", [])}
                ],
                company_fact_ids=[
                    i.id
                    for i in context.company_facts
                    if str(i.id) == str(primary_match.get("company_fact_id", ""))
                ],
                source_ids=[primary_match["source_id"]] if primary_match.get("source_id") else [],
                warnings=[],
            )
            for variant, fmt, tone, body in specs
        ]


def validate_draft(
    draft: AdapterDraft,
    context: GenerationContext,
    *,
    outreach_allowed: bool,
) -> ValidationReport:
    issues: list[ValidationIssue] = []

    def issue(
        code: str,
        message: str,
        severity: ValidationSeverity = ValidationSeverity.BLOCK,
    ) -> None:
        issues.append(ValidationIssue(code=code, severity=severity, message=message))

    if not outreach_allowed:
        issue("OUTREACH_DECISION_REQUIRED", "Owner outreach decision is not active")
    if context.contact.do_not_contact:
        issue("SUPPRESSED_CONTACT", "Contact is marked do-not-contact")
    if context.contact.verification_status not in {
        "verified",
        "verified_public",
        "provider_verified",
    }:
        issue("CONTACT_NOT_VERIFIED", "Contact must be verified before draft generation")
    if not any(
        (
            context.contact.email,
            context.contact.telegram,
            context.contact.linkedin,
            context.contact.other_public_link,
        )
    ):
        issue("CONTACT_CHANNEL_MISSING", "Contact has no supported public channel")
    if not context.company_facts:
        issue("VERIFIED_COMPANY_FACT_REQUIRED", "At least one verified company fact is required")
    if not context.opportunities:
        issue("VERIFIED_OPPORTUNITY_REQUIRED", "At least one verified opportunity is required")
    if not context.candidate_facts:
        issue("ALLOWED_CANDIDATE_FACT_REQUIRED", "At least one draft-permitted fact is required")

    allowed_candidate = {item.id for item in context.candidate_facts}
    allowed_company = {item.id for item in context.company_facts}
    allowed_opportunities = {item.id for item in context.opportunities}
    allowed_signals = {item.id for item in context.signals}
    if not set(draft.candidate_fact_ids) <= allowed_candidate:
        issue("CANDIDATE_FACT_NOT_ALLOWED", "Draft cites an unavailable candidate fact")
    if not set(draft.company_fact_ids) <= allowed_company:
        issue("COMPANY_FACT_NOT_VERIFIED", "Draft cites an unverified company fact")
    if not set(draft.opportunity_type_ids) <= allowed_opportunities:
        issue("OPPORTUNITY_NOT_VERIFIED", "Draft cites an unverified opportunity")
    if not set(draft.opportunity_signal_ids) <= allowed_signals:
        issue("SIGNAL_NOT_VERIFIED", "Draft cites an unverified signal")
    if draft.positioning_strategy != context.recommendation.primary_strategy:
        issue("STRATEGY_MISMATCH", "Draft strategy differs from owner-selected recommendation")
    if draft.collaboration_format != context.recommendation.collaboration_format:
        issue("COLLABORATION_FORMAT_MISMATCH", "Draft collaboration format was altered")
    if draft.language != context.language.code:
        issue("LANGUAGE_MISMATCH", "Draft language differs from the selected language")
    if context.language.needs_review:
        issue(
            "LANGUAGE_NEEDS_REVIEW",
            context.language.reason,
            ValidationSeverity.WARNING,
        )

    words = len(draft.body.split())
    min_words, max_words = (
        (25, 90)
        if draft.message_format == DraftFormat.SHORT
        else (context.min_words, context.max_words)
    )
    if words < min_words or words > max_words:
        issue(
            "WORD_COUNT_OUT_OF_RANGE",
            f"Draft has {words} words; required range is {min_words}-{max_words}",
        )
    lowered = f"{draft.subject}\n{draft.body}".casefold()
    for marker in ("<img", "tracking pixel", "act now", "guaranteed result"):
        if marker in lowered:
            issue("FORBIDDEN_CONTENT", f"Forbidden content marker: {marker}")
    robotic_markers = (
        "my verified background",
        "public materials report",
        "structured cross-functional work",
        "measurable improvement",
        "i cannot speak about your internal processes",
        "according to verified evidence",
        "my profile demonstrates",
        "this creates an interesting context",
        "campaign goal",
        "positioning strategy",
        "opportunity signal",
    )
    for marker in robotic_markers:
        if marker in lowered:
            issue("ROBOTIC_OR_INTERNAL_LANGUAGE", f"Remove template/internal phrase: {marker}")
    if context.company.name.casefold() not in lowered:
        issue("COMPANY_CONNECTION_MISSING", "Draft must explain why this company is relevant")
    for rule in context.rules:
        if rule.rule_type == "forbidden_word" and rule.text.casefold() in lowered:
            severity = (
                ValidationSeverity.BLOCK if rule.severity == "block" else ValidationSeverity.WARNING
            )
            issue("CANDIDATE_RULE_VIOLATION", rule.text, severity)

    if context.recommendation.primary_strategy == "ai_first" and not any(
        fact.fact_type in {"skill", "technology", "ai"} for fact in context.candidate_facts
    ):
        issue("AI_POSITIONING_UNSUPPORTED", "AI-first requires an allowed verified AI fact")
    allowed_signatures = {item.value for item in context.signature_contacts}
    for line in draft.body.splitlines():
        if "@" in line and not any(value in line for value in allowed_signatures):
            issue("SIGNATURE_CONTACT_NOT_ALLOWED", "Draft contains a non-permitted contact value")
    return ValidationReport(
        passed=not any(item.severity == ValidationSeverity.BLOCK for item in issues),
        issues=issues,
    )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def content_hash(subject: str, body: str) -> str:
    return sha256(f"{subject}\n{body}".encode()).hexdigest()
