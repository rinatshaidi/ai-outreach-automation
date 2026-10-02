"""Public, bounded and opportunity-aware Contact Discovery Engine v1."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.crm.contact_channel_semantics import (
    is_relevant_official_path,
)
from app.modules.crm.contact_channel_semantics import (
    is_semantic_contact_channel as _is_semantic_contact_channel,
)
from app.modules.crm.contact_validation import classify_contact_for_outreach
from app.modules.crm.models import (
    CommunicationEvent,
    Company,
    CompanySource,
    Contact,
    ContactChannel,
)
from app.modules.opportunities.models import CompanyOpportunity
from app.modules.research.fetcher import (
    SafeFetcher,
    SafeFetchError,
    address_is_forbidden,
    normalize_public_url,
    resolve_public_addresses,
)
from app.modules.search_tasks.executor import PublicSearchResolver, SearchResult

MAX_OFFICIAL_SOURCES = 3
MAX_SEARCH_QUERIES = 3
MAX_CONTACTS_SHOWN = 5
EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.I)
PHONE_RE = re.compile(r"\+?[1-9][0-9 ()-]{7,}[0-9]")
ROLE_MARKERS = (
    "Founder",
    "Co-Founder",
    "Chief Executive Officer",
    "CEO",
    "Managing Director",
    "Chief Operating Officer",
    "COO",
    "Head of Operations",
    "Head of Business Development",
    "Head of Expansion",
    "Country Manager",
    "Head of Projects",
    "Program Manager",
    "Head of Transformation",
    "Head of Automation",
    "Head of AI",
    "Talent Acquisition",
    "Recruiter",
    "Hiring Manager",
)
SOFT_404_MARKERS = ("page not found", "404", "doesn't exist", "something went wrong")


@dataclass(frozen=True)
class ChannelCandidate:
    channel_type: str
    value: str
    url: str | None
    source_url: str
    source_type: str
    confidence: float
    source_text: str = ""


@dataclass
class ContactCandidate:
    name: str
    role: str
    why_relevant: str
    channels: list[ChannelCandidate] = field(default_factory=list)
    named: bool = False


@dataclass(frozen=True)
class DiscoveryReport:
    company_id: Any
    status: str
    candidates: int
    verified_channels: int
    partial_channels: int
    invalid_channels: int
    search_errors: tuple[str, ...]


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored += 1
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        clean = " ".join(data.split())
        if clean:
            self.text_parts.append(clean)
            if self._href is not None:
                self._anchor_parts.append(clean)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor_parts)))
            self._href = None
            self._anchor_parts = []
        if tag in {"script", "style", "noscript", "svg"} and self._ignored:
            self._ignored -= 1

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


def _channel_type(url: str) -> str | None:
    lowered = url.casefold()
    host = (urlparse(url).hostname or "").casefold()
    if lowered.startswith("mailto:"):
        return "email"
    if lowered.startswith("tel:"):
        return "phone"
    if host.endswith("linkedin.com"):
        return "linkedin"
    if host.endswith("facebook.com") or host == "fb.me":
        return "facebook"
    if host == "t.me" or host.endswith("telegram.me"):
        return "telegram"
    if host == "wa.me" or "api.whatsapp.com" in host:
        return "whatsapp"
    return None


def _clean_channel_value(channel_type: str, url: str) -> str:
    if channel_type == "email":
        return url.removeprefix("mailto:").split("?", maxsplit=1)[0].strip().casefold()
    if channel_type == "phone":
        return url.removeprefix("tel:").strip()
    return url


def _role_from_text(text: str) -> str | None:
    lowered = text.casefold()
    return next((role for role in ROLE_MARKERS if role.casefold() in lowered), None)


def _person_from_result(result: SearchResult, company: Company) -> tuple[str, str] | None:
    role = _role_from_text(result.title)
    if role is None:
        return None
    title = re.sub(r"\s*\|\s*LinkedIn.*$", "", result.title, flags=re.I)
    name = re.split(r"\s+[-–—|]\s+", title, maxsplit=1)[0].strip()
    if not name or company.name.casefold() in name.casefold() or len(name.split()) > 5:
        return None
    return name, role


def _generic_role_for_url(url: str) -> str:
    lowered = url.casefold()
    if any(item in lowered for item in ("customer support", "support@", "help@", "ayuda@")):
        return "Customer Support"
    if any(item in lowered for item in ("career", "job", "recruit")):
        return "Talent Acquisition / Careers"
    if any(item in lowered for item in ("partner", "business", "sales")):
        return "Business Development / Partnerships"
    if any(item in lowered for item in ("press", "media")):
        return "Press / Communications"
    return "Official company contact"


def _is_relevant_official_path(url: str, anchor: str = "") -> bool:
    return is_relevant_official_path(url, anchor)


def is_semantic_contact_channel(channel_type: str, url: str | None) -> bool:
    """Compatibility export for older callers."""

    return _is_semantic_contact_channel(channel_type, url)


def _official_candidates(
    company: Company,
    source: CompanySource,
    body: bytes,
    content_type: str,
) -> list[ContactCandidate]:
    parser = LinkParser()
    text = body.decode("utf-8", errors="replace")
    if "html" in content_type:
        parser.feed(text)
    else:
        parser.text_parts.append(text)
    candidates: dict[tuple[str, str], ContactCandidate] = {}

    def add_generic(role: str, channel: ChannelCandidate) -> None:
        key = (f"{company.name} {role}", role)
        candidate = candidates.setdefault(
            key,
            ContactCandidate(
                name=f"{company.name} {role}",
                role=role,
                why_relevant=f"Official public {role.lower()} path",
            ),
        )
        if not any(
            item.channel_type == channel.channel_type and item.value == channel.value
            for item in candidate.channels
        ):
            candidate.channels.append(channel)

    for href, anchor in parser.links:
        absolute = urljoin(source.url, unescape(href.strip()))
        channel_type = _channel_type(absolute)
        if channel_type:
            value = _clean_channel_value(channel_type, absolute)
            role = _generic_role_for_url(f"{anchor} {source.url}")
            add_generic(
                role,
                ChannelCandidate(
                    channel_type=channel_type,
                    value=value,
                    url=None if channel_type in {"email", "phone"} else absolute,
                    source_url=source.url,
                    source_type="official_site",
                    confidence=0.8,
                    source_text=parser.text,
                ),
            )
        elif absolute.startswith(("http://", "https://")) and _is_relevant_official_path(
            absolute, anchor
        ):
            role = _generic_role_for_url(f"{urlparse(absolute).path} {anchor}")
            add_generic(
                role,
                ChannelCandidate(
                    channel_type="official_form",
                    value=absolute,
                    url=absolute,
                    source_url=source.url,
                    source_type="official_site",
                    confidence=0.75,
                    source_text=parser.text,
                ),
            )
    for email in dict.fromkeys(EMAIL_RE.findall(parser.text)):
        role = _generic_role_for_url(f"{email} {source.url}")
        add_generic(
            role,
            ChannelCandidate(
                channel_type="email",
                value=email.casefold(),
                url=None,
                source_url=source.url,
                source_type="official_site",
                confidence=0.85,
                source_text=parser.text,
            ),
        )
    return list(candidates.values())


def _search_candidate(company: Company, result: SearchResult) -> ContactCandidate | None:
    channel_type = _channel_type(result.url)
    person = _person_from_result(result, company)
    if person:
        name, role = person
        return ContactCandidate(
            name=name,
            role=role,
            why_relevant=f"Public professional profile for a {role} relevant to the opportunity",
            named=True,
            channels=[
                ChannelCandidate(
                    channel_type=channel_type or "professional_profile",
                    value=result.url,
                    url=result.url,
                    source_url=result.url,
                    source_type="public_search",
                    confidence=0.7,
                    source_text=result.title,
                )
            ],
        )
    if channel_type:
        role = _generic_role_for_url(result.url)
        return ContactCandidate(
            name=f"{company.name} {role}",
            role=role,
            why_relevant=f"Public {role.lower()} channel found in search results",
            channels=[
                ChannelCandidate(
                    channel_type=channel_type,
                    value=_clean_channel_value(channel_type, result.url),
                    url=result.url,
                    source_url=result.url,
                    source_type="public_search",
                    confidence=0.55,
                    source_text=result.title,
                )
            ],
        )
    result_host = (urlparse(result.url).hostname or "").casefold().removeprefix("www.")
    official_host = company.normalized_domain.casefold().removeprefix("www.")
    result_text = f"{result.title} {result.url}".casefold()
    official_relevant_path = _is_relevant_official_path(result.url, result.title)
    if official_relevant_path and (
        result_host == official_host or result_host.endswith(f".{official_host}")
    ):
        role = _generic_role_for_url(result_text)
        return ContactCandidate(
            name=f"{company.name} {role}",
            role=role,
            why_relevant=f"Official public {role.lower()} path found in search results",
            channels=[
                ChannelCandidate(
                    channel_type="official_form",
                    value=result.url,
                    url=result.url,
                    source_url=result.url,
                    source_type="public_search",
                    confidence=0.7,
                    source_text=result.title,
                )
            ],
        )
    return None


async def _validate_channel(
    channel: ChannelCandidate,
    contact: Contact,
    company: Company,
    fetcher: SafeFetcher,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    if channel.channel_type == "email":
        syntax_ok = bool(EMAIL_RE.fullmatch(channel.value))
        found_at_source = channel.value.casefold() in channel.source_text.casefold()
        domain_ok = False
        if syntax_ok:
            try:
                addresses = await resolve_public_addresses(
                    channel.value.rsplit("@", maxsplit=1)[1]
                )
                domain_ok = bool(addresses) and not any(
                    address_is_forbidden(address) for address in addresses
                )
            except SafeFetchError:
                domain_ok = False
        return {
            "status": (
                "VERIFIED"
                if syntax_ok and found_at_source and domain_ok
                else "UNVERIFIED"
            ),
            "validated_at": now,
            "http_status": None,
            "final_url": None,
            "error": (
                None
                if syntax_ok and domain_ok
                else ("email_domain_unresolved" if syntax_ok else "invalid_email_syntax")
            ),
        }
    if channel.channel_type == "phone":
        public = bool(PHONE_RE.fullmatch(channel.value)) and channel.value in channel.source_text
        return {
            "status": "VERIFIED" if public else "UNVERIFIED",
            "validated_at": now,
            "http_status": None,
            "final_url": None,
            "error": None if public else "phone_not_confirmed_in_public_source",
        }
    raw_url = channel.url or channel.value
    if not is_semantic_contact_channel(channel.channel_type, raw_url):
        return {
            "status": "INVALID",
            "validated_at": now,
            "http_status": None,
            "final_url": None,
            "error": "url_not_matching_declared_channel",
        }
    try:
        normalized = normalize_public_url(raw_url)
        document = await fetcher.fetch(normalized)
    except SafeFetchError as exc:
        match = re.search(r"HTTP (\d{3})", str(exc))
        http_status = int(match.group(1)) if match else None
        invalid = http_status in {404, 410} or exc.code in {
            "invalid_scheme",
            "missing_hostname",
            "invalid_hostname",
            "private_address",
        }
        return {
            "status": "INVALID" if invalid else "UNVERIFIED",
            "validated_at": now,
            "http_status": http_status,
            "final_url": None,
            "error": f"{exc.code}: {exc}"[:500],
        }
    page_text = " ".join(document.body.decode("utf-8", errors="replace").split()).casefold()
    if any(marker in page_text[:5000] for marker in SOFT_404_MARKERS):
        return {
            "status": "INVALID",
            "validated_at": now,
            "http_status": document.status_code,
            "final_url": document.final_url,
            "error": "soft_404",
        }
    company_token = re.sub(r"[^a-z0-9]", "", company.name.casefold())
    contact_tokens = [
        item.casefold()
        for item in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", f"{contact.name} {contact.role}")
    ]
    compact_page = re.sub(r"[^a-z0-9]", "", page_text)
    identity = bool(company_token and company_token in compact_page) or any(
        token in page_text for token in contact_tokens
    )
    return {
        "status": "VERIFIED" if identity else "PARTIAL",
        "validated_at": now,
        "http_status": document.status_code,
        "final_url": document.final_url,
        "error": None if identity else "reachable_but_identity_not_confirmed",
    }


def _role_score(role: str, opportunities: set[str]) -> float:
    lowered = role.casefold()
    score = 0.0
    weights = (
        (("founder", "co-founder"), 90),
        (("ceo", "chief executive", "managing director"), 88),
        (("coo", "chief operating", "head of operations"), 82),
        (("business development",), 76),
        (("expansion", "market development", "country manager"), 75),
        (("projects", "program"), 68),
        (("transformation", "automation", "head of ai"), 70),
        (("talent", "recruit", "hiring"), 58),
        (("partnership", "business contact"), 55),
        (("press",), 15),
        (("support",), 5),
    )
    for markers, value in weights:
        if any(marker in lowered for marker in markers):
            score = max(score, float(value))
    if opportunities.intersection({"business_expansion", "market_entry"}) and any(
        item in lowered for item in ("expansion", "business development", "country manager")
    ):
        score += 20
    if opportunities.intersection({"ai_adoption", "process_automation"}) and any(
        item in lowered for item in ("automation", "transformation", "operations", "ai")
    ):
        score += 20
    return score


async def _upsert_candidate(
    session: AsyncSession,
    company: Company,
    candidate: ContactCandidate,
) -> Contact:
    email = next(
        (item.value for item in candidate.channels if item.channel_type == "email"), None
    )
    identity_conditions = [func.lower(Contact.name) == candidate.name.casefold()]
    if email:
        identity_conditions.append(func.lower(Contact.email) == email.casefold())
    contact = await session.scalar(
        select(Contact).where(
            Contact.company_id == company.id,
            or_(*identity_conditions),
        )
    )
    if contact is None:
        contact = Contact(
            company_id=company.id,
            name=candidate.name[:200],
            role=candidate.role[:200],
            email=email,
            verification_status="unverified",
            confidence=0,
            lawful_public_source_note=candidate.channels[0].source_url,
            why_relevant=candidate.why_relevant,
            do_not_contact="customer support" in candidate.role.casefold(),
        )
        session.add(contact)
        await session.flush()
    else:
        contact.role = candidate.role[:200] or contact.role
        contact.why_relevant = candidate.why_relevant
        if "customer support" in candidate.role.casefold():
            contact.do_not_contact = True
    for item in candidate.channels:
        existing = await session.scalar(
            select(ContactChannel).where(
                ContactChannel.contact_id == contact.id,
                ContactChannel.channel_type == item.channel_type,
                ContactChannel.value == item.value,
            )
        )
        if existing is None:
            session.add(
                ContactChannel(
                    contact_id=contact.id,
                    channel_type=item.channel_type,
                    value=item.value,
                    url=item.url,
                    source_url=item.source_url,
                    source_type=item.source_type,
                    confidence=item.confidence,
                )
            )
    await session.flush()
    return contact


async def _legacy_channels(
    session: AsyncSession, contact: Contact, source: CompanySource | None
) -> None:
    source_url = source.url if source else contact.lawful_public_source_note
    if not source_url:
        return
    values = (
        ("email", contact.email, None),
        ("linkedin", contact.linkedin, contact.linkedin),
        ("telegram", contact.telegram, contact.telegram),
        ("official_form", contact.other_public_link, contact.other_public_link),
    )
    status = {
        "VERIFIED_CONTACT": "VERIFIED",
        "PARTIAL_CONTACT": "PARTIAL",
        "INVALID_CONTACT": "INVALID",
    }.get(contact.validation_status, "UNVERIFIED")
    for channel_type, value, url in values:
        if not value:
            continue
        existing = await session.scalar(
            select(ContactChannel).where(
                ContactChannel.contact_id == contact.id,
                ContactChannel.channel_type == channel_type,
                ContactChannel.value == value,
            )
        )
        if existing is None:
            session.add(
                ContactChannel(
                    contact_id=contact.id,
                    channel_type=channel_type,
                    value=value,
                    url=url,
                    source_url=source_url,
                    source_type="existing_verified_source",
                    confidence=float(contact.confidence or 0.7),
                    validation_status=status,
                    validated_at=contact.validated_at,
                    validation_http_status=contact.validation_http_status,
                    validation_final_url=contact.validation_final_url,
                    validation_error=contact.validation_error,
                )
            )
        elif status == "VERIFIED" and contact.validated_at is not None:
            existing.validation_status = "VERIFIED"
            existing.validated_at = contact.validated_at
            existing.validation_http_status = contact.validation_http_status
            existing.validation_final_url = contact.validation_final_url
            existing.validation_error = contact.validation_error


async def _normalize_generated_channel_ownership(
    session: AsyncSession, company: Company
) -> None:
    """Repair old grouped discovery channels without changing manual contact facts."""

    contacts = list(
        await session.scalars(
            select(Contact)
            .where(Contact.company_id == company.id)
            .options(selectinload(Contact.channels))
            .execution_options(populate_existing=True)
        )
    )
    official = next(
        (
            item
            for item in contacts
            if item.role == "Official company contact" and "Press" not in item.name
        ),
        None,
    )
    support = [item for item in contacts if item.do_not_contact]
    for owner in contacts:
        for channel in list(owner.channels):
            if channel.source_type not in {
                "official_site",
                "official_contact_probe",
                "public_search",
            }:
                continue
            target: Contact | None = None
            if channel.channel_type == "email":
                local_part = channel.value.split("@", maxsplit=1)[0].casefold()
                if local_part in {"help", "support", "ayuda"}:
                    target = next(
                        (item for item in support if item.email == channel.value),
                        support[0] if support else None,
                    )
            elif owner.role == "Official press channel" or "Press" in owner.name:
                target = official
            if target is None or target.id == owner.id:
                continue
            duplicate = next(
                (
                    item
                    for item in target.channels
                    if item.channel_type == channel.channel_type
                    and item.value == channel.value
                ),
                None,
            )
            if duplicate is not None:
                await session.delete(channel)
            else:
                channel.contact_id = target.id
    await session.flush()


async def discover_company_contacts(
    session: AsyncSession,
    company: Company,
    *,
    fetcher: SafeFetcher | None = None,
    searcher: PublicSearchResolver | None = None,
) -> DiscoveryReport:
    """Discover, validate, rank and persist public contact paths for one company."""

    fetcher = fetcher or SafeFetcher(
        respect_robots=True,
        max_bytes=1_500_000,
        timeout_seconds=5,
        minimum_host_interval=0.25,
    )
    searcher = searcher or PublicSearchResolver()
    company.contact_discovery_status = "in_progress"
    company.version += 1
    session.add(
        CommunicationEvent(
            company_id=company.id,
            event_type="contact_discovery_started",
            summary="Contact discovery started",
            metadata_json={},
        )
    )
    await session.commit()

    sources = list(
        await session.scalars(
            select(CompanySource)
            .where(CompanySource.company_id == company.id)
            .order_by(CompanySource.fetched_at.desc().nullslast())
            .limit(MAX_OFFICIAL_SOURCES)
        )
    )
    existing_contacts = list(
        await session.scalars(
            select(Contact)
            .where(Contact.company_id == company.id)
            .options(selectinload(Contact.channels))
        )
    )
    source_map = {item.id: item for item in sources}
    for contact in existing_contacts:
        source = source_map.get(contact.source_id) if contact.source_id else None
        await _legacy_channels(session, contact, source)
    await session.commit()

    candidates: list[ContactCandidate] = []
    search_errors: list[str] = []
    source_text_cache: dict[str, str] = {
        item.url: item.extracted_text or "" for item in sources
    }
    async def inspect_source(
        source: CompanySource,
    ) -> tuple[list[ContactCandidate], str | None]:
        try:
            document = await fetcher.fetch(source.url)
            source_text_cache[source.url] = document.body.decode(
                "utf-8", errors="replace"
            )
            return (
                _official_candidates(company, source, document.body, document.content_type),
                None,
            )
        except SafeFetchError as exc:
            return [], f"{source.url}: {exc.code}"

    for found, error in await asyncio.gather(*(inspect_source(source) for source in sources)):
        candidates.extend(found)
        if error:
            search_errors.append(error)

    known_urls = {item.url.rstrip("/") for item in sources}
    probe_sources = [
        CompanySource(
            company_id=company.id,
            url=f"https://{company.normalized_domain}/{path}",
            source_type="official_contact_probe",
        )
        for path in ("contact-us", "contact", "business")
        if f"https://{company.normalized_domain}/{path}".rstrip("/") not in known_urls
    ]
    for found, _ in await asyncio.gather(*(inspect_source(source) for source in probe_sources)):
        candidates.extend(found)

    opportunities = set(
        await session.scalars(
            select(CompanyOpportunity.opportunity_type).where(
                CompanyOpportunity.company_id == company.id,
                CompanyOpportunity.status != "rejected",
            )
        )
    )
    focus = "expansion business development operations"
    if opportunities.intersection({"ai_adoption", "process_automation"}):
        focus = "automation transformation operations AI"
    queries = (
        f'"{company.name}" founder CEO LinkedIn',
        f'"{company.name}" {focus} LinkedIn',
        f'"{company.name}" contact partnerships careers email',
        f'"{company.name}" Telegram WhatsApp Facebook business',
    )[:MAX_SEARCH_QUERIES]
    async def inspect_query(query: str) -> tuple[list[ContactCandidate], str | None]:
        try:
            found: list[ContactCandidate] = []
            for result in (await searcher.public_search(query))[:5]:
                candidate = _search_candidate(company, result)
                if candidate:
                    found.append(candidate)
            return found, None
        except Exception as exc:  # noqa: BLE001 - search failure must not discard official paths
            return [], f"public search: {type(exc).__name__}"

    for found, error in await asyncio.gather(*(inspect_query(query) for query in queries)):
        candidates.extend(found)
        if error:
            search_errors.append(error)

    for candidate in candidates:
        await _upsert_candidate(session, company, candidate)
    await _normalize_generated_channel_ownership(session, company)
    await session.commit()

    contacts = list(
        await session.scalars(
            select(Contact)
            .where(Contact.company_id == company.id)
            .options(selectinload(Contact.channels))
            .execution_options(populate_existing=True)
        )
    )
    pruned = False
    for contact in contacts:
        for channel in list(contact.channels):
            if (
                channel.channel_type == "official_form"
                and not _is_relevant_official_path(channel.url or channel.value)
                and contact.name.casefold().startswith(company.name.casefold())
            ):
                await session.delete(channel)
                pruned = True
    if pruned:
        await session.commit()
        contacts = list(
            await session.scalars(
                select(Contact)
                .where(Contact.company_id == company.id)
                .options(selectinload(Contact.channels))
                .execution_options(populate_existing=True)
            )
        )
    verified_channels = 0
    partial_channels = 0
    invalid_channels = 0
    validation_jobs: list[tuple[Contact, ContactChannel, ChannelCandidate]] = []
    for contact in contacts:
        for channel in contact.channels:
            if (
                channel.source_type == "existing_verified_source"
                and channel.validation_status == "VERIFIED"
                and channel.validated_at is not None
            ):
                verified_channels += 1
                continue
            candidate_channel = ChannelCandidate(
                channel_type=channel.channel_type,
                value=channel.value,
                url=channel.url,
                source_url=channel.source_url,
                source_type=channel.source_type,
                confidence=channel.confidence,
                source_text=next(
                    (
                        item.extracted_text or ""
                        for item in sources
                        if item.url == channel.source_url
                    ),
                    source_text_cache.get(channel.source_url, ""),
                ),
            )
            validation_jobs.append((contact, channel, candidate_channel))
    validations = await asyncio.gather(
        *(
            _validate_channel(candidate_channel, contact, company, fetcher)
            for contact, _, candidate_channel in validation_jobs
        )
    )
    for (_, channel, _), validation in zip(validation_jobs, validations, strict=True):
            channel.validation_status = validation["status"]
            channel.validated_at = validation["validated_at"]
            channel.validation_http_status = validation["http_status"]
            channel.validation_final_url = validation["final_url"]
            channel.validation_error = validation["error"]
            verified_channels += channel.validation_status == "VERIFIED"
            partial_channels += channel.validation_status == "PARTIAL"
            invalid_channels += channel.validation_status == "INVALID"
    for contact in contacts:
        valid = [item for item in contact.channels if item.validation_status == "VERIFIED"]
        if valid and not contact.do_not_contact:
            contact.validation_status = "VERIFIED_CONTACT"
            contact.verification_status = "verified_public"
            contact.validated_at = max(
                (item.validated_at for item in valid if item.validated_at),
                default=datetime.now(UTC),
            )
            contact.confidence = max(item.confidence for item in valid)
            best = valid[0]
            if best.channel_type == "email":
                email_owner = await session.scalar(
                    select(Contact.id).where(
                        Contact.company_id == company.id,
                        func.lower(Contact.email) == best.value.casefold(),
                        Contact.id != contact.id,
                    )
                )
                if email_owner is None:
                    contact.email = best.value
            elif best.channel_type == "linkedin":
                contact.linkedin = best.url or best.value
            elif best.channel_type == "telegram":
                contact.telegram = best.url or best.value
            elif best.channel_type in {"official_form", "facebook", "whatsapp"}:
                contact.other_public_link = best.url or best.value
        elif not contact.do_not_contact:
            contact.validation_status = (
                "PARTIAL_CONTACT"
                if any(item.validation_status == "PARTIAL" for item in contact.channels)
                else "UNVERIFIED_CONTACT"
            )

    for contact in contacts:
        classify_contact_for_outreach(contact, company.name)
        valid_count = min(
            2, sum(item.validation_status == "VERIFIED" for item in contact.channels)
        )
        partial_count = min(
            2, sum(item.validation_status == "PARTIAL" for item in contact.channels)
        )
        named = not contact.name.startswith(company.name) and "Public" not in contact.name
        contact.discovery_score = (
            _role_score(f"{contact.name} {contact.role or ''}", opportunities)
            + valid_count * 50
            + partial_count * 8
            + (12 if named else 0)
            - (200 if contact.do_not_contact else 0)
        )
        if not contact.why_relevant:
            contact.why_relevant = f"Public path for {contact.role or 'company contact'}"
    ranked = sorted(
        (
            item
            for item in contacts
            if not item.do_not_contact
            and any(channel.validation_status != "INVALID" for channel in item.channels)
        ),
        key=lambda item: item.discovery_score or 0,
        reverse=True,
    )
    for contact in contacts:
        contact.rank_label = None
    labels = ("primary", "secondary", "alternative", "alternative", "alternative")
    for contact, label in zip(ranked[:MAX_CONTACTS_SHOWN], labels, strict=False):
        contact.rank_label = label

    actionable = any(
        not item.do_not_contact
        and any(channel.validation_status == "VERIFIED" for channel in item.channels)
        for item in contacts
    )
    company.contact_discovery_status = "completed" if actionable else "contact_not_found"
    company.contact_discovered_at = datetime.now(UTC)
    company.version += 1
    session.add(
        CommunicationEvent(
            company_id=company.id,
            event_type="contact_discovery_completed",
            summary=(
                f"Contact discovery completed: {len(ranked)} candidates, "
                f"{verified_channels} verified channels"
            ),
            metadata_json={
                "candidates": len(ranked),
                "verified_channels": verified_channels,
                "partial_channels": partial_channels,
                "invalid_channels": invalid_channels,
                "search_errors": search_errors,
            },
        )
    )
    await session.commit()
    return DiscoveryReport(
        company_id=company.id,
        status=company.contact_discovery_status,
        candidates=len(ranked),
        verified_channels=verified_channels,
        partial_channels=partial_channels,
        invalid_channels=invalid_channels,
        search_errors=tuple(search_errors),
    )
