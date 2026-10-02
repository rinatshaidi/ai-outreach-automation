"""Jinja2 and HTMX routes for candidate profile management."""

import json
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select

from app.api.candidate_profile import (
    DbSession,
    change_record_verification,
    create_contact,
    create_experience,
    create_fact,
    create_rule,
    create_skill,
    create_strength,
    delete_contact,
    delete_experience,
    delete_fact,
    get_primary_profile,
    owner_actor,
    preview_fact_pack,
    request_id,
    update_contact,
    update_experience,
    update_fact,
    update_skill,
    upsert_profile,
    verify_all_reviewed_records,
)
from app.api.profile_review import (
    apply_profile_import,
    create_profile_import,
    decide_import_item,
    decide_import_section,
    profile_import_preview,
    validate_profile_import,
)
from app.api.web import templates
from app.modules.audit.models import AuditEvent
from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateExperience,
    CandidateFact,
    CandidateRule,
    CandidateSkill,
    CandidateStrength,
)
from app.modules.candidate_profile.readiness import calculate_profile_readiness
from app.modules.candidate_profile.schemas import (
    BulkVerificationDecision,
    CandidateContactCreate,
    CandidateContactUpdate,
    CandidateExperienceCreate,
    CandidateExperienceUpdate,
    CandidateFactCreate,
    CandidateFactUpdate,
    CandidateProfileUpsert,
    CandidateRuleCreate,
    CandidateSkillCreate,
    CandidateSkillUpdate,
    CandidateStrengthCreate,
    ContactType,
    FactPackPurpose,
    FactType,
    ProfileStatus,
    RuleSeverity,
    SkillGroup,
    SkillLevel,
    StrengthType,
    VerificationDecision,
)
from app.modules.opportunities.schemas import CollaborationFormat, WorkplaceFormat
from app.modules.profile_review.models import (
    CandidateProfileSection,
    ProfileImportBatch,
    ProfileImportItem,
)
from app.modules.profile_review.schemas import (
    ImportItemDecision,
    ImportSectionDecision,
    ProfileImportCreate,
    ProfileSectionReview,
    ProfileSectionType,
    ReviewDecision,
)
from app.modules.profile_review.service import ensure_profile_sections, review_section

router = APIRouter(include_in_schema=False)


class ExperienceOverlapDecision(StrEnum):
    PARALLEL = "parallel"
    DEFER = "defer"

PROFILE_SECTION_LABELS = {
    ProfileSectionType.POSITIONING: "Позиционирование",
    ProfileSectionType.TITLE_SUMMARY: "Профессиональный заголовок и summary",
    ProfileSectionType.MANAGEMENT_BUSINESS_EXPERIENCE: "Управленческий и бизнес-опыт",
    ProfileSectionType.ROLES_PERIODS_INDUSTRIES: "Роли, периоды и отрасли",
    ProfileSectionType.PROJECTS_ACHIEVEMENTS: "Проекты и достижения",
    ProfileSectionType.TEAMS_BUDGETS_RESPONSIBILITY: "Команды, бюджеты и ответственность",
    ProfileSectionType.EXPERIENCE_GEOGRAPHY: "География реализованного опыта",
    ProfileSectionType.CONTRACTORS_PARTNERS_NEGOTIATIONS: "Подрядчики, партнёры и переговоры",
    ProfileSectionType.AI_PROJECTS: "AI- и automation-проекты",
    ProfileSectionType.TECHNICAL_SKILLS: "Технические навыки",
    ProfileSectionType.STRENGTHS: "Сильные стороны",
    ProfileSectionType.DESIRED_ADJACENT_ROLES: "Желаемые и смежные роли",
    ProfileSectionType.EXCLUDED_ROLES: "Исключённые роли",
    ProfileSectionType.EMPLOYMENT_PROJECT_FORMATS: "Форматы найма и проектной работы",
    ProfileSectionType.CONSULTING_CONTRACT: "Consulting и contract",
    ProfileSectionType.WORKPLACE_FORMATS: "Формат рабочего места",
    ProfileSectionType.RELOCATION_TRAVEL: "Релокация и командировки",
    ProfileSectionType.COUNTRIES_REGIONS: "Страны и регионы",
    ProfileSectionType.INCOME_CONSTRAINTS: "Доход и ограничения",
    ProfileSectionType.LANGUAGES: "Языки",
    ProfileSectionType.CONTACTS: "Контакты и профессиональные ссылки",
    ProfileSectionType.POSITIONING_CONSTRAINTS: "Ограничения позиционирования",
    ProfileSectionType.PERMISSIONS_CONSENT: "Разрешения и согласия",
}


def csv_values(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def form_list_values(value: str, field: str, errors: dict[str, str]) -> list[str]:
    stripped = value.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            errors[field] = "Некорректный JSON-массив. Используйте значения через запятую."
            return []
        if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
            errors[field] = "Ожидается список строк или значения через запятую."
            return []
        return list(dict.fromkeys(item.strip() for item in decoded if item.strip()))
    return csv_values(stripped)


def enum_form_values[EnumValue: StrEnum](
    value: str,
    enum_type: type[EnumValue],
    field: str,
    errors: dict[str, str],
) -> list[EnumValue]:
    values = form_list_values(value, field, errors)
    allowed = {item.value for item in enum_type}
    invalid = [item for item in values if item not in allowed]
    if invalid:
        errors[field] = (
            f"Недопустимые значения: {', '.join(invalid)}. "
            f"Допустимо: {', '.join(sorted(allowed))}."
        )
        return []
    return [enum_type(item) for item in values]


def experience_years(value: str, field: str, errors: dict[str, str]) -> float | None:
    stripped = value.strip().replace(",", ".")
    if not stripped:
        return None
    numeric = stripped[:-1].strip() if stripped.endswith("+") else stripped
    try:
        parsed = float(numeric)
    except ValueError:
        errors[field] = "Укажите число от 0 до 80. Допустима запись 10+."
        return None
    if not 0 <= parsed <= 80:
        errors[field] = "Значение должно быть от 0 до 80 лет."
        return None
    return parsed


def pydantic_form_errors(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for item in exc.errors():
        field = str(item["loc"][0]) if item["loc"] else "_form"
        error_type = str(item["type"])
        if error_type == "string_too_long":
            maximum = item.get("ctx", {}).get("max_length")
            message = (
                f"Текст превышает допустимую длину: максимум {maximum} символов."
                if maximum
                else "Текст превышает допустимую длину."
            )
        elif error_type in {"too_long", "list_too_long"}:
            message = "Указано слишком много значений."
        elif error_type == "literal_error" and field == "store_private":
            message = "Для сохранения записи включите «Хранить локально»."
        else:
            message = f"Поле заполнено неверно: {item['msg']}"
        errors.setdefault(field, message)
    return errors


EXPERIENCE_FORM_LABELS = {
    "position": "Должность",
    "organization_label": "Организация",
    "industry": "Отрасль",
    "started_at": "Дата начала",
    "ended_at": "Дата окончания",
    "project_types": "Типы проектов",
    "responsibility_level": "Уровень ответственности",
    "team_size_max": "Максимальный размер команды",
    "project_geographies": "География проектов",
    "store_private": "Хранить локально",
    "_form": "Запись опыта",
}


def experience_form_values(experience: CandidateExperience | None = None) -> dict[str, object]:
    if experience is None:
        return {
            "position": "",
            "organization_label": "",
            "industry": "",
            "started_at": "",
            "ended_at": "",
            "project_types": "",
            "responsibility_level": "",
            "team_size_max": "",
            "project_geographies": "",
            "contractor_management": False,
            "negotiations": False,
            "territory_development": False,
            "launches": False,
            "operations_management": False,
            "store_private": True,
            "use_for_ai_analysis": False,
            "use_in_scoring": False,
            "use_in_draft": False,
            "send_externally": False,
            "use_in_signature": False,
            "publish_publicly": False,
            "confirm_duplicate": False,
        }
    return {
        "version": experience.version,
        "position": experience.position,
        "organization_label": experience.organization_label or "",
        "industry": experience.industry or "",
        "started_at": experience.started_at.isoformat() if experience.started_at else "",
        "ended_at": experience.ended_at.isoformat() if experience.ended_at else "",
        "project_types": ", ".join(experience.project_types),
        "responsibility_level": experience.responsibility_level or "",
        "team_size_max": experience.team_size_max if experience.team_size_max is not None else "",
        "project_geographies": ", ".join(experience.project_geographies),
        "contractor_management": experience.contractor_management,
        "negotiations": experience.negotiations,
        "territory_development": experience.territory_development,
        "launches": experience.launches,
        "operations_management": experience.operations_management,
        "store_private": experience.store_private,
        "use_for_ai_analysis": experience.use_for_ai_analysis,
        "use_in_scoring": experience.use_in_scoring,
        "use_in_draft": experience.use_in_draft,
        "send_externally": experience.send_externally,
        "use_in_signature": experience.use_in_signature,
        "publish_publicly": experience.publish_publicly,
        "confirm_duplicate": False,
    }


def without_form_label(value: str, *labels: str) -> str:
    """Accept pasted values both with and without their visible form label."""

    stripped = value.strip()
    for label in labels:
        prefix = f"{label}:"
        if stripped.casefold().startswith(prefix.casefold()):
            return stripped[len(prefix) :].strip()
    return stripped


def optional_date(value: str, field: str, errors: dict[str, str]) -> date | None:
    cleaned = without_form_label(
        value,
        "Дата начала" if field == "started_at" else "Дата окончания",
    )
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        errors[field] = "Укажите корректную дату."
        return None


def optional_team_size(value: str, errors: dict[str, str]) -> int | None:
    cleaned = without_form_label(value, "Макс. команда", "Максимальная команда")
    if not cleaned:
        return None
    try:
        parsed = int(cleaned)
    except ValueError:
        errors["team_size_max"] = "Укажите целое число от 0 до 1 000 000."
        return None
    if not 0 <= parsed <= 1_000_000:
        errors["team_size_max"] = "Размер команды должен быть от 0 до 1 000 000."
        return None
    return parsed


def experience_payload_from_form(
    values: dict[str, object], errors: dict[str, str]
) -> CandidateExperienceCreate | None:
    started_at = optional_date(str(values["started_at"]), "started_at", errors)
    ended_at = optional_date(str(values["ended_at"]), "ended_at", errors)
    team_size_max = optional_team_size(str(values["team_size_max"]), errors)
    if started_at and ended_at and ended_at < started_at:
        errors["ended_at"] = "Дата окончания не может быть раньше даты начала."
    if errors:
        return None
    try:
        return CandidateExperienceCreate(
            position=without_form_label(str(values["position"]), "Должность"),
            organization_label=without_form_label(
                str(values["organization_label"]), "Организация"
            )
            or None,
            industry=without_form_label(str(values["industry"]), "Отрасль") or None,
            started_at=started_at,
            ended_at=ended_at,
            project_types=csv_values(
                without_form_label(str(values["project_types"]), "Типы проектов")
            ),
            responsibility_level=without_form_label(
                str(values["responsibility_level"]), "Уровень ответственности"
            )
            or None,
            team_size_max=team_size_max,
            project_geographies=csv_values(
                without_form_label(
                    str(values["project_geographies"]), "География проектов"
                )
            ),
            contractor_management=bool(values["contractor_management"]),
            negotiations=bool(values["negotiations"]),
            territory_development=bool(values["territory_development"]),
            launches=bool(values["launches"]),
            operations_management=bool(values["operations_management"]),
            verified=False,
            store_private=bool(values["store_private"]),
            use_for_ai_analysis=bool(values["use_for_ai_analysis"]),
            use_in_scoring=bool(values["use_in_scoring"]),
            use_in_draft=bool(values["use_in_draft"]),
            send_externally=bool(values["send_externally"]),
            use_in_signature=bool(values["use_in_signature"]),
            publish_publicly=bool(values["publish_publicly"]),
        )
    except ValidationError as exc:
        errors.update(pydantic_form_errors(exc))
        return None


def http_exception_message(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        return str(exc.detail.get("message", "Не удалось сохранить запись."))
    return str(exc.detail)


def skill_form_values(skill: CandidateSkill) -> dict[str, object]:
    return {
        "version": skill.version,
        "name": skill.name,
        "skill_group": skill.skill_group,
        "actual_level": skill.actual_level,
        "duration_months": (
            skill.duration_months if skill.duration_months is not None else ""
        ),
        "evidence": skill.evidence or "",
        "verified_results": skill.verified_results or "",
        "limitations": skill.limitations or "",
        "store_private": skill.store_private,
        "use_for_ai_analysis": skill.use_for_ai_analysis,
        "use_in_scoring": skill.use_in_scoring,
        "use_in_draft": skill.use_in_draft,
        "send_externally": skill.send_externally,
        "use_in_signature": skill.use_in_signature,
        "publish_publicly": skill.publish_publicly,
    }


def profile_form_values(profile: object | None) -> dict[str, object]:
    list_fields = (
        "desired_roles",
        "adjacent_roles",
        "excluded_roles",
        "preferred_industries",
        "excluded_industries",
        "preferred_countries",
        "work_formats",
        "remote_work_countries",
        "relocation_countries",
        "business_trip_countries",
        "preferred_regions",
        "collaboration_formats",
        "workplace_formats",
        "preferred_company_types",
    )
    scalar_fields = (
        "display_name",
        "professional_title",
        "location",
        "summary",
        "total_years_experience",
        "management_years_experience",
        "geography_constraints",
        "visa_or_sponsorship_required",
        "target_income",
        "desired_responsibility_level",
        "preferred_culture",
        "language_level",
        "profile_status",
    )
    values: dict[str, object] = {
        field: ", ".join(getattr(profile, field, []) or []) for field in list_fields
    }
    values.update({field: getattr(profile, field, "") or "" for field in scalar_fields})
    visa_value = getattr(profile, "visa_or_sponsorship_required", None)
    values["visa_or_sponsorship_required"] = (
        "" if visa_value is None else "true" if visa_value else "false"
    )
    values["temporary_relocation_allowed"] = bool(
        getattr(profile, "temporary_relocation_allowed", False)
    )
    values["on_the_ground_launch_allowed"] = bool(
        getattr(profile, "on_the_ground_launch_allowed", False)
    )
    return values


SECTION_STATUS_LABELS = {
    "draft": "Черновик",
    "review_required": "Требует проверки",
    "user_approved": "Подтверждено вами",
    "verified": "Проверено отдельно",
}

PROFILE_FORM_LABELS = {
    "_form": "Форма профиля",
    "display_name": "Отображаемое имя",
    "professional_title": "Профессиональный заголовок",
    "location": "Локация",
    "summary": "Summary",
    "total_years_experience": "Общий опыт",
    "management_years_experience": "Управленческий опыт",
    "desired_roles": "Желаемые роли",
    "preferred_countries": "Страны",
    "collaboration_formats": "Форматы сотрудничества",
    "workplace_formats": "Форматы рабочего места",
    "visa_or_sponsorship_required": "Visa / sponsorship",
    "target_income": "Целевой доход",
    "profile_status": "Статус профиля",
}


def _sentence(value: object | None) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _render_import_item(item: ProfileImportItem) -> str:
    data = item.proposed_data
    entity_type = item.target_entity_type
    lines: list[str] = []
    if entity_type == "fact":
        lines.append(_sentence(data.get("text")))
        evidence = _sentence(data.get("evidence"))
        if evidence:
            lines.append(f"Основание или ограничение: {evidence}")
    elif entity_type == "skill":
        name = _sentence(data.get("name"))
        level = _sentence(data.get("actual_level"))
        lines.append(f"{name} — уровень: {level}." if level else name)
        evidence = _sentence(data.get("evidence"))
        limitations = _sentence(data.get("limitations"))
        if evidence:
            lines.append(f"Практическое основание: {evidence}")
        if limitations:
            lines.append(f"Ограничение: {limitations}")
    elif entity_type == "strength":
        lines.append(_sentence(data.get("text")))
        evidence = _sentence(data.get("evidence"))
        if evidence:
            lines.append(f"Основание: {evidence}")
    elif entity_type == "experience":
        position = _sentence(data.get("position"))
        industry = _sentence(data.get("industry"))
        heading = position + (f" — {industry}." if industry else ".")
        lines.append(heading)
        project_types = data.get("project_types") or []
        if project_types:
            lines.append(f"Типы проектов: {', '.join(map(str, project_types))}.")
        responsibility = _sentence(data.get("responsibility_level"))
        if responsibility:
            lines.append(f"Ответственность: {responsibility}")
        limitations = _sentence(data.get("crisis_or_complex_situations"))
        if limitations:
            lines.append(f"Что требует уточнения: {limitations}")
    elif entity_type == "contact":
        contact_type = _sentence(data.get("contact_type"))
        value = _sentence(data.get("value"))
        lines.append(f"{contact_type}: {value}" if contact_type else value)
    return "\n".join(line for line in lines if line)


def render_section_content(section_type: str, items: list[ProfileImportItem]) -> str:
    rendered = [_render_import_item(item) for item in items]
    rendered = [item for item in rendered if item]
    if rendered:
        return "\n\n".join(f"• {item}" for item in rendered)
    if section_type == ProfileSectionType.CONTACTS.value:
        return (
            "Точные профессиональные контакты и ссылки пока не указаны. "
            "Добавьте сюда только те значения, которые разрешено хранить локально. "
            "Разрешения для AI, писем, подписи и публикации согласовываются отдельно."
        )
    return (
        "В предварительном профиле недостаточно точных сведений для этого блока. "
        "Дополните текст или оставьте блок без подтверждения."
    )


@router.get("/candidate-profile", response_class=HTMLResponse)
async def candidate_profile_page(request: Request, session: DbSession) -> HTMLResponse:
    profile = await get_primary_profile(session)
    facts: list[CandidateFact] = []
    contacts: list[CandidateContact] = []
    rules: list[CandidateRule] = []
    experiences: list[CandidateExperience] = []
    skills: list[CandidateSkill] = []
    strengths: list[CandidateStrength] = []
    sections: list[CandidateProfileSection] = []
    section_cards: list[dict[str, object]] = []
    readiness: dict[str, object] = {"status": "NOT_READY", "pilot_first_wave_ready": False}
    if profile is not None:
        sections = await ensure_profile_sections(session, profile)
        facts = list(
            await session.scalars(
                select(CandidateFact)
                .where(CandidateFact.profile_id == profile.id)
                .order_by(CandidateFact.created_at.desc())
            )
        )
        contacts = list(
            await session.scalars(
                select(CandidateContact)
                .where(CandidateContact.profile_id == profile.id)
                .order_by(CandidateContact.created_at.desc())
            )
        )
        rules = list(
            await session.scalars(
                select(CandidateRule)
                .where(CandidateRule.profile_id == profile.id)
                .order_by(CandidateRule.priority)
            )
        )
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
                .order_by(CandidateSkill.skill_group, CandidateSkill.name)
            )
        )
        strengths = list(
            await session.scalars(
                select(CandidateStrength)
                .where(CandidateStrength.profile_id == profile.id)
                .order_by(CandidateStrength.priority)
            )
        )
        latest_batch = await session.scalar(
            select(ProfileImportBatch)
            .where(ProfileImportBatch.profile_id == profile.id)
            .order_by(ProfileImportBatch.created_at.desc())
            .limit(1)
        )
        import_items: list[ProfileImportItem] = []
        if latest_batch is not None:
            import_items = list(
                await session.scalars(
                    select(ProfileImportItem)
                    .where(ProfileImportItem.batch_id == latest_batch.id)
                    .order_by(ProfileImportItem.id)
                )
            )
        items_by_section: dict[str, list[ProfileImportItem]] = {}
        for item in import_items:
            items_by_section.setdefault(item.section_type, []).append(item)
        section_cards = [
            {
                "section": section,
                "label": PROFILE_SECTION_LABELS[ProfileSectionType(section.section_type)],
                "status_label": SECTION_STATUS_LABELS.get(section.status, section.status),
                "content": section.content_draft
                or render_section_content(
                    section.section_type,
                    items_by_section.get(section.section_type, []),
                ),
            }
            for section in sections
        ]
        readiness = await calculate_profile_readiness(session, profile)
        await session.commit()
    profile_form_errors: dict[str, str] = getattr(request.state, "profile_form_errors", {})
    experience_edits = {
        str(item.id): experience_form_values(item) for item in experiences
    }
    experience_edits.update(getattr(request.state, "experience_edits", {}))
    experience_form_errors: dict[str, str] = getattr(
        request.state, "experience_form_errors", {}
    )
    skill_edits = {str(item.id): skill_form_values(item) for item in skills}
    skill_edits.update(getattr(request.state, "skill_edits", {}))
    return templates.TemplateResponse(
        request=request,
        name="candidate_profile.html",
        context={
            "profile": profile,
            "facts": facts,
            "contacts": contacts,
            "rules": rules,
            "experiences": experiences,
            "skills": skills,
            "strengths": strengths,
            "fact_types": list(FactType),
            "contact_types": list(ContactType),
            "skill_groups": list(SkillGroup),
            "skill_levels": list(SkillLevel),
            "strength_types": list(StrengthType),
            "profile_sections": sections,
            "section_cards": section_cards,
            "open_section": request.query_params.get("open"),
            "profile_form": getattr(
                request.state,
                "profile_form",
                profile_form_values(profile),
            ),
            "profile_form_errors": profile_form_errors,
            "profile_form_error_items": [
                {
                    "field": field,
                    "label": PROFILE_FORM_LABELS.get(field, field),
                    "message": message,
                }
                for field, message in profile_form_errors.items()
            ],
            "experience_form": getattr(
                request.state, "experience_form", experience_form_values()
            ),
            "experience_form_labels": EXPERIENCE_FORM_LABELS,
            "experience_form_errors": experience_form_errors,
            "experience_form_error_items": [
                {
                    "field": field,
                    "label": EXPERIENCE_FORM_LABELS.get(field, field),
                    "message": message,
                }
                for field, message in experience_form_errors.items()
            ],
            "experience_duplicate": getattr(
                request.state, "experience_duplicate", None
            ),
            "experience_edits": experience_edits,
            "experience_edit_errors": getattr(
                request.state, "experience_edit_errors", {}
            ),
            "experience_edit_duplicates": getattr(
                request.state, "experience_edit_duplicates", {}
            ),
            "open_experience": getattr(request.state, "open_experience", None),
            "experience_action_error": getattr(
                request.state, "experience_action_error", None
            ),
            "experience_notice": request.query_params.get("experience_notice"),
            "skill_edits": skill_edits,
            "skill_edit_errors": getattr(request.state, "skill_edit_errors", {}),
            "open_skill": getattr(request.state, "open_skill", None),
            "skill_notice": request.query_params.get("skill_notice"),
            "fact_notice": request.query_params.get("fact_notice"),
            "contact_notice": request.query_params.get("contact_notice"),
            "fact_action_error": getattr(request.state, "fact_action_error", None),
            "contact_action_error": getattr(
                request.state, "contact_action_error", None
            ),
            "profile_readiness": readiness,
            "verification_groups": [
                {
                    "key": "experience",
                    "label": "Professional Experience",
                    "items": [
                        {
                            "id": item.id,
                            "version": item.version,
                            "value": f"{item.position} · {item.organization_label or '—'}",
                            "verified": item.verified,
                            "record": item,
                        }
                        for item in experiences
                    ],
                },
                {
                    "key": "skill",
                    "label": "Skills",
                    "items": [
                        {
                            "id": item.id,
                            "version": item.version,
                            "value": f"{item.name} · {item.skill_group} / {item.actual_level}",
                            "verified": item.verified,
                            "record": item,
                        }
                        for item in skills
                    ],
                },
                {
                    "key": "strength",
                    "label": "Strengths",
                    "items": [
                        {
                            "id": item.id,
                            "version": item.version,
                            "value": item.text,
                            "verified": item.verified,
                            "record": item,
                        }
                        for item in strengths
                    ],
                },
                {
                    "key": "fact",
                    "label": "Candidate Facts",
                    "items": [
                        {
                            "id": item.id,
                            "version": item.version,
                            "value": item.text,
                            "verified": item.verified,
                            "record": item,
                        }
                        for item in facts
                    ],
                },
                {
                    "key": "contact",
                    "label": "Contacts",
                    "items": [
                        {
                            "id": item.id,
                            "version": item.version,
                            "value": f"{item.contact_type} · {item.value}",
                            "verified": item.verified,
                            "record": item,
                        }
                        for item in contacts
                    ],
                },
            ],
            "overlapping_experiences": [
                (left, right)
                for index, left in enumerate(experiences)
                for right in experiences[index + 1 :]
                if left.started_at
                and right.started_at
                and (left.ended_at is None or left.ended_at >= right.started_at)
                and (right.ended_at is None or right.ended_at >= left.started_at)
            ],
            "verification_notice": request.query_params.get("verification_notice"),
            "overlap_notice": request.query_params.get("overlap_notice"),
        },
    )


@router.post("/candidate-profile/verification/{entity_type}/{entity_id}")
async def verify_candidate_record_web(
    entity_type: str,
    entity_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form(ge=1)],
    verified: Annotated[bool, Form()],
    confirmed: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await change_record_verification(
        entity_type,
        entity_id,
        VerificationDecision(version=version, verified=verified, confirmed=confirmed),
        request,
        session,
    )
    return RedirectResponse(
        "/candidate-profile?verification_notice=updated#final-verification",
        status_code=303,
    )


@router.post("/candidate-profile/verification/verify-all")
async def verify_all_candidate_records_web(
    request: Request,
    session: DbSession,
    confirmed: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await verify_all_reviewed_records(
        BulkVerificationDecision(confirmed=confirmed), request, session
    )
    return RedirectResponse(
        "/candidate-profile?verification_notice=all_verified#final-verification",
        status_code=303,
    )


@router.post("/candidate-profile/experience-overlap")
async def decide_experience_overlap_web(
    request: Request,
    session: DbSession,
    left_id: Annotated[UUID, Form()],
    right_id: Annotated[UUID, Form()],
    decision: Annotated[ExperienceOverlapDecision, Form()],
    confirmed: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    if not confirmed or left_id == right_id:
        raise HTTPException(status_code=422, detail="Explicit overlap decision is required")
    profile = await get_primary_profile(session)
    if profile is None:
        return RedirectResponse(url="/candidate-profile", status_code=303)
    records = list(
        await session.scalars(
            select(CandidateExperience).where(
                CandidateExperience.profile_id == profile.id,
                CandidateExperience.id.in_((left_id, right_id)),
            )
        )
    )
    if len(records) != 2:
        raise HTTPException(status_code=404, detail="Experience records were not found")
    session.add(
        AuditEvent(
            actor=owner_actor(request),
            action="candidate_experience_overlap_reviewed",
            entity_type="candidate_experience_pair",
            entity_id=f"{left_id}:{right_id}",
            result="success",
            safe_diff={"decision": decision.value},
            request_id=request_id(request),
        )
    )
    await session.commit()
    return RedirectResponse(
        f"/candidate-profile?overlap_notice={decision.value}#final-verification",
        status_code=303,
    )
@router.post("/candidate-profile/sections/{section_type}/review")
async def review_profile_section_web(
    section_type: str,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form(ge=1)],
    decision: Annotated[ReviewDecision, Form()],
    content: Annotated[str, Form(min_length=1, max_length=20_000)],
    comment: Annotated[str | None, Form(max_length=4000)] = None,
) -> RedirectResponse:
    profile = await get_primary_profile(session)
    if profile is None:
        return RedirectResponse(url="/candidate-profile", status_code=303)
    sections = await ensure_profile_sections(session, profile)
    section = next((item for item in sections if item.section_type == section_type), None)
    if section is None or section.version != version:
        return RedirectResponse(
            url=f"/candidate-profile?open={section_type}#review-{section_type}",
            status_code=303,
        )
    owner = getattr(request.state, "owner", None)
    normalized_content = content.strip()
    content_hash = sha256(normalized_content.encode("utf-8")).hexdigest()
    section.content_draft = normalized_content
    try:
        await review_section(
            session,
            section,
            decision=ProfileSectionReview(version=version, decision=decision).decision,
            actor=str(owner.id) if owner is not None else "local-test-owner",
            comment=comment,
            content_hash=content_hash,
            request_id=str(getattr(request.state, "request_id", "profile-review-web")),
        )
    except ValueError:
        await session.rollback()
    else:
        await session.commit()
    return RedirectResponse(
        url=f"/candidate-profile?open={section_type}#review-{section_type}",
        status_code=303,
    )


@router.post("/candidate-profile/import-preview")
async def create_profile_import_web(
    session: DbSession,
    source_filename: Annotated[str, Form(min_length=1, max_length=240)],
    items_json: Annotated[str, Form(min_length=2, max_length=200_000)],
) -> RedirectResponse:
    decoded = json.loads(items_json)
    payload = ProfileImportCreate.model_validate(
        {"source_filename": source_filename, "items": decoded}
    )
    batch = await create_profile_import(payload, session)
    return RedirectResponse(url=f"/candidate-profile/imports/{batch.id}", status_code=303)


@router.get("/candidate-profile/imports/{batch_id}", response_class=HTMLResponse)
async def profile_import_page(batch_id: UUID, request: Request, session: DbSession) -> HTMLResponse:
    batch = await profile_import_preview(batch_id, session)
    items_by_section: dict[str, list[object]] = {}
    for item in batch.items:
        items_by_section.setdefault(item.section_type, []).append(item)
    section_groups = [
        {
            "number": number,
            "type": section_type.value,
            "label": PROFILE_SECTION_LABELS[section_type],
            "entries": items_by_section.get(section_type.value, []),
        }
        for number, section_type in enumerate(ProfileSectionType, start=1)
    ]
    pending_count = sum(item.decision == "pending" for item in batch.items)
    approved_count = sum(item.decision == "approved" for item in batch.items)
    return templates.TemplateResponse(
        request=request,
        name="profile_import.html",
        context={
            "batch": batch,
            "section_groups": section_groups,
            "pending_count": pending_count,
            "approved_count": approved_count,
        },
    )


@router.post("/candidate-profile/imports/{batch_id}/validate")
async def validate_profile_import_web(batch_id: UUID, session: DbSession) -> RedirectResponse:
    await validate_profile_import(batch_id, session)
    return RedirectResponse(url=f"/candidate-profile/imports/{batch_id}", status_code=303)


@router.post("/candidate-profile/imports/{batch_id}/items/{item_id}/decision")
async def decide_import_item_web(
    batch_id: UUID,
    item_id: UUID,
    session: DbSession,
    version: Annotated[int, Form(ge=1)],
    decision: Annotated[str, Form(pattern="^(approved|deferred|rejected)$")],
) -> RedirectResponse:
    await decide_import_item(
        batch_id,
        item_id,
        ImportItemDecision(version=version, decision=decision),
        session,
    )
    return RedirectResponse(url=f"/candidate-profile/imports/{batch_id}", status_code=303)


@router.post("/candidate-profile/imports/{batch_id}/sections/{section_type}/decision")
async def decide_import_section_web(
    batch_id: UUID,
    section_type: ProfileSectionType,
    session: DbSession,
    decision: Annotated[str, Form(pattern="^(approved|deferred|rejected)$")],
) -> RedirectResponse:
    await decide_import_section(
        batch_id,
        section_type,
        ImportSectionDecision(decision=decision),
        session,
    )
    return RedirectResponse(
        url=f"/candidate-profile/imports/{batch_id}#section-{section_type.value}",
        status_code=303,
    )


@router.post("/candidate-profile/imports/{batch_id}/apply")
async def apply_profile_import_web(batch_id: UUID, session: DbSession) -> RedirectResponse:
    await apply_profile_import(batch_id, session)
    return RedirectResponse(url=f"/candidate-profile/imports/{batch_id}", status_code=303)


@router.post("/candidate-profile/profile")
async def save_profile(
    request: Request,
    session: DbSession,
    display_name: Annotated[str, Form()] = "",
    professional_title: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    summary: Annotated[str, Form()] = "",
    total_years_experience: Annotated[str, Form()] = "",
    management_years_experience: Annotated[str, Form()] = "",
    desired_roles: Annotated[str, Form()] = "",
    adjacent_roles: Annotated[str, Form()] = "",
    excluded_roles: Annotated[str, Form()] = "",
    preferred_industries: Annotated[str, Form()] = "",
    excluded_industries: Annotated[str, Form()] = "",
    preferred_countries: Annotated[str, Form()] = "",
    work_formats: Annotated[str, Form()] = "",
    remote_work_countries: Annotated[str, Form()] = "",
    relocation_countries: Annotated[str, Form()] = "",
    business_trip_countries: Annotated[str, Form()] = "",
    preferred_regions: Annotated[str, Form()] = "",
    geography_constraints: Annotated[str, Form()] = "",
    visa_or_sponsorship_required: Annotated[str, Form()] = "",
    temporary_relocation_allowed: Annotated[bool, Form()] = False,
    on_the_ground_launch_allowed: Annotated[bool, Form()] = False,
    collaboration_formats: Annotated[str, Form()] = "",
    workplace_formats: Annotated[str, Form()] = "",
    target_income: Annotated[str, Form()] = "",
    desired_responsibility_level: Annotated[str, Form()] = "",
    preferred_company_types: Annotated[str, Form()] = "",
    preferred_culture: Annotated[str, Form()] = "",
    language_level: Annotated[str, Form()] = "",
    profile_status: Annotated[str, Form()] = ProfileStatus.DRAFT.value,
    version: Annotated[int | None, Form()] = None,
) -> Response:
    form_values: dict[str, object] = {
        "display_name": display_name,
        "professional_title": professional_title,
        "location": location,
        "summary": summary,
        "total_years_experience": total_years_experience,
        "management_years_experience": management_years_experience,
        "desired_roles": desired_roles,
        "adjacent_roles": adjacent_roles,
        "excluded_roles": excluded_roles,
        "preferred_industries": preferred_industries,
        "excluded_industries": excluded_industries,
        "preferred_countries": preferred_countries,
        "work_formats": work_formats,
        "remote_work_countries": remote_work_countries,
        "relocation_countries": relocation_countries,
        "business_trip_countries": business_trip_countries,
        "preferred_regions": preferred_regions,
        "geography_constraints": geography_constraints,
        "visa_or_sponsorship_required": visa_or_sponsorship_required,
        "temporary_relocation_allowed": temporary_relocation_allowed,
        "on_the_ground_launch_allowed": on_the_ground_launch_allowed,
        "collaboration_formats": collaboration_formats,
        "workplace_formats": workplace_formats,
        "target_income": target_income,
        "desired_responsibility_level": desired_responsibility_level,
        "preferred_company_types": preferred_company_types,
        "preferred_culture": preferred_culture,
        "language_level": language_level,
        "profile_status": profile_status,
    }
    errors: dict[str, str] = {}
    total_years = experience_years(total_years_experience, "total_years_experience", errors)
    management_years = experience_years(
        management_years_experience,
        "management_years_experience",
        errors,
    )
    collaboration_values = enum_form_values(
        collaboration_formats,
        CollaborationFormat,
        "collaboration_formats",
        errors,
    )
    workplace_values = enum_form_values(
        workplace_formats,
        WorkplaceFormat,
        "workplace_formats",
        errors,
    )
    if visa_or_sponsorship_required not in {"", "true", "false"}:
        errors["visa_or_sponsorship_required"] = (
            "Выберите: не указано, требуется или не требуется."
        )
    if profile_status not in {ProfileStatus.DRAFT.value, ProfileStatus.REVIEW_REQUIRED.value}:
        errors["profile_status"] = "Допустимы только Draft или Review required."

    list_inputs = {
        "desired_roles": desired_roles,
        "adjacent_roles": adjacent_roles,
        "excluded_roles": excluded_roles,
        "preferred_industries": preferred_industries,
        "excluded_industries": excluded_industries,
        "preferred_countries": preferred_countries,
        "work_formats": work_formats,
        "remote_work_countries": remote_work_countries,
        "relocation_countries": relocation_countries,
        "business_trip_countries": business_trip_countries,
        "preferred_regions": preferred_regions,
        "preferred_company_types": preferred_company_types,
    }
    parsed_lists = {
        field: form_list_values(value, field, errors) for field, value in list_inputs.items()
    }
    if errors:
        request.state.profile_form = form_values
        request.state.profile_form_errors = errors
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response

    try:
        payload = CandidateProfileUpsert(
            display_name=display_name or None,
            professional_title=professional_title or None,
            location=location or None,
            summary=summary or None,
            total_years_experience=total_years,
            management_years_experience=management_years,
            desired_roles=parsed_lists["desired_roles"],
            adjacent_roles=parsed_lists["adjacent_roles"],
            excluded_roles=parsed_lists["excluded_roles"],
            preferred_industries=parsed_lists["preferred_industries"],
            excluded_industries=parsed_lists["excluded_industries"],
            preferred_countries=parsed_lists["preferred_countries"],
            work_formats=parsed_lists["work_formats"],
            remote_work_countries=parsed_lists["remote_work_countries"],
            relocation_countries=parsed_lists["relocation_countries"],
            business_trip_countries=parsed_lists["business_trip_countries"],
            preferred_regions=parsed_lists["preferred_regions"],
            geography_constraints=geography_constraints or None,
            visa_or_sponsorship_required=(
                None
                if not visa_or_sponsorship_required
                else visa_or_sponsorship_required == "true"
            ),
            temporary_relocation_allowed=temporary_relocation_allowed,
            on_the_ground_launch_allowed=on_the_ground_launch_allowed,
            collaboration_formats=collaboration_values,
            workplace_formats=workplace_values,
            target_income=target_income or None,
            desired_responsibility_level=desired_responsibility_level or None,
            preferred_company_types=parsed_lists["preferred_company_types"],
            preferred_culture=preferred_culture or None,
            language_level=language_level or None,
            profile_status=ProfileStatus(profile_status),
            version=version,
        )
    except ValidationError as exc:
        errors.update(pydantic_form_errors(exc))
        request.state.profile_form = form_values
        request.state.profile_form_errors = errors
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response
    try:
        await upsert_profile(payload, session)
    except HTTPException as exc:
        await session.rollback()
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        errors["_form"] = str(detail.get("message", "Профиль не удалось сохранить."))
        request.state.profile_form = form_values
        request.state.profile_form_errors = errors
        response = await candidate_profile_page(request, session)
        response.status_code = exc.status_code
        return response
    return RedirectResponse("/candidate-profile", status_code=303)


@router.post("/candidate-profile/facts")
async def save_fact(
    request: Request,
    session: DbSession,
    fact_type: Annotated[FactType, Form()],
    text: Annotated[str, Form()],
    evidence: Annotated[str, Form()] = "",
    source_link: Annotated[str, Form()] = "",
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    payload = CandidateFactCreate(
        fact_type=fact_type,
        text=text,
        evidence=evidence or None,
        source_link=source_link or None,
        verified=False,
        store_private=store_private,
        use_for_ai_analysis=use_for_ai_analysis,
        use_in_scoring=use_in_scoring,
        use_in_draft=use_in_draft,
        send_externally=send_externally,
        use_in_signature=use_in_signature,
        publish_publicly=publish_publicly,
    )
    await create_fact(payload, request, session)
    return RedirectResponse("/candidate-profile#facts", status_code=303)


@router.post("/candidate-profile/facts/{fact_id}/permissions")
async def save_fact_permissions(
    fact_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await update_fact(
        fact_id,
        CandidateFactUpdate(
            version=version,
            store_private=store_private,
            use_for_ai_analysis=use_for_ai_analysis,
            use_in_scoring=use_in_scoring,
            use_in_draft=use_in_draft,
            send_externally=send_externally,
            use_in_signature=use_in_signature,
            publish_publicly=publish_publicly,
        ),
        request,
        session,
    )
    return RedirectResponse("/candidate-profile#facts", status_code=303)


@router.post("/candidate-profile/facts/{fact_id}/delete")
async def remove_fact(
    fact_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    confirm_delete: Annotated[str, Form()] = "",
) -> Response:
    if confirm_delete != "yes":
        request.state.fact_action_error = (
            "Удаление отменено: подтвердите удаление именно этого факта."
        )
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response
    try:
        await delete_fact(fact_id, version, request, session)
    except HTTPException as exc:
        await session.rollback()
        request.state.fact_action_error = http_exception_message(exc)
        response = await candidate_profile_page(request, session)
        response.status_code = exc.status_code
        return response
    return RedirectResponse(
        "/candidate-profile?fact_notice=deleted#facts", status_code=303
    )


@router.post("/candidate-profile/contacts")
async def save_contact(
    request: Request,
    session: DbSession,
    contact_type: Annotated[ContactType, Form()],
    value: Annotated[str, Form()],
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    payload = CandidateContactCreate(
        contact_type=contact_type,
        value=value,
        verified=False,
        store_private=store_private,
        use_for_ai_analysis=use_for_ai_analysis,
        use_in_scoring=use_in_scoring,
        use_in_draft=use_in_draft,
        send_externally=send_externally,
        use_in_signature=use_in_signature,
        publish_publicly=publish_publicly,
        allowed_in_signature=False,
    )
    await create_contact(payload, request, session)
    return RedirectResponse("/candidate-profile#contacts", status_code=303)


@router.post("/candidate-profile/contacts/{contact_id}/permissions")
async def save_contact_permissions(
    contact_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await update_contact(
        contact_id,
        CandidateContactUpdate(
            version=version,
            store_private=store_private,
            use_for_ai_analysis=use_for_ai_analysis,
            use_in_scoring=use_in_scoring,
            use_in_draft=use_in_draft,
            send_externally=send_externally,
            use_in_signature=use_in_signature,
            publish_publicly=publish_publicly,
        ),
        request,
        session,
    )
    return RedirectResponse("/candidate-profile#contacts", status_code=303)


@router.post("/candidate-profile/contacts/{contact_id}/delete")
async def remove_contact(
    contact_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    confirm_delete: Annotated[str, Form()] = "",
) -> Response:
    if confirm_delete != "yes":
        request.state.contact_action_error = (
            "Удаление отменено: подтвердите удаление именно этого контакта."
        )
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response
    try:
        await delete_contact(contact_id, version, request, session)
    except HTTPException as exc:
        await session.rollback()
        request.state.contact_action_error = http_exception_message(exc)
        response = await candidate_profile_page(request, session)
        response.status_code = exc.status_code
        return response
    return RedirectResponse(
        "/candidate-profile?contact_notice=deleted#contacts", status_code=303
    )


@router.post("/candidate-profile/rules")
async def save_rule(
    session: DbSession,
    rule_type: Annotated[str, Form()],
    text: Annotated[str, Form()],
    severity: Annotated[RuleSeverity, Form()] = RuleSeverity.BLOCK,
    priority: Annotated[int, Form()] = 100,
) -> RedirectResponse:
    await create_rule(
        CandidateRuleCreate(
            rule_type=rule_type,
            text=text,
            severity=severity,
            priority=priority,
        ),
        session,
    )
    return RedirectResponse("/candidate-profile#rules", status_code=303)


@router.post("/candidate-profile/experiences")
async def save_experience(
    request: Request,
    session: DbSession,
    position: Annotated[str, Form()],
    organization_label: Annotated[str, Form()] = "",
    industry: Annotated[str, Form()] = "",
    started_at: Annotated[str, Form()] = "",
    ended_at: Annotated[str, Form()] = "",
    project_types: Annotated[str, Form()] = "",
    responsibility_level: Annotated[str, Form()] = "",
    team_size_max: Annotated[str, Form()] = "",
    project_geographies: Annotated[str, Form()] = "",
    contractor_management: Annotated[bool, Form()] = False,
    negotiations: Annotated[bool, Form()] = False,
    territory_development: Annotated[bool, Form()] = False,
    launches: Annotated[bool, Form()] = False,
    operations_management: Annotated[bool, Form()] = False,
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
    confirm_duplicate: Annotated[bool, Form()] = False,
) -> Response:
    values: dict[str, object] = {
        "position": position,
        "organization_label": organization_label,
        "industry": industry,
        "started_at": started_at,
        "ended_at": ended_at,
        "project_types": project_types,
        "responsibility_level": responsibility_level,
        "team_size_max": team_size_max,
        "project_geographies": project_geographies,
        "contractor_management": contractor_management,
        "negotiations": negotiations,
        "territory_development": territory_development,
        "launches": launches,
        "operations_management": operations_management,
        "store_private": store_private,
        "use_for_ai_analysis": use_for_ai_analysis,
        "use_in_scoring": use_in_scoring,
        "use_in_draft": use_in_draft,
        "send_externally": send_externally,
        "use_in_signature": use_in_signature,
        "publish_publicly": publish_publicly,
        "confirm_duplicate": confirm_duplicate,
    }
    errors: dict[str, str] = {}
    payload = experience_payload_from_form(values, errors)
    duplicate: dict[str, object] | None = None
    if payload is not None:
        try:
            await create_experience(
                payload,
                request,
                session,
                confirm_duplicate=confirm_duplicate,
            )
        except HTTPException as exc:
            await session.rollback()
            errors["_form"] = http_exception_message(exc)
            if (
                isinstance(exc.detail, dict)
                and exc.detail.get("code") == "duplicate_candidate_experience"
            ):
                duplicate = exc.detail
    if errors:
        request.state.experience_form = values
        request.state.experience_form_errors = errors
        request.state.experience_duplicate = duplicate
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response
    return RedirectResponse(
        "/candidate-profile?experience_notice=created#experiences", status_code=303
    )


@router.post("/candidate-profile/experiences/{experience_id}/edit")
async def edit_experience(
    experience_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    position: Annotated[str, Form()],
    organization_label: Annotated[str, Form()] = "",
    industry: Annotated[str, Form()] = "",
    started_at: Annotated[str, Form()] = "",
    ended_at: Annotated[str, Form()] = "",
    project_types: Annotated[str, Form()] = "",
    responsibility_level: Annotated[str, Form()] = "",
    team_size_max: Annotated[str, Form()] = "",
    project_geographies: Annotated[str, Form()] = "",
    contractor_management: Annotated[bool, Form()] = False,
    negotiations: Annotated[bool, Form()] = False,
    territory_development: Annotated[bool, Form()] = False,
    launches: Annotated[bool, Form()] = False,
    operations_management: Annotated[bool, Form()] = False,
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
    confirm_duplicate: Annotated[bool, Form()] = False,
) -> Response:
    values: dict[str, object] = {
        "version": version,
        "position": position,
        "organization_label": organization_label,
        "industry": industry,
        "started_at": started_at,
        "ended_at": ended_at,
        "project_types": project_types,
        "responsibility_level": responsibility_level,
        "team_size_max": team_size_max,
        "project_geographies": project_geographies,
        "contractor_management": contractor_management,
        "negotiations": negotiations,
        "territory_development": territory_development,
        "launches": launches,
        "operations_management": operations_management,
        "store_private": store_private,
        "use_for_ai_analysis": use_for_ai_analysis,
        "use_in_scoring": use_in_scoring,
        "use_in_draft": use_in_draft,
        "send_externally": send_externally,
        "use_in_signature": use_in_signature,
        "publish_publicly": publish_publicly,
        "confirm_duplicate": confirm_duplicate,
    }
    errors: dict[str, str] = {}
    create_payload = experience_payload_from_form(values, errors)
    duplicate: dict[str, object] | None = None
    if create_payload is not None:
        update_values = create_payload.model_dump()
        update_values.pop("verified", None)
        try:
            await update_experience(
                experience_id,
                CandidateExperienceUpdate(version=version, **update_values),
                request,
                session,
                confirm_duplicate=confirm_duplicate,
            )
        except HTTPException as exc:
            await session.rollback()
            errors["_form"] = http_exception_message(exc)
            if (
                isinstance(exc.detail, dict)
                and exc.detail.get("code") == "duplicate_candidate_experience"
            ):
                duplicate = exc.detail
    if errors:
        key = str(experience_id)
        request.state.experience_edits = {key: values}
        request.state.experience_edit_errors = {key: errors}
        request.state.experience_edit_duplicates = {key: duplicate}
        request.state.open_experience = key
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response
    return RedirectResponse(
        "/candidate-profile?experience_notice=updated#experiences", status_code=303
    )


@router.post("/candidate-profile/experiences/{experience_id}/delete")
async def remove_experience(
    experience_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    confirm_delete: Annotated[str, Form()] = "",
) -> Response:
    if confirm_delete != "yes":
        request.state.experience_action_error = (
            "Удаление отменено: сначала подтвердите удаление именно этой записи."
        )
        request.state.open_experience = str(experience_id)
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response
    try:
        await delete_experience(experience_id, version, request, session)
    except HTTPException as exc:
        await session.rollback()
        request.state.experience_action_error = http_exception_message(exc)
        request.state.open_experience = str(experience_id)
        response = await candidate_profile_page(request, session)
        response.status_code = exc.status_code
        return response
    return RedirectResponse(
        "/candidate-profile?experience_notice=deleted#experiences", status_code=303
    )


@router.post("/candidate-profile/skills")
async def save_skill(
    request: Request,
    session: DbSession,
    name: Annotated[str, Form()],
    skill_group: Annotated[SkillGroup, Form()],
    actual_level: Annotated[SkillLevel, Form()],
    duration_months: Annotated[int | None, Form()] = None,
    evidence: Annotated[str, Form()] = "",
    verified_results: Annotated[str, Form()] = "",
    limitations: Annotated[str, Form()] = "",
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await create_skill(
        CandidateSkillCreate(
            name=name,
            skill_group=skill_group,
            actual_level=actual_level,
            duration_months=duration_months,
            evidence=evidence or None,
            verified_results=verified_results or None,
            limitations=limitations or None,
            verified=False,
            store_private=store_private,
            use_for_ai_analysis=use_for_ai_analysis,
            use_in_scoring=use_in_scoring,
            use_in_draft=use_in_draft,
            send_externally=send_externally,
            use_in_signature=use_in_signature,
            publish_publicly=publish_publicly,
        ),
        request,
        session,
    )
    return RedirectResponse("/candidate-profile#skills", status_code=303)


@router.post("/candidate-profile/skills/{skill_id}/edit")
async def edit_skill(
    skill_id: UUID,
    request: Request,
    session: DbSession,
    version: Annotated[int, Form()],
    name: Annotated[str, Form()],
    skill_group: Annotated[SkillGroup, Form()],
    actual_level: Annotated[SkillLevel, Form()],
    duration_months: Annotated[int | None, Form()] = None,
    evidence: Annotated[str, Form()] = "",
    verified_results: Annotated[str, Form()] = "",
    limitations: Annotated[str, Form()] = "",
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
) -> Response:
    key = str(skill_id)
    values: dict[str, object] = {
        "version": version,
        "name": name,
        "skill_group": skill_group.value,
        "actual_level": actual_level.value,
        "duration_months": duration_months if duration_months is not None else "",
        "evidence": evidence,
        "verified_results": verified_results,
        "limitations": limitations,
        "store_private": store_private,
        "use_for_ai_analysis": use_for_ai_analysis,
        "use_in_scoring": use_in_scoring,
        "use_in_draft": use_in_draft,
        "send_externally": send_externally,
        "use_in_signature": use_in_signature,
        "publish_publicly": publish_publicly,
    }
    errors: dict[str, str] = {}
    try:
        complete = CandidateSkillCreate(
            name=name,
            skill_group=skill_group,
            actual_level=actual_level,
            duration_months=duration_months,
            evidence=evidence or None,
            verified_results=verified_results or None,
            limitations=limitations or None,
            verified=False,
            store_private=store_private,
            use_for_ai_analysis=use_for_ai_analysis,
            use_in_scoring=use_in_scoring,
            use_in_draft=use_in_draft,
            send_externally=send_externally,
            use_in_signature=use_in_signature,
            publish_publicly=publish_publicly,
        )
    except ValidationError as exc:
        errors.update(pydantic_form_errors(exc))
    if not errors:
        update_values = complete.model_dump(
            exclude={"verified", "implemented_project_fact_ids"}
        )
        try:
            await update_skill(
                skill_id,
                CandidateSkillUpdate(version=version, **update_values),
                request,
                session,
            )
        except HTTPException as exc:
            await session.rollback()
            errors["_form"] = http_exception_message(exc)
    if errors:
        request.state.skill_edits = {key: values}
        request.state.skill_edit_errors = {key: errors}
        request.state.open_skill = key
        response = await candidate_profile_page(request, session)
        response.status_code = 422
        return response
    return RedirectResponse(
        "/candidate-profile?skill_notice=updated#skills", status_code=303
    )


@router.post("/candidate-profile/strengths")
async def save_strength(
    request: Request,
    session: DbSession,
    strength_type: Annotated[StrengthType, Form()],
    text: Annotated[str, Form()],
    evidence: Annotated[str, Form()] = "",
    priority: Annotated[int, Form()] = 100,
    store_private: Annotated[bool, Form()] = False,
    use_for_ai_analysis: Annotated[bool, Form()] = False,
    use_in_scoring: Annotated[bool, Form()] = False,
    use_in_draft: Annotated[bool, Form()] = False,
    send_externally: Annotated[bool, Form()] = False,
    use_in_signature: Annotated[bool, Form()] = False,
    publish_publicly: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await create_strength(
        CandidateStrengthCreate(
            strength_type=strength_type,
            text=text,
            evidence=evidence or None,
            priority=priority,
            verified=False,
            store_private=store_private,
            use_for_ai_analysis=use_for_ai_analysis,
            use_in_scoring=use_in_scoring,
            use_in_draft=use_in_draft,
            send_externally=send_externally,
            use_in_signature=use_in_signature,
            publish_publicly=publish_publicly,
        ),
        request,
        session,
    )
    return RedirectResponse("/candidate-profile#strengths", status_code=303)


@router.get("/candidate-profile/fact-pack-preview", response_class=HTMLResponse)
async def fact_pack_partial(
    request: Request,
    session: DbSession,
    purpose: FactPackPurpose = FactPackPurpose.AI_ANALYSIS,
) -> HTMLResponse:
    pack = await preview_fact_pack(session, purpose)
    return templates.TemplateResponse(
        request=request,
        name="partials/fact_pack.html",
        context={"pack": pack},
    )
