"""Conservative deterministic parsing for Russian owner queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ParsedSearchTask:
    language: str = "unknown"
    country: str | None = None
    region: str | None = None
    industry: str | None = None
    focus: str | None = None
    explicit_limit: int | None = None
    direct_target: str | None = None


ANALYZE_MARKERS = (
    "проанализируй",
    "проанализировать",
    "изучи компанию",
    "исследуй компанию",
    "проверь компанию",
    "analyze ",
    "analyse ",
    "research company",
    "check company",
)
ANALYZE_TARGET_PATTERN = re.compile(
    r"^(?:проанализируй|проанализировать|изучи|исследуй|проверь|analyze|analyse|research|check)"
    r"\s+(?:компанию|компания|company)?\s*[«\"']?([^,;\n»\"']{2,200})",
    re.I,
)


COUNTRIES = {
    "росси": "Russia",
    "мексик": "Mexico",
    "серби": "Serbia",
    "таиланд": "Thailand",
    "черногори": "Montenegro",
    "бразили": "Brazil",
    "аргентин": "Argentina",
    "оаэ": "United Arab Emirates",
    "russia": "Russia",
    "mexico": "Mexico",
    "serbia": "Serbia",
    "thailand": "Thailand",
    "montenegro": "Montenegro",
    "brazil": "Brazil",
    "argentina": "Argentina",
    "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates",
}
REGIONS = {"краснодар": "Краснодар", "krasnodar": "Краснодар"}
INDUSTRIES = {
    "логист": "Logistics",
    "прокат автомобилей": "Car Rental",
    "аренд автомобилей": "Car Rental",
    "строитель": "Construction",
    "travel tech": "Travel Tech",
    "туризм": "Travel Tech",
    "ai-компан": "AI / Technology",
    "ии-компан": "AI / Technology",
    "logistics": "Logistics",
    "car rental": "Car Rental",
    "construction": "Construction",
    "tourism": "Travel Tech",
    "ai compan": "AI / Technology",
}
FOCUSES = {
    "business development": "Business Development",
    "развити бизнеса": "Business Development",
    "expansion": "Expansion",
    "экспанси": "Expansion",
    "operations": "Operations",
    "операцион": "Operations",
    "ai automation": "AI Automation",
    "автоматизац": "AI Automation",
    "business expansion": "Expansion",
    "operational": "Operations",
}
URL_PATTERN = re.compile(
    r"(?:(?:https?://)?(?:www\.)?)[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[^\s]*)?", re.I
)


def _first_match(text: str, mapping: dict[str, str]) -> str | None:
    return next((value for marker, value in mapping.items() if marker in text), None)


def _direct_target(query: str) -> str | None:
    match = URL_PATTERN.search(query)
    if not match:
        return None
    target = match.group(0).rstrip(".,;:)")
    parsed = urlparse(target if "://" in target else f"https://{target}")
    return parsed.geturl() if parsed.hostname else None


def detect_query_language(query: str) -> str:
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", query))
    has_latin = bool(re.search(r"[A-Za-z]", query))
    if has_cyrillic and has_latin:
        return "mixed"
    if has_cyrillic:
        return "ru"
    if has_latin:
        return "en"
    return "unknown"


def parse_search_query(query: str) -> ParsedSearchTask:
    normalized = " ".join(query.lower().split())
    limit_match = re.search(r"(?:найди|подбери|find|select|suggest)\s+(\d{1,2})\b", normalized)
    explicit_limit = int(limit_match.group(1)) if limit_match else None
    if explicit_limit is not None and not 1 <= explicit_limit <= 20:
        explicit_limit = None
    return ParsedSearchTask(
        language=detect_query_language(query),
        country=_first_match(normalized, COUNTRIES),
        region=_first_match(normalized, REGIONS),
        industry=_first_match(normalized, INDUSTRIES),
        focus=_first_match(normalized, FOCUSES),
        explicit_limit=explicit_limit,
        direct_target=_direct_target(query),
    )


def infer_search_task_intent(query: str) -> tuple[str, str | None]:
    """Infer the owner-facing task mode without rewriting the original query."""

    parsed = parse_search_query(query)
    normalized = " ".join(query.casefold().split())
    analyze_requested = any(marker in normalized for marker in ANALYZE_MARKERS)
    if not analyze_requested and parsed.direct_target:
        without_url = URL_PATTERN.sub("", normalized).strip(" ,.;:-")
        analyze_requested = not without_url
    if not analyze_requested:
        return "find_companies", None
    if parsed.direct_target:
        return "analyze_company", parsed.direct_target
    match = ANALYZE_TARGET_PATTERN.search(query.strip())
    target = match.group(1).strip() if match else query.strip()
    return "analyze_company", target[:1000]
