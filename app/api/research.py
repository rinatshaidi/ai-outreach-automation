"""Safe, provenance-first company research API."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, cast
from urllib.parse import urljoin, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import add_event, ensure_version
from app.infrastructure.db.session import get_db_session
from app.modules.crm.models import Company, CompanySource, Contact
from app.modules.opportunities.models import CompanyOpportunity, OpportunitySignal
from app.modules.research.extraction import extract_research
from app.modules.research.fetcher import SafeFetcher, SafeFetchError, normalize_public_url
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis, ResearchRun
from app.modules.research.schemas import (
    CompanyFactRead,
    CompanyFactUpdate,
    CompanyTaskHypothesisRead,
    CompanyTaskHypothesisUpdate,
    ResearchRequest,
    ResearchResult,
    ResearchRunRead,
)

router = APIRouter(prefix="/api/v1/companies/{company_id}/research", tags=["research"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_safe_fetcher() -> SafeFetcher:
    return SafeFetcher()


Fetcher = Annotated[SafeFetcher, Depends(get_safe_fetcher)]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def require_company(session: AsyncSession, company_id: UUID) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise api_error(404, "company_not_found", "Company was not found")
    return company


@router.get("/runs", response_model=list[ResearchRunRead])
async def list_research_runs(company_id: UUID, session: DbSession) -> list[ResearchRun]:
    await require_company(session, company_id)
    return list(
        await session.scalars(
            select(ResearchRun)
            .where(ResearchRun.company_id == company_id)
            .order_by(ResearchRun.started_at.desc())
        )
    )


@router.get("/facts", response_model=list[CompanyFactRead])
async def list_company_facts(company_id: UUID, session: DbSession) -> list[CompanyFact]:
    await require_company(session, company_id)
    return list(
        await session.scalars(
            select(CompanyFact)
            .where(CompanyFact.company_id == company_id)
            .order_by(CompanyFact.created_at.desc())
        )
    )


@router.patch("/facts/{fact_id}", response_model=CompanyFactRead)
async def update_company_fact(
    company_id: UUID,
    fact_id: UUID,
    payload: CompanyFactUpdate,
    session: DbSession,
) -> CompanyFact:
    fact = cast(CompanyFact | None, await session.get(CompanyFact, fact_id))
    if fact is None or fact.company_id != company_id:
        raise api_error(404, "fact_not_found", "Company fact was not found")
    ensure_version(fact.version, payload.version)
    for key, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(fact, key, getattr(value, "value", value))
    fact.version += 1
    await session.commit()
    await session.refresh(fact)
    return fact


@router.get("/hypotheses", response_model=list[CompanyTaskHypothesisRead])
async def list_task_hypotheses(company_id: UUID, session: DbSession) -> list[CompanyTaskHypothesis]:
    await require_company(session, company_id)
    return list(
        await session.scalars(
            select(CompanyTaskHypothesis)
            .where(CompanyTaskHypothesis.company_id == company_id)
            .order_by(CompanyTaskHypothesis.created_at.desc())
        )
    )


@router.patch("/hypotheses/{hypothesis_id}", response_model=CompanyTaskHypothesisRead)
async def update_task_hypothesis(
    company_id: UUID,
    hypothesis_id: UUID,
    payload: CompanyTaskHypothesisUpdate,
    session: DbSession,
) -> CompanyTaskHypothesis:
    hypothesis = cast(
        CompanyTaskHypothesis | None,
        await session.get(CompanyTaskHypothesis, hypothesis_id),
    )
    if hypothesis is None or hypothesis.company_id != company_id:
        raise api_error(404, "hypothesis_not_found", "Task hypothesis was not found")
    ensure_version(hypothesis.version, payload.version)
    hypothesis.status = payload.status.value
    hypothesis.version += 1
    await session.commit()
    await session.refresh(hypothesis)
    return hypothesis


@router.post("", response_model=ResearchResult, status_code=status.HTTP_201_CREATED)
async def run_research(
    company_id: UUID,
    payload: ResearchRequest,
    request: Request,
    session: DbSession,
    fetcher: Fetcher,
) -> ResearchResult:
    company = await require_company(session, company_id)
    raw_url = str(payload.url)
    try:
        normalized_url = normalize_public_url(raw_url)
    except SafeFetchError as exc:
        raise api_error(422, exc.code, str(exc)) from exc

    run = ResearchRun(
        company_id=company_id,
        requested_url=raw_url,
        normalized_url=normalized_url,
        status="fetching",
    )
    session.add(run)
    old_status = company.pipeline_status
    if old_status == "new":
        company.pipeline_status = "research_pending"
        company.version += 1
    add_event(
        session,
        company_id=company_id,
        event_type="research_started",
        summary=f"Research started for {normalized_url}",
        metadata={"url": normalized_url},
    )
    await session.commit()
    await session.refresh(run)

    try:
        document = await fetcher.fetch(normalized_url)
        extracted = extract_research(document.body, document.content_type)
    except (SafeFetchError, ValueError) as exc:
        code = exc.code if isinstance(exc, SafeFetchError) else "text_extraction_failed"
        run.status = (
            "blocked"
            if code
            in {
                "private_address",
                "robots_denied",
                "invalid_scheme",
                "userinfo_forbidden",
                "port_forbidden",
            }
            else "failed"
        )
        run.error_code = code
        run.error_message = str(exc)[:500]
        run.completed_at = datetime.now(UTC)
        add_event(
            session,
            company_id=company_id,
            event_type="research_blocked" if run.status == "blocked" else "research_failed",
            summary=f"Research stopped safely: {code}",
        )
        await session.commit()
        raise api_error(422 if run.status == "blocked" else 502, code, str(exc)) from exc

    content_hash = sha256(document.body).hexdigest()
    source = await session.scalar(
        select(CompanySource).where(
            CompanySource.company_id == company_id,
            CompanySource.url == document.final_url,
        )
    )
    if source is None:
        source = CompanySource(
            company_id=company_id,
            url=document.final_url,
            source_type="manual_research",
        )
        session.add(source)
        await session.flush()
    source.fetched_at = datetime.now(UTC)
    source.http_status = document.status_code
    source.content_hash = content_hash
    source.extracted_text = extracted.text
    source.language = extracted.language
    source.freshness_status = "current"
    source.error = None
    source.version += 1

    facts: list[CompanyFact] = []
    for fact_candidate in extracted.facts:
        fact = await session.scalar(
            select(CompanyFact).where(
                CompanyFact.company_id == company_id,
                CompanyFact.source_id == source.id,
                CompanyFact.fact_type == fact_candidate.fact_type,
                CompanyFact.value == fact_candidate.value,
            )
        )
        if fact is None:
            fact = CompanyFact(
                company_id=company_id,
                source_id=source.id,
                fact_type=fact_candidate.fact_type,
                value=fact_candidate.value,
                confidence=fact_candidate.confidence,
                exact_fragment=fact_candidate.exact_fragment,
                status="extracted",
            )
            session.add(fact)
        facts.append(fact)

    signals: list[OpportunitySignal] = []
    for signal_candidate in extracted.signals:
        signal = await session.scalar(
            select(OpportunitySignal).where(
                OpportunitySignal.company_id == company_id,
                OpportunitySignal.source_id == source.id,
                OpportunitySignal.signal_type == signal_candidate.signal_type.value,
                OpportunitySignal.exact_fragment == signal_candidate.exact_fragment,
            )
        )
        if signal is None:
            signal = OpportunitySignal(
                company_id=company_id,
                source_id=source.id,
                signal_type=signal_candidate.signal_type.value,
                title=signal_candidate.title,
                description=signal_candidate.description,
                detected_at=datetime.now(UTC),
                confidence=signal_candidate.confidence,
                exact_fragment=signal_candidate.exact_fragment,
                status="extracted",
            )
            session.add(signal)
            await session.flush()
        signals.append(signal)

    opportunities: list[CompanyOpportunity] = []
    for opportunity_type in extracted.opportunity_types:
        opportunity = await session.scalar(
            select(CompanyOpportunity).where(
                CompanyOpportunity.company_id == company_id,
                CompanyOpportunity.opportunity_type == opportunity_type.value,
            )
        )
        relevant_signal_ids = [
            str(item.id)
            for item in signals
            if item.signal_type == opportunity_type.value
            or opportunity_type.value in {"business_expansion", "new_product_or_direction"}
        ]
        if opportunity is None:
            opportunity = CompanyOpportunity(
                company_id=company_id,
                opportunity_type=opportunity_type.value,
                source_ids=[str(source.id)],
                signal_ids=relevant_signal_ids,
                rationale="Proposed by deterministic research rules; owner review is required.",
                confidence=0.45 if relevant_signal_ids else 0.25,
                status="proposed",
            )
            session.add(opportunity)
            await session.flush()
        opportunities.append(opportunity)

    contacts: list[Contact] = []
    for email in extracted.public_emails:
        contact = await session.scalar(
            select(Contact).where(Contact.company_id == company_id, Contact.email == email)
        )
        if contact is None:
            is_careers = email.split("@", maxsplit=1)[0] in {
                "career",
                "careers",
                "jobs",
                "recruiting",
                "talent",
            }
            contact = Contact(
                company_id=company_id,
                name="Public careers contact" if is_careers else "Public company contact",
                role="Careers" if is_careers else "Public contact",
                email=email,
                decision_maker_role="talent_acquisition" if is_careers else None,
                decision_priority=2 if is_careers else None,
                source_id=source.id,
                verification_status="unverified",
                confidence=0.5,
                lawful_public_source_note=f"Public mailto link on {document.final_url}",
            )
            session.add(contact)
        contacts.append(contact)

    hypotheses: list[CompanyTaskHypothesis] = []
    for hypothesis_candidate in extracted.hypotheses:
        hypothesis = await session.scalar(
            select(CompanyTaskHypothesis).where(
                CompanyTaskHypothesis.company_id == company_id,
                CompanyTaskHypothesis.title == hypothesis_candidate.title,
            )
        )
        if hypothesis is None:
            hypothesis = CompanyTaskHypothesis(
                company_id=company_id,
                source_ids=[str(source.id)],
                title=hypothesis_candidate.title,
                description=hypothesis_candidate.description,
                rationale=hypothesis_candidate.rationale,
                confidence=hypothesis_candidate.confidence,
                status="hypothesis",
                risks=hypothesis_candidate.risks,
            )
            session.add(hypothesis)
        hypotheses.append(hypothesis)

    await session.flush()
    company.language_signals = list(dict.fromkeys([*company.language_signals, extracted.language]))
    company.opportunity_types = list(
        dict.fromkeys(
            [*company.opportunity_types, *(item.value for item in extracted.opportunity_types)]
        )
    )
    if not company.description:
        company.description = extracted.text[:2000]
    company.last_researched_at = datetime.now(UTC)
    company.pipeline_status = "researched"
    company.version += 1
    run.source_id = source.id
    run.status = "completed"
    run.content_type = document.content_type
    run.content_bytes = len(document.body)
    run.language = extracted.language
    run.redirect_chain = document.redirect_chain
    run.result_summary = {
        "facts": len(facts),
        "signals": len(signals),
        "opportunities": len(opportunities),
        "hypotheses": len(hypotheses),
        "public_contacts": len(contacts),
        "research_links": [
            link
            for link in dict.fromkeys(
                urljoin(document.final_url, value) for value in extracted.public_links
            )
            if urlparse(link).hostname == urlparse(document.final_url).hostname
            and any(
                marker in urlparse(link).path.casefold()
                for marker in (
                    "about",
                    "company",
                    "contact",
                    "career",
                    "job",
                    "news",
                    "blog",
                    "leadership",
                    "team",
                )
            )
        ][:20],
        "request_id": str(getattr(request.state, "request_id", "missing-request-id")),
    }
    run.completed_at = datetime.now(UTC)
    add_event(
        session,
        company_id=company_id,
        event_type="research_completed",
        summary=(
            f"Research completed: {len(facts)} facts, {len(signals)} signals, "
            f"{len(hypotheses)} hypotheses, {len(contacts)} public contacts"
        ),
        metadata={"source_id": str(source.id), "content_hash": content_hash},
    )
    await session.commit()
    for item in [run, *facts, *hypotheses]:
        await session.refresh(item)
    return ResearchResult(
        run=ResearchRunRead.model_validate(run),
        facts=[CompanyFactRead.model_validate(item) for item in facts],
        hypotheses=[CompanyTaskHypothesisRead.model_validate(item) for item in hypotheses],
        signal_ids=[item.id for item in signals],
        opportunity_ids=[item.id for item in opportunities],
    )
