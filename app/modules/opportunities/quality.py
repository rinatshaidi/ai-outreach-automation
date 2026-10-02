"""Evidence-linked local fit, without exporting any owner information.

These are capability concepts, not translations of generated prose. A concept
must occur on BOTH sides; a desired role alone never counts as experience.
"""

import re
from typing import Any

from sqlalchemy import select

from app.modules.candidate_profile.models import CandidateExperience, CandidateFact, CandidateSkill

CAPABILITIES = (
    (
        "projects",
        "управление проектами",
        "project management",
        ("project management", "project delivery", "управление проектами", "ведение проектов"),
        "launches",
    ),
    (
        "contractors",
        "работа с подрядчиками",
        "contractor management",
        ("contractor", "подрядчик", "construction", "строительств"),
        "contractor_management",
    ),
    (
        "development",
        "развитие бизнеса и территорий",
        "business and territory development",
        (
            "business development",
            "expansion",
            "market entry",
            "развитие бизнеса",
            "экспанси",
            "выход на рынок",
        ),
        "territory_development",
    ),
    (
        "operations",
        "организация операций",
        "operations coordination",
        (
            "operations",
            "operational",
            "операцион",
            "distributed service network",
        ),
        "operations_management",
    ),
    (
        "negotiations",
        "переговоры и партнёрства",
        "negotiations and partnerships",
        ("partnership", "negotiation", "партнер", "партнёр", "переговор"),
        "negotiations",
    ),
    (
        "automation",
        "автоматизация процессов",
        "workflow automation",
        ("automation", "автоматиза", "n8n", "workflow"),
        None,
    ),
    ("python", "разработка на Python", "Python development", ("python",), None),
    (
        "integration",
        "интеграция систем",
        "system integration",
        ("api integration", "system integration", "интеграция систем", "интеграц"),
        None,
    ),
    (
        "infrastructure",
        "инфраструктурные проекты",
        "infrastructure projects",
        ("infrastructure", "инфраструктур", "commercial real estate", "коммерческая недвижимость"),
        None,
    ),
    (
        "finance",
        "финансы и анализ рынков",
        "finance and market analysis",
        ("trading", "трейдинг", "financial analysis", "финансовый анализ"),
        None,
    ),
)

# These are deliberately few and owner-approved.  A track is not a keyword
# bucket: a company must expose a source-backed opportunity of the relevant
# type and the owner must have verified evidence for the same track.
MATCH_TRACKS = {
    "project_delivery": {
        "ru": "Запуск проектов и операционное управление",
        "en": "Project delivery and operations",
        "opportunity_types": {
            "operations_improvement",
            "project_work",
            "new_product_or_direction",
        },
        "signal_types": {"project_launch", "operational_change", "new_product"},
        "experience_flags": {"contractor_management", "launches", "operations_management"},
        "skill_groups": set(),
        "contribution_ru": (
            "помочь структурировать запуск, координацию подрядчиков или повторяемый "
            "операционный процесс"
        ),
        "contribution_en": (
            "help structure a launch, contractor coordination, or a repeatable operating process"
        ),
    },
    "business_development": {
        "ru": "Развитие бизнеса и расширение",
        "en": "Business development and expansion",
        "opportunity_types": {
            "business_expansion",
            "market_entry",
            "investment_or_growth",
            "local_representation",
        },
        "signal_types": {"market_entry", "partnership", "expansion", "funding"},
        "experience_flags": {"negotiations", "territory_development", "launches"},
        "skill_groups": {"business"},
        "contribution_ru": (
            "предложить поддержку выхода на рынок, партнёрской инициативы или "
            "коммерческого запуска"
        ),
        "contribution_en": (
            "support a market-entry, partnership, or commercial-launch initiative"
        ),
    },
    "practical_automation": {
        "ru": "Практическая AI/Python-автоматизация",
        "en": "Practical AI/Python automation",
        "opportunity_types": {"ai_adoption", "process_automation"},
        "signal_types": {"automation", "digital_transformation", "process_change"},
        "experience_flags": set(),
        "skill_groups": {"ai", "technology"},
        "contribution_ru": (
            "разобрать конкретный рабочий процесс и предложить практичную автоматизацию "
            "без заявлений об ML-экспертизе, которой нет в доказательствах"
        ),
        "contribution_en": (
            "review a concrete workflow and propose practical automation without making "
            "unsupported ML-engineering claims"
        ),
    },
}


def _permitted_records(records: list[Any], permission: str) -> list[Any]:
    return [
        record
        for record in records
        if record.verified and record.store_private and getattr(record, permission, False)
    ]


def _record_supports_track(record: Any, config: dict[str, Any]) -> bool:
    flags = config["experience_flags"]
    if flags and any(bool(getattr(record, flag, False)) for flag in flags):
        return True
    return bool(
        getattr(record, "skill_group", None) in config["skill_groups"]
        and getattr(record, "actual_level", "") in {"practical", "proficient", "advanced"}
    )


def _candidate_evidence(record: Any, label: str) -> str:
    """Return one owner-visible, verified record excerpt for a match.

    The match object remains internal to the owner workspace, but must still
    name the actual approved record rather than a generic capability bucket.
    """

    for attribute in ("text", "evidence", "verified_results"):
        value = " ".join(str(getattr(record, attribute, "") or "").split())
        if value:
            return value[:420]
    position = " ".join(str(getattr(record, "position", "") or "").split())
    if position:
        return f"{position}: {label}"
    skill = " ".join(str(getattr(record, "name", "") or "").split())
    if skill:
        return f"{skill} ({getattr(record, 'actual_level', '') or 'confirmed'})"
    return label


def _contact_path_exists(contacts: list[Any]) -> bool:
    """Contactability changes next action, never professional fit."""

    return any(
        not getattr(contact, "do_not_contact", False)
        and getattr(contact, "validation_status", "") == "VERIFIED_CONTACT"
        and (
            getattr(contact, "email", None)
            or getattr(contact, "linkedin", None)
            or getattr(contact, "other_public_link", None)
        )
        for contact in contacts
    )


def _source_backed_excerpt(
    *, source_ids: set[str], facts: list[Any], signals: list[Any], locale: str
) -> tuple[str, str, str, str] | None:
    """Prefer a dated signal; otherwise use a verified, source-linked fact.

    The text is source evidence, not an AI hypothesis.  Page chrome is removed
    before it can reach the owner-facing explanation.
    """

    # Prefer a fact because the synthesis provider carries an ID for faithful
    # RU/EN translation.  A signal remains a valid fallback when no linked fact
    # exists, for example for a newly detected hiring signal.
    for fact in facts:
        if str(getattr(fact, "source_id", "")) not in source_ids:
            continue
        if getattr(fact, "status", "") != "verified":
            continue
        excerpt = company_evidence_excerpt(getattr(fact, "value", ""))
        if excerpt:
            return excerpt, str(fact.source_id), "", str(fact.id)
    for signal in signals:
        if str(getattr(signal, "id", "")) not in source_ids:
            continue
        if getattr(signal, "status", "") != "verified" or not getattr(signal, "source_id", None):
            continue
        excerpt = company_evidence_excerpt(
            getattr(signal, "exact_fragment", None) or getattr(signal, "description", "")
        )
        if excerpt:
            return excerpt, str(signal.source_id), str(signal.id), ""
    return None


def build_match_theses(
    records: list[Any],
    facts: list[Any],
    opportunities: list[Any],
    signals: list[Any],
    contacts: list[Any],
    locale: str,
    *,
    permission: str = "use_in_scoring",
) -> list[dict[str, Any]]:
    """Build explainable owner-to-company matches from evidence on both sides.

    A bare company description, generic opportunity type, contact or shared
    keyword cannot produce a thesis.  This pure function intentionally keeps
    personal evidence local: only record IDs and a safe track label are emitted.
    """

    permitted = _permitted_records(records, permission)
    contact_ready = _contact_path_exists(contacts)
    results: list[dict[str, Any]] = []
    seen_tracks: set[str] = set()
    for opportunity in opportunities:
        if getattr(opportunity, "status", "") != "verified":
            continue
        opportunity_type = getattr(opportunity, "opportunity_type", "")
        linked_ids = {
            str(item)
            for item in [
                *(getattr(opportunity, "source_ids", None) or []),
                *(getattr(opportunity, "signal_ids", None) or []),
            ]
            if item
        }
        if not linked_ids:
            continue
        for key, config in MATCH_TRACKS.items():
            if key in seen_tracks or opportunity_type not in config["opportunity_types"]:
                continue
            supporting_records = [
                record for record in permitted if _record_supports_track(record, config)
            ]
            candidate_ids = [str(record.id) for record in supporting_records]
            if not supporting_records:
                continue
            evidence = _source_backed_excerpt(
                source_ids=linked_ids, facts=facts, signals=signals, locale=locale
            )
            if evidence is None:
                continue
            evidence_text, source_id, signal_id, company_fact_id = evidence
            label = config["ru"] if locale == "ru" else config["en"]
            contribution = (
                config["contribution_ru"] if locale == "ru" else config["contribution_en"]
            )
            state = "ready_to_contact" if contact_ready else "match_confirmed_contact_pending"
            if locale == "ru":
                explanation = (
                    f"Сигнал компании: {evidence_text} Ваш подтверждённый опыт: {label}. "
                    f"Практичный вклад: {contribution}."
                )
                scenario = (
                    "Есть конкретный повод обратиться по этому направлению."
                    if contact_ready
                    else "Совпадение подтверждено; перед обращением нужно найти адресный контакт."
                )
                risk = (
                    "Контакт подтверждён; всё равно проверьте адресата перед отправкой."
                    if contact_ready
                    else "Подтверждённого адресного контакта пока нет."
                )
            else:
                explanation = (
                    f"Company signal: {evidence_text} Your verified experience: {label}. "
                    f"Practical contribution: {contribution}."
                )
                scenario = (
                    "There is a concrete reason to approach the company on this topic."
                    if contact_ready
                    else "Fit is confirmed; find a targeted contact before outreach."
                )
                risk = (
                    "A contact is verified; still confirm the recipient before sending."
                    if contact_ready
                    else "No verified, targeted contact has been found yet."
                )
            results.append(
                {
                    "key": key,
                    "track": key,
                    "opportunity_id": str(getattr(opportunity, "id", "")),
                    "label": label,
                    "candidate_ids": candidate_ids,
                    "company_fact_id": company_fact_id,
                    "source_id": source_id,
                    "signal_id": signal_id,
                    "company_evidence": evidence_text,
                    "candidate_evidence": _candidate_evidence(supporting_records[0], label),
                    "contribution": contribution,
                    "explanation": explanation,
                    "scenario": scenario,
                    "risk": risk,
                    "state": state,
                }
            )
            seen_tracks.add(key)
    return results


def language_matches(text: str, locale: str, names: list[str] = ()) -> bool:
    """Conservative mixed-script guard; proper names are exempt, not translated."""
    for name in sorted(filter(None, names), key=len, reverse=True):
        text = text.replace(name, "")
    cyrillic = len(re.findall(r"[а-яё]", text, re.I))
    latin = len(re.findall(r"[a-z]", text, re.I))
    if not cyrillic and not latin:
        return bool(text.strip())
    if locale == "en":
        return cyrillic == 0
    return cyrillic > 0 and cyrillic >= latin


def contains_capability(text: str, markers) -> bool:
    """Match token boundaries, avoiding 'api' in 'capital', etc."""
    return any(
        re.search(r"(?<!\w)" + re.escape(m) + (r"(?!\w)" if len(m) <= 3 else ""), text.casefold())
        for m in markers
    )


_WEB_CHROME_MARKERS = (
    "this website uses cookies",
    "cookie policy",
    "privacy policy",
    "accept all",
    "skip to content",
    "пропустить к содержимому",
    "этот веб-сайт использует файлы cookie",
    "политику конфиденциальности",
    "принять все",
)


def company_evidence_excerpt(value: str, *, limit: int = 360) -> str:
    """Return an owner-readable company fact, never page navigation or cookie copy.

    The first visible text of a public page frequently contains navigation and a
    cookie banner.  It is useful as research provenance, but it is not evidence
    that the owner should contact the company.
    """
    text = " ".join((value or "").split())
    lowered = text.casefold()
    cut_points = [lowered.find(marker) for marker in _WEB_CHROME_MARKERS if marker in lowered]
    if cut_points:
        text = text[: min(cut_points)].strip(" -:;,.")
    if not text or any(marker in text.casefold() for marker in _WEB_CHROME_MARKERS):
        return ""
    # Repeated navigation/content fragments are a common result of a responsive
    # page rendering the same heading twice.  One concise statement is enough.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    unique: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        key = sentence.casefold().strip()
        if key and key not in seen:
            unique.append(sentence.strip())
            seen.add(key)
    return " ".join(unique)[:limit].strip()


def supported_matches(
    records: list[Any], facts: list[Any], locale: str, *, permission: str = "use_in_scoring"
) -> list[dict]:
    permitted = [
        r for r in records if r.verified and r.store_private and getattr(r, permission, False)
    ]
    result = []
    for key, ru, en, markers, flag in CAPABILITIES:
        supporting = []
        for record in permitted:
            text = " ".join(
                str(getattr(record, field, "") or "")
                for field in ("name", "text", "position", "project_types", "evidence")
            ).casefold()
            if (flag and getattr(record, flag, False)) or contains_capability(text, markers):
                supporting.append(str(record.id))
        evidence = next(
            (
                (f, company_evidence_excerpt(f.value))
                for f in facts
                if f.status == "verified"
                and f.source_id
                and contains_capability(f.value, markers)
                and company_evidence_excerpt(f.value)
            ),
            None,
        )
        if supporting and evidence:
            fact, evidence_text = evidence
            label = ru if locale == "ru" else en
            result.append(
                {
                    "key": key,
                    "label": label,
                    "candidate_ids": supporting,
                    "company_fact_id": str(fact.id),
                    "source_id": str(fact.source_id),
                    "company_evidence": evidence_text,
                    "explanation": (
                        (
                            f"Компания работает в контексте: {evidence_text}. "
                            f"Ваш подтверждённый опыт: {label}."
                        )
                        if locale == "ru"
                        else (
                            f"Company context: {evidence_text}. "
                            f"Your verified experience: {label}."
                        )
                    ),
                    "scenario": (
                        (
                            "Написать с коротким предложением обсудить задачи в направлении "
                            f"«{label}». "
                            "Конкретная роль или потребность компании пока не подтверждена."
                        )
                        if locale == "ru"
                        else (
                            f"Write with a concise offer to discuss work involving {label}. "
                            "A specific role or company need is not yet confirmed."
                        )
                    ),
                }
            )
    return result[:3]


async def profile_records(session, profile_id) -> list[Any]:
    records = []
    if profile_id:
        for model in (CandidateExperience, CandidateSkill, CandidateFact):
            records.extend(
                await session.scalars(select(model).where(model.profile_id == profile_id))
            )
    return records


def job_risks(job, profile, records: list[Any], locale: str) -> list[dict]:
    """Compare explicit requirements only; company technology is not a job requirement."""
    result = []
    ru = locale == "ru"

    def add(text):
        result.append({"text": text, "source": job.url})

    description = job.description or ""
    levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
    required = re.search(
        r"(?:english|английск\w*)[^.!?\n]{0,45}\b(A1|A2|B1|B2|C1|C2)\b", description, re.I
    )
    current = re.search(
        r"\b(A1|A2|B1|B2|C1|C2)\b", (getattr(profile, "language_level", "") or ""), re.I
    )
    if (
        required
        and current
        and levels.index(required[1].upper()) > levels.index(current[1].upper())
    ):
        add(
            f"В вакансии указан английский {required[1].upper()}; в профиле — {current[1].upper()}."
            if ru
            else (
                f"The vacancy specifies English {required[1].upper()}; "
                f"your profile states {current[1].upper()}."
            )
        )
    skills = [
        r for r in records if r.verified and r.store_private and getattr(r, "use_in_scoring", False)
    ]
    text = " ".join(
        str(getattr(r, "name", "") or getattr(r, "text", "")) for r in skills
    ).casefold()
    for skill in job.required_skills or []:
        if skill.casefold() not in text:
            # Product/technology names are proper names, not untranslated prose.
            if not language_matches(skill, locale) and len(skill.split()) > 3:
                continue
            add(
                f"Требуется {skill}; подтверждённый навык в профиле не найден."
                if ru
                else f"{skill} is required; no verified matching skill was found in your profile."
            )
    for pattern, russian, english in (
        (
            r"(?:must|require[ds]?).{0,35}(?:work permit|work authorization)",
            "Требуется разрешение на работу.",
            "Work authorization is required.",
        ),
        (
            r"(?:must be|only).{0,20}(?:based|residen).{0,15}(?:united states|usa|u\.s\.)",
            "Найм ограничен проживающими в США.",
            "Hiring is restricted to US residents.",
        ),
        (
            r"(?:on.site|in.office) (?:only|required)|обязательн\w*.{0,30}офис",
            "Обязательна работа из офиса; проверьте возможность переезда.",
            "Office attendance is required; check relocation feasibility.",
        ),
    ):
        if re.search(pattern, description, re.I):
            add(russian if ru else english)
    return result


def quality_checks(company, payload: dict, contact_ready: bool) -> dict[str, bool]:
    # A country is a mandatory evidence gate only when the task explicitly
    # constrained geography.  For a worldwide / relocation-ready search the
    # executor records ``not_required``; the country remains useful context in
    # the card, but must not hide an otherwise qualified opportunity.
    geography_ready = (
        company.geography_verification_status == "not_required"
        or (
            company.geography_verification_status == "verified"
            and bool(payload.get("country"))
        )
    )
    return {
        "identity": company.identity_verification_status == "verified",
        "description": bool(payload.get("one_line") and payload.get("overview")),
        "geography": geography_ready,
        "profile_fit": bool(payload.get("matches")),
        "research": payload.get("research_status") == "complete",
        "localization": payload.get("locale_validated") is True,
        "vacancy_review": payload.get("vacancy_reviewed") is True,
        "risk_review": payload.get("risk_reviewed") is True,
        # A contact determines whether outreach can start now.  It is not a
        # prerequisite for showing an evidence-backed company to the owner.
        "contact": True,
        "relevance": company.relevance_status != "not_relevant",
    }


def ready_for_inbox(company, payload: dict, contact_ready: bool) -> bool:
    return all(quality_checks(company, payload, contact_ready).values())
