"""Owner-facing, localized explanations for public contact paths."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.crm.models import Contact


@dataclass(frozen=True)
class ContactPresentation:
    category: str
    role_label: str
    guidance: str


def present_contact(contact: Contact, locale: str) -> ContactPresentation:
    """Explain whose contact this is without overstating public evidence."""

    ru = locale == "ru"
    role = (contact.decision_maker_role or "").casefold()
    raw_role = (contact.role or "").casefold()
    if contact.do_not_contact or "support" in raw_role:
        return ContactPresentation(
            category="support",
            role_label="Служба поддержки" if ru else "Customer support",
            guidance=(
                "Не использовать для outreach: это канал поддержки клиентов."
                if ru
                else "Do not use for outreach: this is a customer-support channel."
            ),
        )
    if role in {"founder", "co_founder", "ceo", "managing_director"}:
        return ContactPresentation(
            category="leadership",
            role_label=("Основатель / руководитель" if ru else "Founder / executive"),
            guidance=(
                "Личный публичный контакт руководителя. Подходит для короткого, "
                "предметного обращения."
                if ru
                else "Public executive contact. Suitable for a concise, specific approach."
            ),
        )
    if role in {"recruiter", "talent_acquisition", "hiring_manager"}:
        return ContactPresentation(
            category="hiring",
            role_label="HR / рекрутинг" if ru else "HR / recruitment",
            guidance=(
                "Канал найма. Предпочтителен для отклика на вакансию или карьерного обращения."
                if ru
                else "Hiring channel. Prefer it for a vacancy response or career outreach."
            ),
        )
    if role in {"head_of_business_development", "head_of_expansion", "country_manager"}:
        return ContactPresentation(
            category="business",
            role_label=(
                "Развитие бизнеса / партнёрства" if ru else "Business development / partnerships"
            ),
            guidance=(
                "Подходит для предложения проекта, партнёрства или развития направления."
                if ru
                else "Suitable for a project, partnership or expansion proposal."
            ),
        )
    if role in {"coo", "head_of_operations", "head_of_projects", "head_of_transformation"}:
        return ContactPresentation(
            category="operations",
            role_label="Операции / проекты" if ru else "Operations / projects",
            guidance=(
                "Подходит для конкретного операционного, проектного или "
                "автоматизационного предложения."
                if ru
                else "Suitable for a specific operations, project or automation proposal."
            ),
        )
    if "press" in raw_role or "media" in raw_role:
        return ContactPresentation(
            category="press",
            role_label="Пресс-служба" if ru else "Press office",
            guidance=(
                "Официальный медиа-канал; обычно не лучший адрес для первого outreach-обращения."
                if ru
                else "Official media channel; usually not the best first outreach recipient."
            ),
        )
    return ContactPresentation(
        category="public_company",
        role_label="Публичный контакт компании" if ru else "Public company contact",
        guidance=(
            "Это общий официальный канал. Персональный получатель не подтверждён — "
            "начните с него только при отсутствии более адресного контакта."
            if ru
            else (
                "This is a general official channel. No person is confirmed; use it only "
                "when no more targeted contact is available."
            )
        ),
    )
