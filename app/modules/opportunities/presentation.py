"""Owner-facing wording for the current Local Pilot wave.

The source records remain unchanged.  This module translates the researched pilot
material into concise product language and deliberately does not invent new facts.
"""

# ruff: noqa: E501 -- long Russian copy is intentionally kept as readable content records.

from __future__ import annotations

import re
from typing import Any

PILOT_PRESENTATIONS_RU: dict[str, dict[str, Any]] = {
    "Airalo": {
        "country": "Сингапур",
        "industry": "Технологии для путешествий и глобальная связь",
        "description": "Международная компания, предоставляющая цифровые решения связи для путешественников через технологию eSIM.",
        "current_activity": "Компания развивает глобальную eSIM-платформу и международную партнёрскую модель. Конкретная актуальная потребность в профиле владельца пока не подтверждена.",
        "conclusion": "Стоит рассмотреть",
        "why": "Международная компания, где управленческий опыт может быть полезен в развитии партнёрств, операций и межфункциональных проектов.",
        "scenario": "Развитие бизнеса / международные операции",
        "fit": "Сильное совпадение — развитие бизнеса, переговоры, запуски и координация сложных процессов. ИИ-автоматизация может быть дополнительным усилителем.",
        "upside": "Глобальная партнёрская модель и распределённые процессы хорошо проверяют переносимость управленческого опыта.",
        "risk": "Не подтверждена конкретная потребность компании именно в таком профиле прямо сейчас.",
        "scenarios": [
            (
                "Развитие бизнеса и партнёрств",
                "Координация партнёрского процесса между рынками и командами.",
                "Высокая реалистичность",
            ),
            (
                "Управление операционным проектом",
                "Структурирование запуска или улучшения повторяемого международного процесса.",
                "Средняя реалистичность",
            ),
            (
                "Автоматизация отдельного рабочего процесса",
                "Небольшая диагностика процесса и управляемый прототип с ручным контролем.",
                "Дополнительный сценарий",
            ),
        ],
    },
    "Bolt": {
        "country": "Эстония",
        "industry": "Мобильность, доставка и платформенные операции",
        "description": "Международная технологическая платформа в сфере городской мобильности, доставки и транспортных услуг.",
        "conclusion": "Стоит рассмотреть в первую очередь",
        "why": "Есть прямое совпадение с развитием территорий, запусками, партнёрами и операционным управлением.",
        "scenario": "Развитие территорий / запуск новых рынков",
        "fit": "Сильное совпадение — запуски, развитие территорий, подрядчики, переговоры и исполнение сложных проектов. Отраслевой опыт в мобильности не подтверждён.",
        "upside": "Официальная вакансия руководителя развития подтверждает реальную потребность в задачах роста и запуска.",
        "risk": "Текущая вакансия предполагает полную занятость, гибридный формат и работу в Таллине; нужен честный разбор пробела в отраслевом опыте.",
        "scenarios": [
            (
                "Руководство запуском",
                "Перевод центральных стандартов в план локального запуска и контроль исполнения.",
                "Высокая реалистичность",
            ),
            (
                "Операционное управление развитием",
                "Координация партнёров, рисков и процессов при росте рынка.",
                "Высокая реалистичность",
            ),
            (
                "Автоматизация отчётности запуска",
                "Упрощение одного повторяемого операционного процесса.",
                "Дополнительный сценарий",
            ),
        ],
    },
    "n8n": {
        "country": "Германия",
        "industry": "Оркестрация ИИ и автоматизация процессов",
        "description": "Платформа для автоматизации рабочих процессов, интеграции сервисов и создания управляемых ИИ-сценариев.",
        "conclusion": "Стоит рассмотреть как проектную возможность",
        "why": "Компания напрямую связана с автоматизацией рабочих процессов и позволяет проверить честное ИИ-позиционирование без завышения технического уровня.",
        "scenario": "Проектная ИИ-автоматизация / автоматизация на Python",
        "fit": "Сильное совпадение — понимание бизнес-процессов и практические проекты автоматизации. Среднее — Python и интеграции. Слабое — глубокая разработка старшего уровня.",
        "upside": "Основной продукт компании совпадает с развиваемым направлением ИИ-автоматизации и практикой n8n.",
        "risk": "Нельзя позиционировать кандидата как старшего ИИ- или Python-инженера; подходящая вакансия и география найма пока не подтверждены.",
        "scenarios": [
            (
                "Диагностика и прототип автоматизации",
                "Перевести реальный бизнес-процесс в контролируемый прототип с ручным подтверждением.",
                "Средняя реалистичность",
            ),
            (
                "Координация проекта автоматизации",
                "Соединить бизнес-заказчика, рабочий процесс и техническую реализацию.",
                "Средняя реалистичность",
            ),
            (
                "Автоматизация операционных процессов",
                "Улучшить отдельный внутренний или клиентский процесс.",
                "Требует подтверждения потребности",
            ),
        ],
    },
    "what3words": {
        "country": "Великобритания",
        "industry": "Геолокационные технологии и международные партнёрства",
        "description": "Геолокационная платформа, присваивающая небольшим участкам поверхности уникальные комбинации из трёх слов.",
        "conclusion": "Стоит рассмотреть без привязки к вакансии",
        "why": "Международные партнёрства и клиентские операции позволяют перенести имеющийся опыт в небольшое проектное предложение.",
        "scenario": "Партнёрские операции / консалтинг",
        "fit": "Сильное совпадение — партнёры, межфункциональная координация и развитие бизнеса. ИИ-автоматизация уместна только как инструмент улучшения процесса.",
        "upside": "Можно предложить ограниченную диагностику процесса подключения партнёров без предположения о найме.",
        "risk": "Подходящая вакансия и явная внутренняя потребность не подтверждены; общее предложение о работе будет слабым.",
        "scenarios": [
            (
                "Операционная работа с партнёрами",
                "Карта процесса подключения партнёров и точек потери времени между командами.",
                "Средняя реалистичность",
            ),
            (
                "Проектное управление",
                "Координация небольшого межфункционального улучшения.",
                "Средняя реалистичность",
            ),
            (
                "Автоматизация рабочего процесса",
                "Прототип автоматизации одного подтверждённого узкого места.",
                "Только после предварительного анализа",
            ),
        ],
    },
    "Einride": {
        "country": "Швеция",
        "industry": "Электрические и автономные грузовые технологии",
        "description": "Технологическая компания, развивающая электрические и автономные решения для грузовых перевозок.",
        "conclusion": "Стоит исследовать глубже",
        "why": "Новая отрасль хорошо проверяет перенос инфраструктурного и операционного опыта в технологичный бизнес.",
        "scenario": "Развёртывание инфраструктуры / операционное управление",
        "fit": "Сильное совпадение — инфраструктурные запуски, подрядчики, риски и операционная координация. Слабое — прямой опыт автономных грузовых перевозок.",
        "upside": "Физическая инфраструктура, программное обеспечение и операции требуют межфункционального управления внедрением.",
        "risk": "Нет подтверждённого опыта в электрическом и автономном грузовом транспорте; нельзя заявлять отраслевую экспертизу.",
        "scenarios": [
            (
                "Управление проектом внедрения",
                "Структурировать участников, риски и этапы ограниченного внедрения.",
                "Средняя реалистичность",
            ),
            (
                "Эксплуатация инфраструктуры",
                "Координация площадок, партнёров и запуска физической инфраструктуры.",
                "Средняя реалистичность",
            ),
            (
                "Лёгкая автоматизация",
                "Автоматизация части контроля внедрения или отчётности.",
                "Дополнительный сценарий",
            ),
        ],
    },
    "Banco Plata": {
        "country": "Мексика",
        "industry": "Финтех и цифровые банковские услуги",
        "description": "Регулируемая мексиканская финансовая организация, развивающая цифровые банковские и кредитные продукты.",
        "conclusion": "Стоит рассмотреть после проверки сценария сотрудничества",
        "why": "Banco Plata быстро развивает цифровые финансовые продукты в Мексике. Управленческий опыт, запуски и развитие бизнеса выглядят релевантнее глубокого технического позиционирования.",
        "scenario": "Проектное управление / операционное управление / развитие бизнеса",
        "fit": "Сильное совпадение — управление проектами, развитие бизнеса, координация запусков и сложных процессов. ИИ-автоматизация может использоваться как дополнительный инструмент.",
        "upside": "Рост компании и развитие новых финансовых направлений создают реалистичный контекст для проектного и операционного вклада.",
        "risk": "Конкретная потребность в таком профиле и именной получатель обращения пока не подтверждены.",
        "current_signals": [
            "Компания получила банковскую авторизацию в Мексике и начала банковские операции.",
            "Официальный карьерный сайт показывает активный набор сотрудников.",
            "Олег Тиньков указан как советник высшего руководства, а не как основатель Banco Plata.",
        ],
        "scenarios": [
            (
                "Координация проекта развития",
                "Структурировать рабочие потоки, риски и взаимодействие участников при развитии нового направления.",
                "Средняя реалистичность",
            ),
            (
                "Операционное управление / развитие бизнеса",
                "Поддержать развитие партнёрств или операционного процесса с понятными контрольными точками.",
                "Средняя реалистичность",
            ),
            (
                "Автоматизация отдельного процесса",
                "После предварительного анализа предложить небольшой контролируемый прототип автоматизации.",
                "Дополнительный сценарий",
            ),
        ],
    },
}


def pilot_presentation(company_name: str, locale: str) -> dict[str, Any]:
    if locale == "ru":
        return PILOT_PRESENTATIONS_RU.get(company_name, {})
    return {}


POSITIONING_LABELS_RU = {
    "business_first": "Бизнес-профиль",
    "ai_first": "ИИ-профиль",
    "hybrid": "Бизнес + ИИ",
}

POSITIONING_LABELS_EN = {
    "business_first": "Business profile",
    "ai_first": "AI profile",
    "hybrid": "Business + AI",
}

STATUS_LABELS_RU = {
    "decision_pending": "Ожидает решения",
    "ACTIONABLE_OPPORTUNITY": "Готово к решению",
    "COMPANY_CANDIDATE": "Кандидат для исследования",
    "CONTACT_FOUND": "Контакт найден",
    "CONTACT_PARTIAL": "Контакт требует проверки",
    "CONTACT_RESEARCH_REQUIRED": "Требуется поиск контакта",
    "NO_VALID_CONTACT": "Нет проверенного контакта",
    "VERIFIED_CONTACT": "Контакт проверен",
    "READY_FOR_LOCAL_PILOT": "Готово к локальному пилоту",
    "business_first": "Бизнес-профиль",
    "ai_first": "ИИ-профиль",
    "hybrid": "Бизнес + ИИ",
    "ready": "Готово к проверке",
    "blocked": "Заблокировано",
    "pending": "Ожидает решения",
    "proposed": "Предложено для проверки",
    "verified": "Подтверждено",
    "draft_ready": "Черновик готов",
    "approved_for_outreach": "Решение писать принято",
    "deeper_research": "Исследовать глубже",
    "not_relevant": "Не интересно",
    "completed": "Завершено",
    "resolving_company": "Определение компании",
    "company_resolved": "Компания определена",
    "research_completed": "Исследование завершено",
    "opportunity_created": "Возможность сформирована",
    "scoring_completed": "Оценка завершена",
    "queued_for_execution": "Ожидает обработки",
    "failed": "Ошибка",
}

STATUS_LABELS_EN = {
    "decision_pending": "Awaiting decision",
    "ACTIONABLE_OPPORTUNITY": "Ready for decision",
    "COMPANY_CANDIDATE": "Research candidate",
    "CONTACT_FOUND": "Contact found",
    "CONTACT_PARTIAL": "Contact needs verification",
    "CONTACT_RESEARCH_REQUIRED": "Contact research required",
    "NO_VALID_CONTACT": "No verified contact",
    "VERIFIED_CONTACT": "Verified contact",
    "READY_FOR_LOCAL_PILOT": "Ready for local pilot",
    "business_first": "Business profile",
    "ai_first": "AI profile",
    "hybrid": "Business + AI",
    "ready": "Ready for review",
    "blocked": "Blocked",
    "pending": "Awaiting decision",
    "proposed": "Proposed for review",
    "verified": "Verified",
    "draft_ready": "Draft ready",
    "approved_for_outreach": "Outreach decision recorded",
    "deeper_research": "Research deeper",
    "not_relevant": "Not interested",
    "completed": "Completed",
    "resolving_company": "Resolving company",
    "company_resolved": "Company resolved",
    "research_completed": "Research completed",
    "opportunity_created": "Opportunity created",
    "scoring_completed": "Scoring completed",
    "queued_for_execution": "Queued for execution",
    "failed": "Failed",
}

PROFILE_TEXT_RU = {
    "Project Manager | Business Development | AI Automation": (
        "Руководитель проектов | Развитие бизнеса | ИИ-автоматизация"
    ),
    "AI Automation / Python Automation — собственные проекты": (
        "ИИ-автоматизация / автоматизация на Python — собственные проекты"
    ),
    "Independent Projects": "Собственные проекты",
    "AI Automation, Python Automation, Software Development": (
        "ИИ-автоматизация, автоматизация на Python, разработка программного обеспечения"
    ),
    "Project Manager": "Руководитель проектов",
    "Business Development": "Развитие бизнеса",
    "Operations": "Операционное управление",
    "Expansion": "Развитие территорий",
    "New Market Launch": "Запуск новых рынков",
    "AI Project Management": "Управление ИИ-проектами",
    "AI Automation": "ИИ-автоматизация",
    "Hybrid roles": "Гибридные роли",
    "technology": "технология",
    "skill": "навык",
    "project": "проект",
    "email": "электронная почта",
    "Mexico": "Мексика",
    "Singapore": "Сингапур",
    "Estonia": "Эстония",
    "Germany": "Германия",
    "United Kingdom": "Великобритания",
    "Sweden": "Швеция",
    "Russia": "Россия",
    "Computer vision": "Компьютерное зрение",
    "Computer vision / Artificial intelligence": "Компьютерное зрение / искусственный интеллект",
    "Artificial intelligence": "Искусственный интеллект",
    "Public company contact": "Официальный контакт компании",
    "Official company contact": "Официальный контакт компании",
    "Founder": "Основатель",
    "Official form": "Официальная форма",
    "Phone": "Телефон",
}

PROFILE_TEXT_EN = {
    "Русский — основной; английский — A2, развивающийся к B1": (
        "Russian is primary; English is A2 and progressing toward B1"
    ),
    "Руководитель проектов и специалист по развитию бизнеса с более чем 10-летним опытом управления инфраструктурными и коммерческими проектами, запуска объектов и новых направлений. Формирую команды, выстраиваю рабочие процессы, управляю подрядчиками, сроками, бюджетами и рисками. Развиваю практическое направление AI и Python-автоматизации и создаю собственные решения с использованием Python, FastAPI, PostgreSQL, Docker, n8n, API и LLM-инструментов.": (
        "Project manager and business development professional with more than 10 years of experience managing infrastructure and commercial projects, launching facilities and new directions. Builds teams and workflows and manages contractors, schedules, budgets, and risks. Currently develops practical AI and Python automation solutions using Python, FastAPI, PostgreSQL, Docker, n8n, APIs, and LLM tools."
    ),
    "Директор": "Director",
    "Заместитель директора / Руководитель управленческого уровня": (
        "Deputy Director / Senior Management Role"
    ),
    "Управление бизнесом, инфраструктурные и коммерческие проекты": (
        "Business management, infrastructure, and commercial projects"
    ),
    "Управление бизнесом, операционное управление, крупные проекты": (
        "Business management, operations, and large projects"
    ),
    "Участие в управлении крупной организацией, координация подразделений и команд, принятие управленческих решений, контроль сроков, ресурсов, рисков и результата": (
        "Contributed to managing a large organization, coordinating departments and teams, making management decisions, and controlling schedules, resources, risks, and outcomes."
    ),
    "Участие в управлении крупной организацией, координация подразделений и команд, принятие решений, контроль ресурсов, сроков и результата": (
        "Contributed to managing a large organization, coordinating departments and teams, making decisions, and controlling resources, schedules, and outcomes."
    ),
    "Самостоятельно веду проекты: постановка задачи, выбор решения, разработка, тестирование, интеграции, запуск MVP и дальнейшее улучшение.": (
        "Independently delivers projects from problem definition and solution selection through development, testing, integrations, MVP launch, and iteration."
    ),
    "Любая страна": "Any country",
    "Мексика": "Mexico",
    "Сингапур": "Singapore",
    "Эстония": "Estonia",
    "Германия": "Germany",
    "Великобритания": "United Kingdom",
    "Швеция": "Sweden",
    "Международная full-time роль — от 2000 USD в месяц; project-based, contract и consulting — по договорённости": (
        "International full-time role from USD 2,000 per month; project-based, contract, and consulting work by agreement."
    ),
}

BLOCKER_LABELS_RU = {
    "company_identity": "не подтверждена компания",
    "source_backed_description": "нет описания с проверенным источником",
    "opportunity_hypothesis": "не сформирована гипотеза возможности",
    "personal_fit_explained": "не объяснено соответствие профилю",
    "collaboration_scenarios": "не подтверждён сценарий сотрудничества",
    "feasibility_checked": "не проверены формат, география или язык",
    "vacancy_status_known": "не проверены вакансии",
    "main_risks_recorded": "не зафиксированы основные риски",
    "overall_recommendation": "нет итоговой рекомендации",
    "public_contact_path": "нет проверенного публичного контакта",
    "major_facts_have_provenance": "ключевые факты не привязаны к источникам",
    "research_confidence_sufficient": "недостаточная уверенность исследования",
}

BLOCKER_LABELS_EN = {
    "company_identity": "company identity is not confirmed",
    "source_backed_description": "no source-backed company description",
    "opportunity_hypothesis": "opportunity hypothesis is missing",
    "personal_fit_explained": "candidate fit is not explained",
    "collaboration_scenarios": "collaboration scenario is not confirmed",
    "feasibility_checked": "format, geography, or language is not checked",
    "vacancy_status_known": "vacancy status is not checked",
    "main_risks_recorded": "main risks are not recorded",
    "overall_recommendation": "final recommendation is missing",
    "public_contact_path": "verified public contact is missing",
    "major_facts_have_provenance": "key facts lack source provenance",
    "research_confidence_sufficient": "research confidence is insufficient",
}

FORMAT_LABELS_RU = {
    "full_time": "Полная занятость",
    "part_time": "Частичная занятость",
    "project_based": "Проектная работа",
    "contract": "Контракт",
    "consulting": "Консалтинг",
    "advisory": "Экспертная поддержка",
    "remote": "Удалённо",
    "hybrid": "Гибридно",
    "on_site": "На месте",
    "relocation": "Переезд",
    "temporary_relocation": "Временный переезд",
    "business_trips": "Командировки",
    "on-site": "На месте",
    "project-based": "Проектная работа",
}

FORMAT_LABELS_EN = {
    "full_time": "Full-time",
    "part_time": "Part-time",
    "project_based": "Project-based",
    "contract": "Contract",
    "consulting": "Consulting",
    "advisory": "Advisory",
    "remote": "Remote",
    "hybrid": "Hybrid",
    "on_site": "On-site",
    "relocation": "Relocation",
    "temporary_relocation": "Temporary relocation",
    "business_trips": "Business trips",
    "on-site": "On-site",
    "project-based": "Project-based",
}

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_WORD_RE = re.compile(r"\b[A-Za-z]{3,}\b")


def localized_status(value: str | None, locale: str) -> str:
    if not value:
        return "Не определено" if locale == "ru" else "Not determined"
    labels = STATUS_LABELS_RU if locale == "ru" else STATUS_LABELS_EN
    return labels.get(value, value.replace("_", " ").capitalize())


def localized_blockers(values: list[str], locale: str) -> list[str]:
    labels = BLOCKER_LABELS_RU if locale == "ru" else BLOCKER_LABELS_EN
    return [labels.get(value, localized_status(value, locale)) for value in values]


def localized_dynamic_text(value: str | None, locale: str) -> str:
    """Prevent raw synthesis in the wrong dashboard language.

    Proper names, URLs and outreach drafts are rendered separately by callers. Raw
    research remains untouched in storage and is available through source links.
    """

    if not value:
        return "Не удалось подтвердить" if locale == "ru" else "Not confirmed"
    if locale == "ru":
        if value in PROFILE_TEXT_RU:
            return PROFILE_TEXT_RU[value]
        # Never hide confirmed source text behind a technical localization
        # placeholder. New decision briefs are localized during synthesis;
        # legacy evidence remains visible in its original language.
        if LATIN_WORD_RE.search(value) and not CYRILLIC_RE.search(value):
            return value
        return value
    if value in PROFILE_TEXT_EN:
        return PROFILE_TEXT_EN[value]
    if CYRILLIC_RE.search(value):
        return value
    return value


def localized_values(values: list[str], locale: str) -> list[str]:
    labels = FORMAT_LABELS_RU if locale == "ru" else FORMAT_LABELS_EN
    return [labels.get(value, value.replace("_", " ").capitalize()) for value in values]
