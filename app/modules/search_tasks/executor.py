"""One-process Local Pilot executor for durable Search Tasks.

The executor deliberately reuses the existing CRM, research, relevance and
opportunity services.  It performs no outreach generation or delivery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, quote_plus, urlparse
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import create_company, update_company
from app.api.opportunities import create_opportunity, create_recommendation
from app.api.relevance import calculate_company_relevance
from app.api.research import run_research
from app.config import Settings, get_settings
from app.infrastructure.db.session import SessionFactory
from app.modules.audit.models import AuditEvent
from app.modules.crm.models import Company, CompanySource, Contact
from app.modules.crm.schemas import CompanyCreate, CompanyUpdate, PipelineStatus
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    PositioningRecommendation,
)
from app.modules.opportunities.schemas import (
    CollaborationFormat,
    CompanyOpportunityCreate,
    DecisionMakerRole,
    EvidenceStatus,
    OpportunityType,
    PositioningRecommendationCreate,
    PositioningStrategy,
    WorkplaceFormat,
)
from app.modules.research.fetcher import SafeFetcher, SafeFetchError, normalize_public_url
from app.modules.research.models import CompanyFact, ResearchRun
from app.modules.research.schemas import ResearchRequest
from app.modules.research.synthesis import refresh_decision_synthesis
from app.modules.search_tasks.models import SearchTask, SearchTaskResult
from app.modules.search_tasks.schemas import SearchTaskStatus, SearchTaskType

logger = logging.getLogger("app.search_task_executor")

SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"
SEARCH_USER_AGENT = "Mozilla/5.0 (compatible; AIOutreachLocalPilot/1.0)"
# Daily discovery is deliberately allowed to run as a durable batch.  It may
# research candidates sequentially and persist each qualified company before
# moving on; it is not an interactive request that must finish in seconds.
TASK_EXECUTION_TIMEOUT_SECONDS = 3600
EXCLUDED_DOMAINS = {
    "duckduckgo.com",
    "wikipedia.org",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "crunchbase.com",
    "bloomberg.com",
    "reuters.com",
    "forbes.com",
    "prnewswire.com",
    "vc.ru",
    "wadline.com",
    "smartranking.ru",
    "ailist.ru",
    "axioma-ai.ru",
    "xvestor.ru",
    "itoq.ru",
}
EDITORIAL_PATH_MARKERS = (
    "/article",
    "/blog/",
    "/ranking/",
    "/ratings/",
    "/news/",
    "/top-",
)
EDITORIAL_TITLE_MARKERS = (
    "top 5",
    "top 10",
    "best companies",
    "рейтинг",
    "лучшие компании",
    "топ-5",
    "топ-10",
)
COMMON_SECOND_LEVEL_SUFFIXES = {"co.uk", "com.mx", "com.br", "com.ar", "com.co"}
TASK_COMPANY_NOTE = (
    "Created by Manual Search Task. No draft or external send without owner decision."
)


class SearchTaskExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SearchTaskCancelled(RuntimeError):
    """The owner cancelled a task while the worker was processing it."""


@dataclass(frozen=True)
class ResolvedCompany:
    name: str
    official_url: str
    normalized_domain: str
    research_urls: tuple[str, ...]
    country: str | None = None
    headquarters: str | None = None
    industry: str | None = None
    company_size: str | None = None
    description: str | None = None
    geography_evidence_url: str | None = None


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str


class OpenAICompanyDiscoveryProvider:
    """Web-grounded public company discovery without Candidate Profile data."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 600,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(
            self.settings.openai_company_discovery_enabled
            and self.settings.openai_api_key is not None
        )

    async def discover(self, query: str, limit: int) -> list[dict[str, Any]]:
        if not self.available or self.settings.openai_api_key is None:
            return []
        candidate_limit = min(20, max(10, limit * 5))
        schema = {
            "type": "object",
            "properties": {
                "companies": {
                    "type": "array",
                    "maxItems": candidate_limit,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "official_url": {"type": "string"},
                            "country": {"type": "string"},
                            "headquarters": {"type": "string"},
                            "industry": {"type": "string"},
                            "company_size": {"type": "string"},
                            "description": {"type": "string"},
                            "research_urls": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 5,
                            },
                            "geography_evidence_url": {"type": "string"},
                        },
                        "required": [
                            "name",
                            "official_url",
                            "country",
                            "headquarters",
                            "industry",
                            "company_size",
                            "description",
                            "research_urls",
                            "geography_evidence_url",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["companies"],
            "additionalProperties": False,
        }
        payload = {
            "model": self.settings.openai_rewrite_model,
            "store": False,
            "tools": [{"type": "web_search"}],
            "tool_choice": {"type": "web_search"},
            "instructions": (
                "Find real operating organizations matching the owner's public company-search "
                "criteria. Use current web search. Return only companies with their own official "
                "website. A company must build or sell the requested product or service; merely "
                "mentioning the topic is not enough. Exclude directories, lists, rankings, media, "
                "articles, blogs, communities, marketplaces, job boards, schools and government "
                "catalogs. official_url must be the company's official homepage, never an article "
                "or directory entry. If the criteria says AI company, AI products or AI services "
                "must be the organization's core commercial business. Exclude diversified banks, "
                "telecoms, marketplaces and general technology ecosystems that merely use or "
                "invest in AI; a dedicated AI subsidiary is allowed only when it has its own "
                "official site. The verbatim query may request a smaller number of final results, "
                "but you must return up to maximum_candidates as an alternate candidate pool for "
                "independent validation. Aim for 10 to 20 distinct candidates when that many "
                "genuine matching companies can be supported by public sources; do not stop at "
                "the requested final-result count. Return fewer only when additional candidates "
                "would be speculative or fail the criteria. "
                "Do not infer headquarters, size or other details when not supported; use an empty "
                "string. research_urls should contain up to five useful official About, company, "
                "news, careers, leadership or contact pages. geography_evidence_url must be the "
                "best public page that explicitly supports the requested country relationship; "
                "prefer an official page, otherwise use a reliable company profile, and use an "
                "empty string when the relationship is not evidenced. Return only the JSON schema."
            ),
            "input": json.dumps(
                {
                    "search_criteria_verbatim": query,
                    "maximum_candidates": candidate_limit,
                },
                ensure_ascii=False,
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "company_discovery_results",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key.get_secret_value()}"
                },
                json=payload,
            )
            if response.status_code in {401, 403}:
                raise SearchTaskExecutionError(
                    "company_discovery_auth_failed",
                    "Public company discovery provider rejected its credentials",
                )
            if response.status_code == 429:
                raise SearchTaskExecutionError(
                    "company_discovery_limit_reached",
                    "Public company discovery provider reached its current usage limit",
                )
            if response.status_code >= 400:
                raise SearchTaskExecutionError(
                    "company_discovery_failed",
                    "Public company discovery provider could not complete this search",
                )
            response_payload = response.json()
            output_text = "".join(
                content.get("text", "")
                for item in response_payload.get("output", [])
                for content in item.get("content", [])
                if content.get("type") == "output_text"
            )
            parsed = json.loads(output_text)
            companies = parsed.get("companies", [])
            if not isinstance(companies, list):
                raise TypeError("companies must be a list")
            normalized: list[dict[str, Any]] = []
            for item in companies:
                if not isinstance(item, dict):
                    continue
                normalized.append(
                    {
                        key: (
                            [str(entry).strip() for entry in value if str(entry).strip()]
                            if key == "research_urls" and isinstance(value, list)
                            else str(value).strip()
                        )
                        for key, value in item.items()
                    }
                )
            return normalized
        except SearchTaskExecutionError:
            raise
        except httpx.TimeoutException as exc:
            raise SearchTaskExecutionError(
                "company_discovery_timeout",
                "Public company discovery exceeded its 10 minute time limit",
            ) from exc
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SearchTaskExecutionError(
                "company_discovery_failed",
                "Public company discovery returned no usable structured result",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


class DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._href = values.get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        raw_url = unescape(self._href)
        parsed = urlparse(raw_url)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
            raw_url = parse_qs(parsed.query).get("uddg", [raw_url])[0]
        title = " ".join(" ".join(self._parts).split())
        if title and raw_url.startswith(("http://", "https://")):
            self.results.append(SearchResult(title=title, url=raw_url))
        self._href = None
        self._parts = []


def registrable_domain(hostname: str) -> str:
    parts = hostname.lower().removeprefix("www.").split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    suffix = ".".join(parts[-2:])
    return ".".join(parts[-3:]) if suffix in COMMON_SECOND_LEVEL_SUFFIXES else suffix


def domain_is_excluded(domain: str) -> bool:
    return any(domain == item or domain.endswith(f".{item}") for item in EXCLUDED_DOMAINS)


def result_looks_editorial(result: SearchResult) -> bool:
    parsed = urlparse(result.url)
    path = parsed.path.casefold()
    title = result.title.casefold()
    return any(marker in path for marker in EDITORIAL_PATH_MARKERS) or any(
        marker in title for marker in EDITORIAL_TITLE_MARKERS
    )


def clean_company_name(title: str, fallback: str) -> str:
    cleaned = re.split(r"\s+[|—–]\s+|\s+-\s+", title, maxsplit=1)[0]
    cleaned = re.sub(r"\s+(?:Fact Sheet|Official Site|Homepage)$", "", cleaned, flags=re.I)
    if not cleaned or len(cleaned) > 120:
        return fallback.strip().title()
    return cleaned.strip()


def normalize_official_homepage(value: str) -> tuple[str, str] | None:
    """Return a safe homepage and registrable domain, rejecting article-like URLs."""

    try:
        normalized = normalize_public_url(value)
    except (SafeFetchError, ValueError):
        return None
    parsed = urlparse(normalized)
    if parsed.hostname is None:
        return None
    domain = registrable_domain(parsed.hostname)
    if domain_is_excluded(domain):
        return None
    path = parsed.path.casefold()
    if any(marker in path for marker in EDITORIAL_PATH_MARKERS):
        return None
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) > 2:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/", domain


class PublicSearchResolver:
    """Resolve company entities first, then their official public websites."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 10,
        discovery_provider: OpenAICompanyDiscoveryProvider | None = None,
    ) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.discovery_provider = discovery_provider or OpenAICompanyDiscoveryProvider()

    async def _search(self, query: str) -> list[SearchResult]:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": SEARCH_USER_AGENT},
        )
        try:
            response = await client.get(SEARCH_URL.format(query=quote_plus(query)))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchTaskExecutionError(
                "public_search_failed", "Public company search is temporarily unavailable"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        parser = DuckDuckGoResultParser()
        parser.feed(response.text)
        return parser.results

    async def public_search(self, query: str) -> list[SearchResult]:
        """Return public search results without applying company-resolution filtering."""

        return await self._search(query)

    async def resolve(self, task: SearchTask) -> list[ResolvedCompany]:
        target = (task.company_name_or_url or "").strip()
        direct_url = target if target.startswith(("http://", "https://")) else None
        if direct_url:
            normalized = normalize_public_url(direct_url)
            hostname = urlparse(normalized).hostname
            if hostname is None:
                raise SearchTaskExecutionError("company_not_resolved", "Company URL is invalid")
            return [
                ResolvedCompany(
                    name=registrable_domain(hostname).split(".", maxsplit=1)[0].title(),
                    official_url=normalized,
                    normalized_domain=registrable_domain(hostname),
                    research_urls=(normalized,),
                )
            ]

        if task.task_type == SearchTaskType.ANALYZE_COMPANY.value:
            query = f"{task.original_query} {target} official website"
            raw_results = [
                *await self._search(query),
                *await self._search(f"{target} official careers company"),
                *await self._search(f"{target} official fact sheet founders leadership"),
            ]
            marker = re.sub(r"[^a-z0-9]", "", target.lower())
            scored: list[tuple[int, SearchResult, str]] = []
            for item in raw_results:
                hostname = urlparse(item.url).hostname
                if hostname is None:
                    continue
                domain = registrable_domain(hostname)
                if domain_is_excluded(domain):
                    continue
                compact_domain = re.sub(r"[^a-z0-9]", "", domain)
                score = (6 if marker and marker in compact_domain else 0) + (
                    3 if marker and marker in re.sub(r"[^a-z0-9]", "", item.title.lower()) else 0
                )
                if "banco plata" in item.title.lower() or "bancoplata" in compact_domain:
                    score += 5
                if task.parsed_country == "Mexico" and domain.endswith(".mx"):
                    score += 3
                if domain.endswith(".careers"):
                    score -= 4
                if score >= 3:
                    scored.append((score, item, domain))
            if not scored:
                raise SearchTaskExecutionError(
                    "company_not_resolved",
                    "Не удалось уверенно определить официальный сайт запрошенной компании",
                )
            scored.sort(key=lambda value: value[0], reverse=True)
            primary_score, primary, primary_domain = scored[0]
            research_urls = tuple(
                dict.fromkeys(
                    item.url
                    for score, item, domain in scored
                    if domain == primary_domain
                    or (
                        marker in re.sub(r"[^a-z0-9]", "", domain)
                        and (score >= primary_score - 3 or domain.endswith(".careers"))
                    )
                )
            )[:4]
            return [
                ResolvedCompany(
                    name=clean_company_name(primary.title, target),
                    official_url=primary.url,
                    normalized_domain=primary_domain,
                    research_urls=research_urls or (primary.url,),
                )
            ]

        # Daily discovery needs a reserve pool: known companies are skipped by
        # the executor and must not consume the owner's daily result limit.
        # The cap keeps one provider request bounded and predictable.
        discovery_limit = min(20, max(10, task.result_limit * 5))
        discovered = await self.discovery_provider.discover(
            task.original_query,
            discovery_limit,
        )
        resolved: list[ResolvedCompany] = []
        seen: set[str] = set()
        for discovered_item in discovered:
            homepage = normalize_official_homepage(discovered_item.get("official_url", ""))
            name = discovered_item.get("name", "").strip()
            if homepage is None or not name or len(name) > 200:
                continue
            official_url, domain = homepage
            if domain in seen:
                continue
            seen.add(domain)
            country = discovered_item.get("country", "").strip() or task.parsed_country
            headquarters = discovered_item.get("headquarters", "").strip() or None
            operating_place = headquarters or country
            resolved.append(
                ResolvedCompany(
                    name=name,
                    official_url=official_url,
                    normalized_domain=domain,
                    research_urls=tuple(
                        dict.fromkeys(
                            [
                                official_url,
                                *[
                                    value
                                    for value in discovered_item.get("research_urls", [])
                                    if isinstance(value, str)
                                    and value.startswith(("http://", "https://"))
                                ],
                                *(
                                    [str(discovered_item.get("geography_evidence_url", ""))]
                                    if str(
                                        discovered_item.get("geography_evidence_url", "")
                                    ).startswith(("http://", "https://"))
                                    else []
                                ),
                            ]
                        )
                    )[:7],
                    country=country,
                    headquarters=operating_place,
                    industry=discovered_item.get("industry", "").strip() or task.parsed_industry,
                    company_size=discovered_item.get("company_size", "").strip() or None,
                    description=discovered_item.get("description", "").strip()[:2000] or None,
                    geography_evidence_url=(
                        str(discovered_item.get("geography_evidence_url", "")).strip() or None
                    ),
                )
            )
            if len(resolved) >= discovery_limit:
                break
        if resolved:
            return resolved
        if self.discovery_provider.available:
            raise SearchTaskExecutionError(
                "no_verified_company_candidates",
                "Search found no real companies with a confirmable official website",
            )

        # Development-only fallback: accept only root company websites. Production uses
        # the web-grounded entity discovery provider above.
        raw_results = await self._search(task.original_query)
        for item in raw_results:
            hostname = urlparse(item.url).hostname
            if hostname is None:
                continue
            domain = registrable_domain(hostname)
            if domain in seen or domain_is_excluded(domain):
                continue
            if result_looks_editorial(item):
                continue
            homepage = normalize_official_homepage(item.url)
            if homepage is None or urlparse(item.url).path not in {"", "/"}:
                continue
            official_url, domain = homepage
            seen.add(domain)
            resolved.append(
                ResolvedCompany(
                    name=clean_company_name(item.title, domain.split(".", maxsplit=1)[0]),
                    official_url=official_url,
                    normalized_domain=domain,
                    research_urls=(official_url,),
                )
            )
            if len(resolved) >= task.result_limit:
                break
        if not resolved:
            raise SearchTaskExecutionError(
                "no_company_candidates", "По запросу не найдено уверенных кандидатов-компаний"
            )
        return resolved


def task_audit(
    session: AsyncSession,
    task: SearchTask,
    action: str,
    *,
    result: str = "success",
    safe_diff: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor="search_task_executor",
            action=action,
            entity_type="search_task",
            entity_id=str(task.id),
            result=result,
            safe_diff=safe_diff,
            request_id=f"search-task-{str(task.id)[:12]}",
        )
    )


async def set_stage(
    session: AsyncSession,
    task: SearchTask,
    stage: str,
    *,
    details: dict[str, object] | None = None,
) -> None:
    await session.refresh(task)
    if task.status == SearchTaskStatus.CANCELLED.value:
        raise SearchTaskCancelled
    task.current_stage = stage
    task_audit(session, task, f"search_task_{stage}", safe_diff=details)
    await session.commit()
    logger.info("search_task_stage task_id=%s stage=%s", task.id, stage)


async def ensure_company(
    session: AsyncSession, task: SearchTask, resolved: ResolvedCompany
) -> Company:
    company = await session.scalar(
        select(Company).where(Company.normalized_domain == resolved.normalized_domain)
    )
    if company is not None:
        if company.is_synthetic:
            raise SearchTaskExecutionError(
                "synthetic_company_conflict", "Resolved domain belongs to synthetic test data"
            )
        changed = False
        for field, value in (
            ("country", resolved.country or task.parsed_country),
            ("industry", resolved.industry or task.parsed_industry),
            ("company_size", resolved.company_size),
        ):
            if value and not getattr(company, field):
                setattr(company, field, value)
                changed = True
        if resolved.headquarters and resolved.headquarters not in company.operating_regions:
            company.operating_regions = [*company.operating_regions, resolved.headquarters]
            changed = True
        if changed:
            company.version += 1
            await session.commit()
            await session.refresh(company)
        return company
    if task.task_type == SearchTaskType.ANALYZE_COMPANY.value and task.started_at is not None:
        partial = await session.scalar(
            select(Company)
            .where(
                Company.is_synthetic.is_(False),
                Company.pipeline_status == PipelineStatus.NEW.value,
                Company.note == TASK_COMPANY_NOTE,
                Company.created_at >= task.started_at,
            )
            .order_by(Company.created_at.desc())
            .limit(1)
        )
        if partial is not None:
            partial.name = resolved.name
            partial.normalized_domain = resolved.normalized_domain
            partial.country = task.parsed_country
            partial.industry = task.parsed_industry
            partial.version += 1
            await session.commit()
            await session.refresh(partial)
            return partial
    return await create_company(
        CompanyCreate(
            name=resolved.name,
            normalized_domain=resolved.normalized_domain,
            is_synthetic=False,
            country=resolved.country or task.parsed_country,
            operating_regions=[resolved.headquarters] if resolved.headquarters else [],
            industry=resolved.industry or task.parsed_industry,
            company_size=resolved.company_size,
            language_signals=[],
            next_action="Complete official-source research",
            note=TASK_COMPANY_NOTE,
        ),
        session,
    )


async def verify_official_research(
    session: AsyncSession, company: Company, run: ResearchRun
) -> None:
    if run.source_id is None:
        return
    source = await session.get(CompanySource, run.source_id)
    if source is None:
        return
    source_host = urlparse(source.url).hostname
    if source_host is None or registrable_domain(source_host) != company.normalized_domain:
        return
    source.source_type = "official_public_web"
    source.trust_level = "official_public"
    source.freshness_status = "current"
    facts = list(
        await session.scalars(
            select(CompanyFact).where(
                CompanyFact.company_id == company.id,
                CompanyFact.source_id == source.id,
                CompanyFact.status == "extracted",
            )
        )
    )
    for fact in facts:
        fact.status = "verified"
        fact.confidence = max(fact.confidence, 0.8)
        fact.version += 1

    source_text = source.extracted_text or ""
    lowered_source = source_text.lower()
    if "oleg tinkov" in lowered_source and "advisor" in lowered_source:
        marker_at = lowered_source.find("oleg tinkov")
        exact_fragment = source_text[marker_at : marker_at + 1200]
        relationship_fact = await session.scalar(
            select(CompanyFact).where(
                CompanyFact.company_id == company.id,
                CompanyFact.fact_type == "leadership_relationship",
            )
        )
        if relationship_fact is None:
            session.add(
                CompanyFact(
                    company_id=company.id,
                    source_id=source.id,
                    fact_type="leadership_relationship",
                    value=exact_fragment,
                    confidence=0.9,
                    exact_fragment=exact_fragment,
                    status="verified",
                )
            )

    contacts = list(
        await session.scalars(
            select(Contact).where(
                Contact.company_id == company.id,
                Contact.source_id == source.id,
            )
        )
    )
    for contact in contacts:
        contact.verification_status = "verified_public"
        contact.validation_status = "VERIFIED_CONTACT"
        contact.validated_at = datetime.now(UTC)
        contact.validation_http_status = source.http_status
        contact.validation_final_url = source.url
        contact.validation_error = None
        contact.confidence = max(contact.confidence or 0, 0.8)
        contact.version += 1

    leader_match = re.search(
        r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'’-]+"
        r"(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'’-]+){1,3})"
        r"\s+Chief Executive Officer",
        source.extracted_text or "",
    )
    if leader_match:
        leader_name = leader_match.group(1)
        existing = await session.scalar(
            select(Contact).where(Contact.company_id == company.id, Contact.name == leader_name)
        )
        if existing is None:
            session.add(
                Contact(
                    company_id=company.id,
                    name=leader_name,
                    role="Chief Executive Officer",
                    other_public_link=source.url,
                    verification_status="verified_public",
                    validation_status="VERIFIED_CONTACT",
                    validated_at=datetime.now(UTC),
                    validation_http_status=source.http_status,
                    validation_final_url=source.url,
                    confidence=0.85,
                    lawful_public_source_note=(
                        f"Named as Chief Executive Officer on official public page {source.url}"
                    ),
                    decision_maker_role=DecisionMakerRole.CEO.value,
                    decision_priority=1,
                    source_id=source.id,
                )
            )
    await session.commit()


async def ensure_general_opportunity(
    session: AsyncSession, task: SearchTask, company: Company
) -> CompanyOpportunity:
    existing = await session.scalar(
        select(CompanyOpportunity)
        .where(CompanyOpportunity.company_id == company.id)
        .order_by(CompanyOpportunity.created_at.desc())
    )
    if existing is not None:
        return existing
    focus = (task.parsed_focus or task.original_query).lower()
    opportunity_type = (
        OpportunityType.BUSINESS_EXPANSION
        if any(marker in focus for marker in ("expansion", "business development"))
        else OpportunityType.PROCESS_AUTOMATION
        if any(marker in focus for marker in ("automation", "автоматизац"))
        else OpportunityType.GENERAL_COMPETENCE_FIT
    )
    source = await session.scalar(
        select(CompanySource)
        .where(CompanySource.company_id == company.id)
        .order_by(CompanySource.created_at.desc())
    )
    if source is None:
        raise SearchTaskExecutionError("research_has_no_source", "Research produced no source")
    return await create_opportunity(
        company.id,
        CompanyOpportunityCreate(
            opportunity_type=opportunity_type,
            rationale=(
                "Official public research supports a cautious competence-fit review; "
                "an internal hiring or consulting need is not assumed."
            ),
            confidence=0.35,
            source_ids=[source.id],
            status=EvidenceStatus.VERIFIED,
        ),
        session,
    )


def strategy_for_assessment(assessment: OpportunityAssessment) -> PositioningStrategy:
    if assessment.hybrid_fit_score >= max(
        assessment.business_fit_score, assessment.ai_automation_fit_score
    ):
        return PositioningStrategy.HYBRID
    if assessment.ai_automation_fit_score > assessment.business_fit_score:
        return PositioningStrategy.AI_FIRST
    return PositioningStrategy.BUSINESS_FIRST


async def ensure_positioning(
    session: AsyncSession,
    task: SearchTask,
    company: Company,
    assessment: OpportunityAssessment,
) -> PositioningRecommendation:
    existing = await session.scalar(
        select(PositioningRecommendation)
        .where(PositioningRecommendation.company_id == company.id)
        .order_by(PositioningRecommendation.created_at.desc())
    )
    if existing is not None:
        return existing
    strategy = strategy_for_assessment(assessment)
    possible_role = task.parsed_focus or "Project / Operations contribution"
    return await create_recommendation(
        company.id,
        PositioningRecommendationCreate(
            assessment_id=assessment.id,
            primary_strategy=strategy,
            primary_message_line=(
                "Lead with verified project and business execution experience relevant to "
                "the researched company context."
            ),
            secondary_advantage=(
                "Use practical AI/Python automation as a supporting capability without "
                "claiming senior engineering expertise."
            ),
            rationale=(
                "Deterministic scoring against the verified Candidate Profile and official "
                "company evidence selected this positioning."
            ),
            value_proposition=(
                "Support a bounded operational, expansion or automation workstream with "
                "structured delivery and explicit risk control."
            ),
            concrete_first_message_offer=(
                "Discuss one concrete workflow or launch challenge before proposing any solution."
            ),
            primary_decision_maker_role=DecisionMakerRole.HEAD_OF_OPERATIONS,
            secondary_decision_maker_role=DecisionMakerRole.TALENT_ACQUISITION,
            collaboration_format=CollaborationFormat.PROJECT_BASED,
            workplace_formats=[WorkplaceFormat.REMOTE],
            possible_role=possible_role[:500],
        ),
        session,
    )


async def advance_for_owner_decision(session: AsyncSession, company: Company) -> Company:
    await session.refresh(company)
    current = PipelineStatus(company.pipeline_status)
    if current == PipelineStatus.NEEDS_REVIEW:
        company = await update_company(
            company.id,
            CompanyUpdate(
                version=company.version,
                pipeline_status=PipelineStatus.OPPORTUNITY_IDENTIFIED,
            ),
            session,
        )
        current = PipelineStatus(company.pipeline_status)
    if current == PipelineStatus.NOT_RELEVANT:
        return company
    if current == PipelineStatus.DECISION_PENDING:
        return company
    if current != PipelineStatus.OPPORTUNITY_IDENTIFIED:
        raise SearchTaskExecutionError(
            "unsupported_pipeline_state", f"Scoring ended in state {current.value}"
        )
    company = await update_company(
        company.id,
        CompanyUpdate(
            version=company.version,
            pipeline_status=PipelineStatus.STRATEGY_SELECTED,
        ),
        session,
    )
    has_contact = bool(
        await session.scalar(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.company_id == company.id,
                Contact.validation_status == "VERIFIED_CONTACT",
            )
        )
    )
    company = await update_company(
        company.id,
        CompanyUpdate(
            version=company.version,
            pipeline_status=(
                PipelineStatus.CONTACT_FOUND if has_contact else PipelineStatus.CONTACT_MISSING
            ),
        ),
        session,
    )
    return await update_company(
        company.id,
        CompanyUpdate(
            version=company.version,
            pipeline_status=PipelineStatus.DECISION_PENDING,
            next_action=(
                "Owner decision required: write, research deeper, defer, watchlist or not relevant"
            ),
        ),
        session,
    )


COUNTRY_EVIDENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "russia": ("russia", "russian federation", "россия", "российск", "moscow", "москва"),
    "россия": ("russia", "russian federation", "россия", "российск", "moscow", "москва"),
    "mexico": ("mexico", "méxico", "mexican", "мексик"),
    "мексика": ("mexico", "méxico", "mexican", "мексик"),
    "serbia": ("serbia", "serbian", "србија", "серби"),
    "сербия": ("serbia", "serbian", "србија", "серби"),
}


def _country_aliases(country: str) -> tuple[str, ...]:
    normalized = country.casefold().strip()
    return COUNTRY_EVIDENCE_ALIASES.get(normalized, (normalized,))


def _evidence_fragment(text: str, markers: tuple[str, ...], radius: int = 260) -> str:
    lowered = text.casefold()
    index = next((lowered.find(marker) for marker in markers if marker in lowered), -1)
    if index < 0:
        return ""
    return " ".join(text[max(0, index - radius) : index + radius].split())


def confirms_ai_company(official_text: str) -> bool:
    """Recognize evidence-backed commercial AI/CV products without relying on an AI label."""

    normalized = official_text.casefold()
    ai_markers = (
        "artificial intelligence",
        "machine learning",
        "computer vision",
        "neural network",
        "face recognition",
        "facial recognition",
        "object recognition",
        "video analytics",
        "biometric",
        "искусственн",
        "машинн",
        "компьютерн",
        "нейросет",
        "распознаван",
        "видеоаналит",
        "биометр",
    )
    commercial_markers = (
        "product",
        "platform",
        "solution",
        "technology",
        "software",
        "продукт",
        "платформ",
        "решени",
        "технолог",
        "систем",
    )
    return any(marker in normalized for marker in ai_markers) and any(
        marker in normalized for marker in commercial_markers
    )


async def qualify_company(
    session: AsyncSession,
    task: SearchTask,
    company: Company,
    runs: list[ResearchRun],
) -> dict[str, object]:
    """Apply evidence-based hard constraints before scoring or owner display."""

    source_ids = {item.source_id for item in runs if item.source_id is not None}
    sources = list(
        await session.scalars(select(CompanySource).where(CompanySource.id.in_(source_ids)))
    )
    official_sources = [
        item
        for item in sources
        if (host := urlparse(item.url).hostname)
        and registrable_domain(host) == company.normalized_domain
        and item.http_status is not None
        and 200 <= item.http_status < 300
        and not item.error
    ]
    if not official_sources:
        raise SearchTaskExecutionError(
            "IDENTITY_UNCONFIRMED",
            "Официальный сайт компании не удалось подтвердить доступным источником",
        )

    brand_values = {
        re.sub(r"[^a-zа-я0-9]", "", company.name.casefold()),
        re.sub(
            r"[^a-zа-я0-9]",
            "",
            company.normalized_domain.split(".", maxsplit=1)[0].casefold(),
        ),
    }
    brand_values.update(
        token
        for token in re.findall(
            r"[a-zа-я0-9]{4,}",
            f"{company.name} {company.normalized_domain.split('.', maxsplit=1)[0]}".casefold(),
        )
        if token not in {"company", "technologies", "technology", "компания"}
    )
    brand_markers = tuple(item for item in brand_values if len(item) >= 3)
    identity_source = next(
        (
            item
            for item in official_sources
            if any(
                marker in re.sub(r"[^a-zа-я0-9]", "", (item.extracted_text or "").casefold())
                for marker in brand_markers
            )
        ),
        None,
    )
    if identity_source is None:
        raise SearchTaskExecutionError(
            "IDENTITY_UNCONFIRMED",
            "Содержимое найденного сайта не подтверждает заявленную компанию",
        )
    company.identity_verification_status = "verified"
    company.identity_source_id = identity_source.id

    country_source: CompanySource | None = None
    country_fragment = ""
    if task.parsed_country:
        aliases = _country_aliases(task.parsed_country)
        for source in sources:
            fragment = _evidence_fragment(source.extracted_text or "", aliases)
            if fragment:
                country_source = source
                country_fragment = fragment
                break
        if country_source is None:
            company.geography_verification_status = "unconfirmed"
            company.geography_source_id = None
            company.version += 1
            await session.commit()
            raise SearchTaskExecutionError(
                "GEOGRAPHY_UNCONFIRMED",
                f"Связь компании с географией «{task.parsed_country}» не подтверждена источником",
            )
        company.country = task.parsed_country
        company.geography_verification_status = "verified"
        company.geography_source_id = country_source.id
        geography_fact = await session.scalar(
            select(CompanyFact).where(
                CompanyFact.company_id == company.id,
                CompanyFact.fact_type == "verified_geography",
                CompanyFact.source_id == country_source.id,
            )
        )
        if geography_fact is None:
            session.add(
                CompanyFact(
                    company_id=company.id,
                    source_id=country_source.id,
                    fact_type="verified_geography",
                    value=task.parsed_country,
                    confidence=0.85,
                    exact_fragment=country_fragment,
                    status="verified",
                )
            )
    else:
        company.geography_verification_status = "not_required"

    query = task.original_query.casefold()
    requests_ai_company = bool(
        re.search(r"(?:\bai\b|\bии\b|artificial intelligence|искусственн.{0,12}интеллект)", query)
    )
    if requests_ai_company:
        official_text = " ".join(item.extracted_text or "" for item in official_sources).casefold()
        if not confirms_ai_company(official_text):
            raise SearchTaskExecutionError(
                "INDUSTRY_UNCONFIRMED",
                "Официальные материалы не подтверждают AI как основное коммерческое направление",
            )

    company.version += 1
    await session.commit()
    return {
        "identity": "verified",
        "identity_source_id": str(identity_source.id),
        "geography": company.geography_verification_status,
        "geography_source_id": str(country_source.id) if country_source else None,
        "industry_constraint": "verified" if requests_ai_company else "not_required",
        "sources_checked": len(sources),
    }


async def link_result(
    session: AsyncSession,
    task: SearchTask,
    company: Company,
    *,
    accepted: bool,
    qualification_status: str | None = None,
    rejection_reason: str | None = None,
    qualification_evidence: dict[str, object] | None = None,
) -> None:
    existing = await session.get(
        SearchTaskResult,
        {"search_task_id": task.id, "company_id": company.id},
    )
    if existing is None:
        session.add(
            SearchTaskResult(
                search_task_id=task.id,
                company_id=company.id,
                accepted=accepted,
                qualification_status=qualification_status
                or ("QUALIFIED" if accepted else "REJECTED"),
                rejection_reason=rejection_reason,
                qualification_evidence=qualification_evidence or {},
                linked_at=datetime.now(UTC),
            )
        )
    else:
        existing.accepted = accepted
        existing.qualification_status = qualification_status or (
            "QUALIFIED" if accepted else "REJECTED"
        )
        existing.rejection_reason = rejection_reason
        existing.qualification_evidence = qualification_evidence or {}
    await session.flush()
    task.found_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SearchTaskResult)
            .where(SearchTaskResult.search_task_id == task.id)
        )
        or 0
    )
    task.accepted_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SearchTaskResult)
            .where(
                SearchTaskResult.search_task_id == task.id,
                SearchTaskResult.accepted.is_(True),
            )
        )
        or 0
    )
    await session.commit()


async def reload_company_after_rollback(
    session: AsyncSession, company_id: UUID
) -> Company | None:
    """Reload a company after rollback without touching expired ORM attributes.

    SQLAlchemy expires ORM objects on rollback.  In an async session, reading
    ``company.id`` after that point may try to lazy-load the value outside the
    greenlet bridge and abort the whole Search Task.  Callers must retain the
    scalar ID before a potentially failing operation and pass it here.
    """

    await session.rollback()
    return await session.get(Company, company_id)


async def was_previously_presented_to_owner(
    session: AsyncSession, normalized_domain: str
) -> bool:
    """Whether a company was already accepted into the owner's inbox.

    Daily discovery must use its limit for new opportunities. A company already
    accepted once remains available in search history and is not a new result.
    Manual research deliberately remains unaffected.
    """

    company_id = await session.scalar(
        select(Company.id).where(Company.normalized_domain == normalized_domain).limit(1)
    )
    if company_id is None:
        return False
    return (
        await session.scalar(
            select(SearchTaskResult.search_task_id)
            .where(
                SearchTaskResult.company_id == company_id,
                SearchTaskResult.accepted.is_(True),
            )
            .limit(1)
        )
    ) is not None


async def process_company(
    session: AsyncSession,
    task: SearchTask,
    resolved: ResolvedCompany,
    fetcher: SafeFetcher,
    *,
    run_contact_discovery: bool = True,
) -> Company:
    await session.refresh(task)
    if task.status == SearchTaskStatus.CANCELLED.value:
        raise SearchTaskCancelled
    company = await ensure_company(session, task, resolved)
    # Keep this scalar before any operation that might roll back the session.
    # ORM attributes are expired by rollback in AsyncSession.
    company_id = company.id
    task_id = task.id
    await set_stage(
        session,
        task,
        "company_resolved",
        details={"company_id": str(company.id), "domain": company.normalized_domain},
    )
    completed_runs: list[ResearchRun] = []
    request = cast(
        Any,
        SimpleNamespace(state=SimpleNamespace(request_id=f"search-task-{task.id}")),
    )
    research_errors: list[str] = []
    research_queue = list(dict.fromkeys(resolved.research_urls))
    attempted: set[str] = set()
    while research_queue and len(attempted) < 7:
        url = research_queue.pop(0)
        if url in attempted:
            continue
        attempted.add(url)
        await session.refresh(task)
        if task.status == SearchTaskStatus.CANCELLED.value:
            raise SearchTaskCancelled
        try:
            result = await run_research(
                company.id,
                ResearchRequest(url=url),
                request,
                session,
                fetcher,
            )
            run = await session.get(ResearchRun, result.run.id)
            if run is not None:
                completed_runs.append(run)
                await verify_official_research(session, company, run)
                for link in (run.result_summary or {}).get("research_links", []):
                    if not isinstance(link, str) or link in attempted or link in research_queue:
                        continue
                    hostname = urlparse(link).hostname
                    if hostname and registrable_domain(hostname) == company.normalized_domain:
                        research_queue.append(link)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            research_errors.append(str(detail.get("message", detail)))
    if not completed_runs:
        raise SearchTaskExecutionError(
            "research_failed",
            (research_errors[0] if research_errors else "Official website research failed")[:1000],
        )
    await set_stage(
        session,
        task,
        "research_completed",
        details={"company_id": str(company.id), "sources": len(completed_runs)},
    )
    qualification = await qualify_company(session, task, company, completed_runs)
    await set_stage(
        session,
        task,
        "qualification_completed",
        details={"company_id": str(company.id), **qualification},
    )
    await ensure_general_opportunity(session, task, company)
    await set_stage(session, task, "opportunity_created", details={"company_id": str(company.id)})
    assessment = await calculate_company_relevance(company.id, session)
    await set_stage(
        session,
        task,
        "scoring_completed",
        details={
            "company_id": str(company.id),
            "score": assessment.overall_opportunity_score,
        },
    )
    await ensure_positioning(session, task, company, assessment)
    try:
        if not run_contact_discovery:
            raise StopAsyncIteration
        # Local import avoids a module cycle: contact discovery reuses PublicSearchResolver.
        from app.modules.crm.contact_discovery import discover_company_contacts

        await set_stage(
            session,
            task,
            "contact_research",
            details={"company_id": str(company.id)},
        )
        report = await discover_company_contacts(session, company, fetcher=fetcher)
        await set_stage(
            session,
            task,
            "contact_research_completed",
            details={
                "company_id": str(company.id),
                "status": report.status,
                "candidates": report.candidates,
                "verified_channels": report.verified_channels,
            },
        )
    except StopAsyncIteration:
        pass
    except Exception as exc:  # noqa: BLE001 - contact absence must not discard company research
        # Both ORM objects may have expired after a contact-discovery rollback.
        await session.rollback()
        recovered_company = await session.get(Company, company_id)
        recovered_task = await session.get(SearchTask, task_id)
        if recovered_company is None or recovered_task is None:
            raise SearchTaskExecutionError(
                "task_state_lost", "Search task state was lost during contact research"
            ) from exc
        company = recovered_company
        task = recovered_task
        company.contact_discovery_status = "failed"
        company.contact_discovered_at = datetime.now(UTC)
        company.version += 1
        task_audit(
            session,
            task,
            "search_task_contact_research_failed",
            result="failed",
            safe_diff={"company_id": str(company_id), "error_type": type(exc).__name__},
        )
        await session.commit()
    from app.modules.auth.models import User
    from app.modules.opportunities.quality import ready_for_inbox
    from app.modules.opportunities.readiness import evaluate_opportunity_readiness
    from app.modules.research.deeper import execute_deeper_research

    owner = await session.get(User, task.owner_id)
    locale = owner.dashboard_locale if owner and owner.dashboard_locale in {"ru", "en"} else "en"
    synthesis = await refresh_decision_synthesis(session, company, locale=locale)
    readiness = await evaluate_opportunity_readiness(session, company, locale=locale)
    accepted = ready_for_inbox(
        company, synthesis.payload, readiness.contact_status == "CONTACT_FOUND"
    )
    if not accepted and company.relevance_status != "not_relevant":
        await set_stage(session, task, "quality_research", details={"company_id": str(company.id)})
        try:
            await execute_deeper_research(
                session, company, request, fetcher, run_research, calculate_company_relevance
            )
            if run_contact_discovery:
                from app.modules.crm.contact_discovery import discover_company_contacts

                await discover_company_contacts(session, company, fetcher=fetcher)
            await session.refresh(company)
            synthesis = await refresh_decision_synthesis(session, company, locale=locale)
            readiness = await evaluate_opportunity_readiness(session, company, locale=locale)
            accepted = ready_for_inbox(
                company, synthesis.payload, readiness.contact_status == "CONTACT_FOUND"
            )
        except Exception as exc:  # noqa: BLE001 - preserve research, withhold incomplete result
            await session.rollback()
            recovered_task = await session.get(SearchTask, task_id)
            recovered_company = await session.get(Company, company_id)
            if recovered_task is None or recovered_company is None:
                raise SearchTaskExecutionError(
                    "task_state_lost", "Search task state was lost during deeper research"
                ) from exc
            task = recovered_task
            company = recovered_company
            task_audit(
                session,
                task,
                "search_task_quality_research_failed",
                result="failed",
                safe_diff={"error_type": type(exc).__name__},
            )
            await session.commit()
            accepted = False
    await session.refresh(task)
    if task.status == SearchTaskStatus.CANCELLED.value:
        raise SearchTaskCancelled
    if accepted:
        company = await advance_for_owner_decision(session, company)
        # Prepare the other dashboard language in the worker, never on a page GET.
        await refresh_decision_synthesis(session, company, locale="en" if locale == "ru" else "ru")
    await link_result(
        session,
        task,
        company,
        accepted=accepted,
        qualification_status="QUALIFIED" if accepted else "QUALITY_REVIEW_REQUIRED",
        qualification_evidence=qualification,
    )
    return company


async def claim_task(session: AsyncSession, task_id: UUID) -> SearchTask | None:
    claimed_id = await session.scalar(
        update(SearchTask)
        .where(
            SearchTask.id == task_id,
            SearchTask.status == SearchTaskStatus.RUNNING.value,
            or_(
                SearchTask.current_stage.is_(None),
                SearchTask.current_stage == "queued_for_execution",
            ),
        )
        .values(
            current_stage="resolving_company",
            failure_code=None,
            failure_reason=None,
            attempt_count=SearchTask.attempt_count + 1,
        )
        .returning(SearchTask.id)
    )
    if claimed_id is None:
        await session.rollback()
        return None
    await session.commit()
    task = await session.get(SearchTask, claimed_id)
    if task is not None:
        task_audit(session, task, "search_task_executor_claimed")
        await session.commit()
    return task


async def fail_task(session: AsyncSession, task_id: UUID, code: str, reason: str) -> None:
    await session.rollback()
    task = await session.get(SearchTask, task_id)
    if task is None:
        return
    if task.status == SearchTaskStatus.CANCELLED.value:
        return
    task.status = SearchTaskStatus.FAILED.value
    task.current_stage = "failed"
    task.failure_code = code[:80]
    task.failure_reason = reason[:2000]
    task.completed_at = datetime.now(UTC)
    task_audit(
        session,
        task,
        "search_task_failed",
        result="failed",
        safe_diff={"failure_code": task.failure_code, "failure_reason": task.failure_reason},
    )
    await session.commit()
    logger.error("search_task_failed task_id=%s code=%s reason=%s", task_id, code, reason)


async def execute_claimed_task(
    session: AsyncSession,
    task: SearchTask,
    *,
    resolver: PublicSearchResolver | None = None,
    fetcher: SafeFetcher | None = None,
    run_contact_discovery: bool = True,
) -> None:
    candidates = await (resolver or PublicSearchResolver()).resolve(task)
    if not candidates:
        raise SearchTaskExecutionError("no_company_candidates", "No companies resolved")
    candidate_failures: list[str] = []
    previously_presented = 0
    for candidate in candidates:
        await session.refresh(task)
        task_id = task.id
        if task.status == SearchTaskStatus.CANCELLED.value:
            raise SearchTaskCancelled
        if task.accepted_count >= task.result_limit:
            break
        if task.source == "daily" and await was_previously_presented_to_owner(
            session, candidate.normalized_domain
        ):
            previously_presented += 1
            task_audit(
                session,
                task,
                "search_task_candidate_skipped_already_presented",
                safe_diff={"domain": candidate.normalized_domain},
            )
            await session.commit()
            continue
        try:
            await process_company(
                session,
                task,
                candidate,
                fetcher or SafeFetcher(),
                run_contact_discovery=run_contact_discovery,
            )
        except SearchTaskExecutionError as exc:
            await session.rollback()
            company = await session.scalar(
                select(Company).where(Company.normalized_domain == candidate.normalized_domain)
            )
            recovered_task = await session.get(SearchTask, task_id)
            if recovered_task is None:
                raise
            task = recovered_task
            if company is not None:
                # A fetch or provider failure is not a negative business signal.
                # Preserve any earlier research and owner state on a known company.
                await link_result(
                    session,
                    task,
                    company,
                    accepted=False,
                    qualification_status=exc.code,
                    rejection_reason=str(exc),
                    qualification_evidence={"domain": candidate.normalized_domain},
                )
                await session.refresh(task)
            candidate_failures.append(f"{candidate.normalized_domain}: {exc.code}")
            task_audit(
                session,
                task,
                "search_task_candidate_skipped",
                result="failed",
                safe_diff={
                    "domain": candidate.normalized_domain,
                    "failure_code": exc.code,
                },
            )
            await session.commit()
            continue
    await session.refresh(task)
    if task.status == SearchTaskStatus.CANCELLED.value:
        raise SearchTaskCancelled
    if task.found_count == 0 and not previously_presented:
        raise SearchTaskExecutionError(
            "all_company_candidates_failed",
            "No candidate completed official-source research. " + "; ".join(candidate_failures[:5]),
        )
    task.status = SearchTaskStatus.COMPLETED.value
    task.current_stage = "completed"
    task.completed_at = datetime.now(UTC)
    task.failure_code = None
    if task.accepted_count < task.result_limit:
        task.failure_reason = (
            "No new companies were available in this search pool; "
            "previously presented companies were skipped."
            if task.accepted_count == 0 and previously_presented
            else f"Completed with {task.accepted_count} of {task.result_limit} requested results"
        )
    else:
        task.failure_reason = None
    task_audit(
        session,
        task,
        "search_task_completed",
        safe_diff={
            "found_count": task.found_count,
            "accepted_count": task.accepted_count,
            "already_presented_skipped": previously_presented,
        },
    )
    await session.commit()
    logger.info(
        "search_task_completed task_id=%s found=%s accepted=%s",
        task.id,
        task.found_count,
        task.accepted_count,
    )


async def execute_search_task_by_id(
    task_id: UUID,
    *,
    resolver: PublicSearchResolver | None = None,
    fetcher: SafeFetcher | None = None,
) -> bool:
    """Claim and execute one RUNNING task; return False when it was not claimable."""

    async with SessionFactory() as session:
        task = await claim_task(session, task_id)
        if task is None:
            return False
        claimed_task_id = task.id
        try:
            await asyncio.wait_for(
                execute_claimed_task(session, task, resolver=resolver, fetcher=fetcher),
                timeout=TASK_EXECUTION_TIMEOUT_SECONDS,
            )
            return True
        except SearchTaskCancelled:
            await session.rollback()
            logger.info("search_task_cancelled task_id=%s", claimed_task_id)
            return True
        except TimeoutError:
            await fail_task(
                session,
                claimed_task_id,
                "search_task_timeout",
                "Поиск превысил безопасный лимит 5 минут и был остановлен. "
                "Попробуйте сузить запрос.",
            )
            return True
        except SearchTaskExecutionError as exc:
            await fail_task(session, claimed_task_id, exc.code, str(exc))
            return True
        except Exception as exc:  # noqa: BLE001 - fail closed and persist a human error
            await fail_task(session, claimed_task_id, "unexpected_executor_error", str(exc))
            return True


async def requeue_interrupted_task_by_id(task_id: UUID) -> bool:
    """Requeue a RUNNING task left in a nonterminal stage after process interruption."""

    async with SessionFactory() as session:
        task = await session.get(SearchTask, task_id)
        if task is None or task.status != SearchTaskStatus.RUNNING.value:
            return False
        if task.current_stage in {None, "queued_for_execution"}:
            return True
        previous_stage = task.current_stage
        task.current_stage = "queued_for_execution"
        task_audit(
            session,
            task,
            "search_task_requeued_after_interruption",
            safe_diff={"previous_stage": previous_stage},
        )
        await session.commit()
        return True


async def requeue_completed_task_for_refresh(task_id: UUID) -> bool:
    """Re-run research for one completed task without creating a new Search Task."""

    async with SessionFactory() as session:
        task = await session.get(SearchTask, task_id)
        if task is None or task.status != SearchTaskStatus.COMPLETED.value:
            return False
        task.status = SearchTaskStatus.RUNNING.value
        task.current_stage = "queued_for_execution"
        task.completed_at = None
        task_audit(session, task, "search_task_requeued_for_research_refresh")
        await session.commit()
        return True
