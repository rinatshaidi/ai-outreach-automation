"""SSRF-safe validation of public contact URLs before outreach readiness."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.modules.crm.models import Company, Contact
from app.modules.crm.schemas import ContactValidationStatus
from app.modules.research.fetcher import SafeFetcher, SafeFetchError, normalize_public_url

SOFT_404_MARKERS = (
    "404",
    "page not found",
    "not found",
    "page doesn't exist",
    "page does not exist",
    "something went wrong",
    "generic error",
)
IGNORED_IDENTITY_TOKENS = {
    "and",
    "business",
    "company",
    "contact",
    "cofounder",
    "co-founder",
    "official",
    "path",
    "public",
    "sales",
    "support",
    "team",
}


def _contact_role_text(contact: Contact) -> str:
    return " ".join(
        value
        for value in (
            contact.name,
            contact.role,
            (contact.email or "").split("@", maxsplit=1)[0],
        )
        if value
    ).casefold()


def _is_named_person(contact: Contact, company_label: str) -> bool:
    """Conservative check: a general team/page must never become a person."""

    name = (contact.name or "").strip()
    lowered = name.casefold()
    if not name or lowered.startswith(company_label.casefold()):
        return False
    generic = {
        "team", "contact", "official", "company", "public", "sales", "support",
        "careers", "hiring", "talent", "hr", "press", "media", "office",
        "команда", "контакт", "компания", "отдел", "поддержка", "вакансии",
        "карьера", "пресса",
    }
    tokens = re.findall(r"[\w'-]+", lowered)
    return len(tokens) >= 2 and not any(token in generic for token in tokens)


class ContactValidationResult(BaseModel):
    status: ContactValidationStatus
    validated_at: datetime
    requested_url: str
    final_url: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    redirect_chain: list[str] = Field(default_factory=list)
    identity_match: bool = False
    error: str | None = None


def contact_url(contact: Contact) -> str | None:
    return contact.linkedin or contact.other_public_link


def classify_contact_for_outreach(
    contact: Contact, company_name: str | None = None
) -> None:
    """Classify a public contact into an explicit owner-facing recipient category.

    The category records only what the public source supports: named leaders,
    hiring teams, business teams, official company channels or non-outreach
    channels.  It never implies that a generic mailbox belongs to a person.
    """

    company_label = company_name or "Company"
    role_text = _contact_role_text(contact)
    named_person = _is_named_person(contact, company_label)
    if any(
        token in role_text
        for token in ("support", "help", "customer care", "ayuda", "поддержк")
    ):
        contact.decision_maker_role = None
        contact.decision_priority = 2
        contact.do_not_contact = True
        contact.why_relevant = "Customer support channel; not an outreach recipient"
    elif any(
        token in role_text
        for token in (
            "recruit",
            "talent",
            "hiring",
            "career",
            "jobs",
            "hr",
            "рекрут",
            "ваканс",
            "кадр",
        )
    ):
        contact.decision_maker_role = "talent_acquisition"
        contact.decision_priority = 1
        contact.why_relevant = (
            "Named recruiter with a public professional channel"
            if named_person
            else "Official hiring or recruitment channel; no named recipient confirmed"
        )
    elif named_person and any(
        token in role_text for token in ("founder", "co-founder", "cofounder", "основател")
    ):
        contact.decision_maker_role = "founder"
        contact.decision_priority = 1
        contact.why_relevant = "Named founder or co-founder with a public professional channel"
    elif named_person and any(
        token in role_text
        for token in ("chief executive", " ceo", "ceo ", "managing director", "генеральн")
    ):
        contact.decision_maker_role = "ceo"
        contact.decision_priority = 1
        contact.why_relevant = "Named executive decision-maker with a public professional channel"
    elif named_person and any(
        token in role_text
        for token in (
            "business development",
            "partnership",
            "partnerships",
            "развитие бизнеса",
            "партнерств",
        )
    ):
        contact.decision_maker_role = "head_of_business_development"
        contact.decision_priority = 1
        contact.why_relevant = "Named business-development or partnership contact"
    elif named_person and any(
        token in role_text
        for token in ("operations", "chief operating", " coo", "coo ", "операц")
    ):
        contact.decision_maker_role = "head_of_operations"
        contact.decision_priority = 1
        contact.why_relevant = "Named operations or project contact"
    elif any(token in role_text for token in ("press", "media", "communications")):
        contact.decision_maker_role = None
        contact.decision_priority = 2
        contact.why_relevant = "Official media channel; not the preferred outreach recipient"
    else:
        contact.decision_maker_role = None
        contact.decision_priority = 2
        contact.why_relevant = (
            "Named person, but their decision-making role is not confirmed"
            if named_person
            else "Official public company channel; no named recipient is confirmed"
        )


def _page_text(body: bytes) -> str:
    return re.sub(r"\s+", " ", body.decode("utf-8", errors="replace")).casefold()


def _looks_like_soft_404(text: str) -> bool:
    head = text[:5000]
    return any(marker in head for marker in SOFT_404_MARKERS)


def _identity_tokens(contact: Contact, company: Company) -> set[str]:
    host_label = company.normalized_domain.split(".", maxsplit=1)[0].casefold()
    raw = f"{contact.name} {contact.role or ''} {host_label}".casefold()
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", raw)
        if token not in IGNORED_IDENTITY_TOKENS
    }


async def validate_contact_path(
    contact: Contact,
    company: Company,
    *,
    fetcher: SafeFetcher | None = None,
    source_url: str | None = None,
    source_text: str | None = None,
    source_http_status: int | None = None,
) -> ContactValidationResult:
    now = datetime.now(UTC)
    raw_url = contact_url(contact) or source_url
    if not raw_url:
        return ContactValidationResult(
            status=ContactValidationStatus.UNVERIFIED,
            validated_at=now,
            requested_url=contact.email or contact.telegram or "missing",
            error="Automated HTTP validation requires a public HTTP/HTTPS URL",
        )
    try:
        normalized = normalize_public_url(raw_url)
    except SafeFetchError as exc:
        return ContactValidationResult(
            status=ContactValidationStatus.INVALID,
            validated_at=now,
            requested_url=raw_url,
            error=f"{exc.code}: {exc}",
        )

    validator = fetcher or SafeFetcher(respect_robots=False, max_bytes=500_000)
    try:
        document = await validator.fetch(normalized)
    except SafeFetchError as exc:
        cached_email_match = bool(
            contact.email
            and source_url
            and source_text
            and contact.email.casefold() in source_text.casefold()
            and source_http_status is not None
            and 200 <= source_http_status < 300
        )
        if exc.code == "content_too_large" and cached_email_match:
            return ContactValidationResult(
                status=ContactValidationStatus.VERIFIED,
                validated_at=now,
                requested_url=normalized,
                final_url=source_url,
                http_status=source_http_status,
                identity_match=True,
            )
        match = re.search(r"HTTP (\d{3})", str(exc))
        http_status = int(match.group(1)) if match else None
        invalid = http_status in {404, 410} or exc.code in {
            "invalid_scheme",
            "missing_hostname",
            "invalid_hostname",
            "invalid_port",
            "private_address",
            "userinfo_forbidden",
            "port_forbidden",
        }
        return ContactValidationResult(
            status=(
                ContactValidationStatus.INVALID
                if invalid
                else ContactValidationStatus.UNVERIFIED
            ),
            validated_at=now,
            requested_url=normalized,
            http_status=http_status,
            error=f"{exc.code}: {exc}",
        )

    text = _page_text(document.body)
    if _looks_like_soft_404(text):
        return ContactValidationResult(
            status=ContactValidationStatus.INVALID,
            validated_at=now,
            requested_url=normalized,
            final_url=document.final_url,
            http_status=document.status_code,
            redirect_chain=document.redirect_chain,
            error="soft_404: page content looks like a missing or generic error page",
        )
    tokens = _identity_tokens(contact, company)
    host = urlsplit(document.final_url).hostname or ""
    same_company_host = company.normalized_domain in host or host.endswith(
        f".{company.normalized_domain}"
    )
    email_match = bool(contact.email and contact.email.casefold() in text)
    # A stored provenance URL may live on an official careers/press domain that differs
    # from the company's canonical product domain. In that case the exact public email
    # must still be present on the fetched page; a merely reachable page is not enough.
    provenance_email_match = bool(source_url and email_match)
    identity_match = (
        same_company_host and (email_match or any(token in text for token in tokens))
    ) or provenance_email_match
    return ContactValidationResult(
        status=(
            ContactValidationStatus.VERIFIED
            if identity_match
            else ContactValidationStatus.PARTIAL
        ),
        validated_at=now,
        requested_url=normalized,
        final_url=document.final_url,
        http_status=document.status_code,
        redirect_chain=document.redirect_chain,
        identity_match=identity_match,
        error=None if identity_match else "Page exists, but contact identity was not confirmed",
    )
