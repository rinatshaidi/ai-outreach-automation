"""Deterministic text extraction and conservative research candidates."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from app.modules.opportunities.schemas import OpportunitySignalType, OpportunityType


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []
        self.mailto_links: list[str] = []
        self.public_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.lower().startswith("mailto:"):
                self.mailto_links.append(href[7:].split("?", maxsplit=1)[0].strip().lower())
            elif href and not href.lower().startswith(("javascript:", "tel:", "#")):
                self.public_links.append(href.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self.parts.append(cleaned)


@dataclass(frozen=True)
class FactCandidate:
    fact_type: str
    value: str
    exact_fragment: str
    confidence: float


@dataclass(frozen=True)
class SignalCandidate:
    signal_type: OpportunitySignalType
    title: str
    description: str
    exact_fragment: str
    confidence: float


@dataclass(frozen=True)
class HypothesisCandidate:
    title: str
    description: str
    rationale: str
    confidence: float
    risks: list[str]


@dataclass(frozen=True)
class ExtractedResearch:
    text: str
    language: str
    facts: list[FactCandidate]
    signals: list[SignalCandidate]
    opportunity_types: list[OpportunityType]
    hypotheses: list[HypothesisCandidate]
    public_emails: list[str]
    public_links: list[str]


SIGNAL_RULES: tuple[tuple[OpportunitySignalType, OpportunityType, str, tuple[str, ...]], ...] = (
    (
        OpportunitySignalType.OPEN_VACANCY,
        OpportunityType.OPEN_VACANCY,
        "Public vacancy or careers signal",
        ("vacancy", "job opening", "we are hiring", "ваканси"),
    ),
    (
        OpportunitySignalType.MARKET_ENTRY,
        OpportunityType.MARKET_ENTRY,
        "Market-entry signal",
        ("new market", "market entry", "выход на рынок", "новый рынок"),
    ),
    (
        OpportunitySignalType.INTERNATIONAL_EXPANSION,
        OpportunityType.BUSINESS_EXPANSION,
        "International expansion signal",
        ("international expansion", "expand internationally", "международн", "экспанси"),
    ),
    (
        OpportunitySignalType.OFFICE_OPENING,
        OpportunityType.BUSINESS_EXPANSION,
        "Office-opening signal",
        ("new office", "opening an office", "открытие офиса", "новый офис"),
    ),
    (
        OpportunitySignalType.PRODUCT_LAUNCH,
        OpportunityType.NEW_PRODUCT_OR_DIRECTION,
        "Product-launch signal",
        ("product launch", "launching", "new product", "запуск продукта", "новый продукт"),
    ),
    (
        OpportunitySignalType.AI_ADOPTION,
        OpportunityType.AI_ADOPTION,
        "AI-adoption signal",
        ("artificial intelligence", " ai ", "llm", "machine learning", "искусственн"),
    ),
    (
        OpportunitySignalType.PROCESS_AUTOMATION,
        OpportunityType.PROCESS_AUTOMATION,
        "Process-automation signal",
        ("process automation", "workflow automation", "автоматизац"),
    ),
    (
        OpportunitySignalType.PARTNERSHIP_PROGRAM,
        OpportunityType.BUSINESS_EXPANSION,
        "Partnership-program signal",
        ("partner program", "partnership program", "партнерская программ", "партнёрская программ"),
    ),
)


def parse_document(body: bytes, content_type: str) -> tuple[str, list[str], list[str]]:
    decoded = body.decode("utf-8", errors="replace")
    if content_type == "text/plain":
        text = " ".join(decoded.split())[:50_000]
        return text, [], []
    parser = VisibleTextParser()
    parser.feed(decoded)
    return (
        " ".join(parser.parts)[:50_000],
        list(dict.fromkeys(parser.mailto_links)),
        list(dict.fromkeys(parser.public_links)),
    )


def detect_language(text: str) -> str:
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cyrillic > latin:
        return "ru"
    if latin:
        return "en"
    return "unknown"


def matching_fragment(text: str, keyword: str, radius: int = 180) -> str:
    lowered = text.casefold()
    index = lowered.find(keyword.casefold())
    if index < 0:
        return text[: min(len(text), radius * 2)]
    start = max(0, index - radius)
    end = min(len(text), index + len(keyword) + radius)
    return text[start:end]


def extract_research(body: bytes, content_type: str) -> ExtractedResearch:
    text, public_emails, public_links = parse_document(body, content_type)
    if not text:
        raise ValueError("No visible research text was extracted")
    language = detect_language(text)
    facts = [
        FactCandidate(
            fact_type="company_activity",
            value=text[:1000],
            exact_fragment=text[:1000],
            confidence=0.65,
        )
    ]
    scale_patterns = (
        r"\b(?:over|more than|more than)\s+\d[\d, ]*\s+(?:employees|customers|clients|countries)\b",
        r"\b\d[\d, ]*\+?\s+(?:employees|customers|clients|countries|offices|markets)\b",
        r"\b(?:более|свыше)\s+\d[\d ]*\s+(?:сотрудник|клиент|стран|рынк)",
    )
    for pattern in scale_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            fragment = matching_fragment(text, match.group(0), radius=220)
            facts.append(
                FactCandidate(
                    fact_type="company_scale",
                    value=fragment,
                    exact_fragment=fragment,
                    confidence=0.75,
                )
            )
            break
    signals: list[SignalCandidate] = []
    opportunity_types: list[OpportunityType] = []
    lowered = f" {text.casefold()} "
    for signal_type, opportunity_type, title, keywords in SIGNAL_RULES:
        keyword = next((item for item in keywords if item.casefold() in lowered), None)
        if keyword is None:
            continue
        fragment = matching_fragment(text, keyword)
        signals.append(
            SignalCandidate(
                signal_type=signal_type,
                title=title,
                description=f"Rule-based extraction found a public {signal_type.value} indicator.",
                exact_fragment=fragment,
                confidence=0.6,
            )
        )
        opportunity_types.append(opportunity_type)

    hypotheses: list[HypothesisCandidate] = []
    if any(
        item in opportunity_types
        for item in {OpportunityType.MARKET_ENTRY, OpportunityType.BUSINESS_EXPANSION}
    ):
        hypotheses.append(
            HypothesisCandidate(
                title="Market or operational launch coordination",
                description=(
                    "The company may need coordination of launch workstreams, "
                    "partners and local operations."
                ),
                rationale=(
                    "This is inferred from public expansion language and is not presented "
                    "as a confirmed internal need."
                ),
                confidence=0.45,
                risks=["The source confirms activity, not an internal hiring or consulting need"],
            )
        )
    if any(
        item in opportunity_types
        for item in {OpportunityType.AI_ADOPTION, OpportunityType.PROCESS_AUTOMATION}
    ):
        hypotheses.append(
            HypothesisCandidate(
                title="AI or workflow implementation support",
                description=(
                    "The company may benefit from scoped automation discovery "
                    "or implementation coordination."
                ),
                rationale=(
                    "This is a cautious hypothesis derived from public AI or automation language."
                ),
                confidence=0.4,
                risks=[
                    "Public technology language may describe a product rather than "
                    "an internal operational need"
                ],
            )
        )
    if not hypotheses:
        hypotheses.append(
            HypothesisCandidate(
                title="General competence-fit review",
                description=(
                    "Review the company activity for realistic management, operations "
                    "or project contribution."
                ),
                rationale=(
                    "No strong timing signal was found; analysis remains allowed under "
                    "GENERAL_COMPETENCE_FIT."
                ),
                confidence=0.25,
                risks=["No explicit public need or timing signal was detected"],
            )
        )
        opportunity_types.append(OpportunityType.GENERAL_COMPETENCE_FIT)

    return ExtractedResearch(
        text=text,
        language=language,
        facts=facts,
        signals=signals,
        opportunity_types=list(dict.fromkeys(opportunity_types)),
        hypotheses=hypotheses,
        public_emails=public_emails,
        public_links=public_links,
    )
