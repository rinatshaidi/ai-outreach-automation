"""Presentation helpers for owner-facing opportunity pages."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

RISK_LABELS_RU = {
    "The source confirms activity, not an internal hiring or consulting need": (
        "Источник подтверждает деятельность компании, но не внутреннюю потребность "
        "в найме или консалтинге."
    ),
    "Public technology language may describe a product rather than an internal operational need": (
        "Публичное описание технологии может относиться к продукту компании, "
        "а не к её внутренней операционной потребности."
    ),
    "No explicit public need or timing signal was detected": (
        "Явная публичная потребность или сигнал подходящего момента не обнаружены."
    ),
    "A specific internal company need is not publicly confirmed.": (
        "Конкретная внутренняя потребность компании публично не подтверждена."
    ),
    "A specific internal need remains a cautious hypothesis for owner review.": (
        "Конкретная внутренняя потребность остаётся осторожной гипотезой "
        "и требует решения владельца."
    ),
    "Internal need is not confirmed": "Внутренняя потребность компании не подтверждена.",
    "Public information may be incomplete": "Публичная информация может быть неполной.",
    "Risk review required": "Требуется проверка рисков владельцем.",
    "Overall deterministic score is below the review threshold": (
        "Итоговая оценка ниже порога для дальнейшего рассмотрения."
    ),
}


def format_local_datetime(
    value: datetime | None,
    timezone_name: str = "Europe/Moscow",
    pattern: str = "%d.%m.%Y · %H:%M",
) -> str:
    """Render stored UTC timestamps in the configured owner timezone."""

    if value is None:
        return "—"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(ZoneInfo(timezone_name)).strftime(pattern)


def localized_risk(value: str | None, locale: str) -> str:
    """Localize only known system-generated risk wording; preserve evidence text."""

    if not value:
        return "Риск не определён." if locale == "ru" else "Risk not determined."
    if locale == "ru":
        return RISK_LABELS_RU.get(value.strip(), value)
    return value
