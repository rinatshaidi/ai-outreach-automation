"""REST API for the Mini-CRM core."""

from datetime import UTC, datetime
from math import ceil
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.db.session import get_db_session
from app.modules.crm.contact_validation import (
    classify_contact_for_outreach,
    validate_contact_path,
)
from app.modules.crm.models import (
    Campaign,
    CommunicationEvent,
    Company,
    CompanySource,
    Contact,
    ContactChannel,
    JobOpening,
)
from app.modules.crm.pipeline import transition_is_allowed
from app.modules.crm.schemas import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    CompanyCreate,
    CompanyPage,
    CompanyRead,
    CompanyUpdate,
    ContactCreate,
    ContactRead,
    ContactUpdate,
    ContactValidationStatus,
    DashboardSummary,
    JobCreate,
    JobRead,
    JobUpdate,
    PageMeta,
    PipelineStatus,
    TimelineEventCreate,
    TimelineEventRead,
    VerificationStatus,
)
from app.modules.followups.models import FollowUp
from app.modules.followups.service import cancel_open_followups
from app.modules.research.fetcher import SafeFetcher

router = APIRouter(prefix="/api/v1", tags=["mini-crm"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_contact_validator() -> SafeFetcher:
    return SafeFetcher(respect_robots=False, max_bytes=500_000)


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def normalize_payload(values: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if hasattr(value, "value"):
            normalized[key] = value.value
        elif isinstance(value, list):
            normalized[key] = [getattr(item, "value", item) for item in value]
        elif key in {
            "linkedin",
            "other_public_link",
            "url",
            "validation_final_url",
        } and value is not None:
            normalized[key] = str(value)
        else:
            normalized[key] = value
    return normalized


def ensure_version(actual: int, supplied: int) -> None:
    if actual != supplied:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "version_conflict",
            "The record changed after it was loaded; refresh and try again",
        )


async def require_entity[ModelT: (Company, Contact, JobOpening, Campaign)](
    session: AsyncSession, model: type[ModelT], entity_id: UUID
) -> ModelT:
    entity = await session.get(model, entity_id)
    if entity is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found", "The record was not found")
    return entity


def add_event(
    session: AsyncSession,
    *,
    company_id: UUID,
    event_type: str,
    summary: str,
    contact_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> None:
    session.add(
        CommunicationEvent(
            company_id=company_id,
            contact_id=contact_id,
            event_type=event_type,
            summary=summary,
            metadata_json=metadata or {},
            occurred_at=occurred_at or datetime.now(UTC),
        )
    )


async def commit_or_conflict(session: AsyncSession, code: str, message: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise api_error(status.HTTP_409_CONFLICT, code, message) from exc


@router.get("/companies", response_model=CompanyPage)
async def list_companies(
    session: DbSession,
    q: str | None = Query(default=None, max_length=200),
    pipeline_status: PipelineStatus | None = None,
    country: str | None = Query(default=None, max_length=120),
    sort: str = Query(default="updated_desc", pattern="^(updated_desc|updated_asc|name|score)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> CompanyPage:
    filters: list[Any] = []
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(or_(Company.name.ilike(pattern), Company.normalized_domain.ilike(pattern)))
    if pipeline_status:
        filters.append(Company.pipeline_status == pipeline_status.value)
    if country:
        filters.append(Company.country == country)

    total = int(await session.scalar(select(func.count(Company.id)).where(*filters)) or 0)
    order: ColumnElement[Any]
    if sort == "updated_asc":
        order = Company.updated_at.asc()
    elif sort == "name":
        order = Company.name.asc()
    elif sort == "score":
        order = Company.relevance_score.desc().nullslast()
    else:
        order = Company.updated_at.desc()
    result = await session.scalars(
        select(Company)
        .where(*filters)
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return CompanyPage(
        items=list(result),
        meta=PageMeta(page=page, page_size=page_size, total=total, pages=ceil(total / page_size)),
    )


@router.post("/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(payload: CompanyCreate, session: DbSession) -> Company:
    company = Company(id=uuid4(), **normalize_payload(payload.model_dump()))
    session.add(company)
    add_event(
        session,
        company_id=company.id,
        event_type="company_created",
        summary="Company added to the CRM",
    )
    await commit_or_conflict(session, "domain_exists", "A company with this domain already exists")
    await session.refresh(company)
    return company


@router.get("/companies/{company_id}", response_model=CompanyRead)
async def read_company(company_id: UUID, session: DbSession) -> Company:
    return await require_entity(session, Company, company_id)


@router.patch("/companies/{company_id}", response_model=CompanyRead)
async def update_company(company_id: UUID, payload: CompanyUpdate, session: DbSession) -> Company:
    company = await require_entity(session, Company, company_id)
    ensure_version(company.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    old_status = company.pipeline_status
    if "pipeline_status" in changes and changes["pipeline_status"] != old_status:
        current = PipelineStatus(old_status)
        target = PipelineStatus(changes["pipeline_status"])
        if not transition_is_allowed(current, target):
            raise api_error(
                status.HTTP_409_CONFLICT,
                "invalid_pipeline_transition",
                f"Pipeline cannot move directly from {current.value} to {target.value}",
            )
    for key, value in changes.items():
        setattr(company, key, value)
    company.version += 1
    if "pipeline_status" in changes and company.pipeline_status != old_status:
        add_event(
            session,
            company_id=company.id,
            event_type="pipeline_changed",
            summary=f"Pipeline status changed: {old_status} → {company.pipeline_status}",
            metadata={"from": old_status, "to": company.pipeline_status},
        )
        if company.pipeline_status in {
            "replied",
            "interview",
            "project_discussion",
            "consulting_discussion",
            "rejected",
            "offer",
            "agreement",
            "closed",
        }:
            await cancel_open_followups(
                session,
                company_id=company.id,
                reason=f"company_status_{company.pipeline_status}",
                request_id="company-status-update",
            )
    else:
        add_event(
            session,
            company_id=company.id,
            event_type="company_updated",
            summary="Company details updated",
        )
    await commit_or_conflict(session, "company_conflict", "Company data conflicts with a record")
    await session.refresh(company)
    return company


@router.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: UUID, version: int, session: DbSession) -> Response:
    company = await require_entity(session, Company, company_id)
    ensure_version(company.version, version)
    await session.delete(company)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/contacts", response_model=list[ContactRead])
async def list_contacts(
    session: DbSession,
    company_id: UUID | None = None,
    verification_status: VerificationStatus | None = None,
    q: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[Contact]:
    query: Select[tuple[Contact]] = select(Contact)
    if company_id:
        query = query.where(Contact.company_id == company_id)
    if verification_status:
        query = query.where(Contact.verification_status == verification_status.value)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(Contact.name.ilike(pattern), Contact.email.ilike(pattern)))
    return list(
        await session.scalars(query.order_by(Contact.updated_at.desc()).offset(offset).limit(limit))
    )


@router.post("/contacts", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact(payload: ContactCreate, session: DbSession) -> Contact:
    await require_entity(session, Company, payload.company_id)
    contact = Contact(id=uuid4(), **normalize_payload(payload.model_dump()))
    session.add(contact)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise api_error(
            status.HTTP_409_CONFLICT,
            "contact_exists",
            "This email already exists for the company",
        ) from exc
    add_event(
        session,
        company_id=contact.company_id,
        contact_id=contact.id,
        event_type="contact_added",
        summary=f"Contact added: {contact.name}",
    )
    await session.commit()
    await session.refresh(contact)
    return contact


@router.get("/contacts/{contact_id}", response_model=ContactRead)
async def read_contact(contact_id: UUID, session: DbSession) -> Contact:
    return await require_entity(session, Contact, contact_id)


@router.patch("/contacts/{contact_id}", response_model=ContactRead)
async def update_contact(contact_id: UUID, payload: ContactUpdate, session: DbSession) -> Contact:
    contact = await require_entity(session, Contact, contact_id)
    ensure_version(contact.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    for key, value in changes.items():
        setattr(contact, key, value)
    contact.version += 1
    if contact.do_not_contact or contact.verification_status == "suppressed":
        await cancel_open_followups(
            session,
            contact_id=contact.id,
            reason="contact_suppressed",
            request_id="contact-update",
        )
    add_event(
        session,
        company_id=contact.company_id,
        contact_id=contact.id,
        event_type="contact_updated",
        summary=f"Contact updated: {contact.name}",
    )
    await commit_or_conflict(session, "contact_conflict", "Contact data conflicts with a record")
    await session.refresh(contact)
    return contact


@router.post("/contacts/{contact_id}/validate", response_model=ContactRead)
async def validate_contact(
    contact_id: UUID,
    session: DbSession,
    fetcher: Annotated[SafeFetcher, Depends(get_contact_validator)],
) -> Contact:
    contact = await require_entity(session, Contact, contact_id)
    company = await require_entity(session, Company, contact.company_id)
    source = await session.get(CompanySource, contact.source_id) if contact.source_id else None
    result = await validate_contact_path(
        contact,
        company,
        fetcher=fetcher,
        source_url=source.url if source is not None else None,
        source_text=source.extracted_text if source is not None else None,
        source_http_status=source.http_status if source is not None else None,
    )
    contact.validation_status = result.status.value
    contact.validated_at = result.validated_at
    contact.validation_http_status = result.http_status
    contact.validation_final_url = result.final_url
    contact.validation_error = result.error
    if result.status == ContactValidationStatus.INVALID:
        contact.verification_status = VerificationStatus.INVALID.value
    elif (
        result.status == ContactValidationStatus.VERIFIED
        and contact.verification_status == VerificationStatus.UNVERIFIED.value
        and (contact.source_id or contact.lawful_public_source_note)
    ):
        contact.verification_status = VerificationStatus.VERIFIED_PUBLIC.value
    if result.status == ContactValidationStatus.VERIFIED:
        classify_contact_for_outreach(contact, company.name)
        if contact.email:
            email_channels = list(
                await session.scalars(
                    select(ContactChannel).where(
                        ContactChannel.contact_id == contact.id,
                        func.lower(ContactChannel.value) == contact.email.casefold(),
                    )
                )
            )
            for channel in email_channels:
                channel.validation_status = "VERIFIED"
                channel.validated_at = result.validated_at
                channel.validation_http_status = result.http_status
                channel.validation_final_url = result.final_url
                channel.validation_error = None
    contact.version += 1
    add_event(
        session,
        company_id=contact.company_id,
        contact_id=contact.id,
        event_type="contact_path_validated",
        summary=f"Contact validation: {result.status.value}",
        metadata={
            "http_status": result.http_status,
            "final_url": result.final_url,
            "validated_at": result.validated_at.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(contact)
    return contact


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(contact_id: UUID, version: int, session: DbSession) -> Response:
    contact = await require_entity(session, Contact, contact_id)
    ensure_version(contact.version, version)
    await session.delete(contact)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/jobs", response_model=list[JobRead])
async def list_jobs(
    session: DbSession,
    company_id: UUID | None = None,
    active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[JobOpening]:
    query: Select[tuple[JobOpening]] = select(JobOpening)
    if company_id:
        query = query.where(JobOpening.company_id == company_id)
    if active is not None:
        query = query.where(JobOpening.active == active)
    return list(
        await session.scalars(
            query.order_by(JobOpening.updated_at.desc()).offset(offset).limit(limit)
        )
    )


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, session: DbSession) -> JobOpening:
    await require_entity(session, Company, payload.company_id)
    job = JobOpening(id=uuid4(), **normalize_payload(payload.model_dump()))
    session.add(job)
    add_event(
        session,
        company_id=job.company_id,
        event_type="job_added",
        summary=f"Job added: {job.title}",
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=JobRead)
async def read_job(job_id: UUID, session: DbSession) -> JobOpening:
    return await require_entity(session, JobOpening, job_id)


@router.patch("/jobs/{job_id}", response_model=JobRead)
async def update_job(job_id: UUID, payload: JobUpdate, session: DbSession) -> JobOpening:
    job = await require_entity(session, JobOpening, job_id)
    ensure_version(job.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    for key, value in changes.items():
        setattr(job, key, value)
    job.version += 1
    add_event(
        session,
        company_id=job.company_id,
        event_type="job_updated",
        summary=f"Job updated: {job.title}",
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: UUID, version: int, session: DbSession) -> Response:
    job = await require_entity(session, JobOpening, job_id)
    ensure_version(job.version, version)
    await session.delete(job)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/campaigns", response_model=list[CampaignRead])
async def list_campaigns(
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status", max_length=30),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[Campaign]:
    query: Select[tuple[Campaign]] = select(Campaign)
    if status_filter:
        query = query.where(Campaign.status == status_filter)
    return list(
        await session.scalars(
            query.order_by(Campaign.updated_at.desc()).offset(offset).limit(limit)
        )
    )


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CampaignCreate, session: DbSession) -> Campaign:
    campaign = Campaign(**normalize_payload(payload.model_dump()))
    session.add(campaign)
    await commit_or_conflict(session, "campaign_exists", "A campaign with this name already exists")
    await session.refresh(campaign)
    return campaign


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
async def read_campaign(campaign_id: UUID, session: DbSession) -> Campaign:
    return await require_entity(session, Campaign, campaign_id)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignRead)
async def update_campaign(
    campaign_id: UUID, payload: CampaignUpdate, session: DbSession
) -> Campaign:
    campaign = await require_entity(session, Campaign, campaign_id)
    ensure_version(campaign.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    for key, value in changes.items():
        setattr(campaign, key, value)
    campaign.version += 1
    if campaign.status != "active":
        await cancel_open_followups(
            session,
            campaign_id=campaign.id,
            reason=f"campaign_{campaign.status}",
            request_id="campaign-update",
        )
    await commit_or_conflict(session, "campaign_conflict", "Campaign data conflicts with a record")
    await session.refresh(campaign)
    return campaign


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: UUID, version: int, session: DbSession) -> Response:
    campaign = await require_entity(session, Campaign, campaign_id)
    ensure_version(campaign.version, version)
    await session.delete(campaign)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/communications", response_model=list[TimelineEventRead])
async def list_timeline(
    session: DbSession,
    company_id: UUID | None = None,
    event_type: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[CommunicationEvent]:
    query: Select[tuple[CommunicationEvent]] = select(CommunicationEvent)
    if company_id:
        query = query.where(CommunicationEvent.company_id == company_id)
    if event_type:
        query = query.where(CommunicationEvent.event_type == event_type)
    return list(
        await session.scalars(query.order_by(CommunicationEvent.occurred_at.desc()).limit(limit))
    )


@router.post(
    "/communications", response_model=TimelineEventRead, status_code=status.HTTP_201_CREATED
)
async def create_timeline_event(
    payload: TimelineEventCreate, session: DbSession
) -> CommunicationEvent:
    await require_entity(session, Company, payload.company_id)
    if payload.contact_id:
        contact = await require_entity(session, Contact, payload.contact_id)
        if contact.company_id != payload.company_id:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "contact_mismatch",
                "Contact belongs to another company",
            )
    values = normalize_payload(payload.model_dump(exclude={"occurred_at"}))
    event = CommunicationEvent(
        **values,
        occurred_at=payload.occurred_at or datetime.now(UTC),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard_summary(session: DbSession) -> DashboardSummary:
    async def count_where(model: Any, *conditions: Any) -> int:
        if model is Company:
            conditions = (*conditions, Company.is_synthetic.is_(False))
        elif hasattr(model, "company_id"):
            conditions = (
                *conditions,
                model.company_id.in_(select(Company.id).where(Company.is_synthetic.is_(False))),
            )
        return int(await session.scalar(select(func.count(model.id)).where(*conditions)) or 0)

    recent = list(
        await session.scalars(
            select(CommunicationEvent)
            .where(
                CommunicationEvent.company_id.in_(
                    select(Company.id).where(Company.is_synthetic.is_(False))
                )
            )
            .order_by(CommunicationEvent.occurred_at.desc())
            .limit(10)
        )
    )
    return DashboardSummary(
        companies=await count_where(Company),
        researched=await count_where(Company, Company.last_researched_at.is_not(None)),
        opportunities_identified=await count_where(
            Company, Company.relevance_status == "opportunity_identified"
        ),
        opportunities_with_vacancy=int(
            await session.scalar(
                select(func.count(func.distinct(Company.id)))
                .where(Company.is_synthetic.is_(False))
                .join(JobOpening, JobOpening.company_id == Company.id)
                .where(
                    Company.relevance_status == "opportunity_identified",
                    JobOpening.active.is_(True),
                )
            )
            or 0
        ),
        opportunities_without_vacancy=await count_where(
            Company,
            Company.relevance_status == "opportunity_identified",
            ~select(JobOpening.id)
            .where(JobOpening.company_id == Company.id, JobOpening.active.is_(True))
            .exists(),
        ),
        business_first=await count_where(
            Company, Company.recommended_positioning == "business_first"
        ),
        ai_first=await count_where(Company, Company.recommended_positioning == "ai_first"),
        hybrid=await count_where(Company, Company.recommended_positioning == "hybrid"),
        remote_opportunities=await count_where(
            Company, Company.recommended_workplace_formats.contains(["remote"])
        ),
        relocation_opportunities=await count_where(
            Company, Company.recommended_workplace_formats.contains(["relocation"])
        ),
        project_opportunities=await count_where(
            Company, Company.recommended_collaboration_formats.contains(["project_based"])
        ),
        watchlist=await count_where(Company, Company.pipeline_status == "watchlist"),
        decision_pending=await count_where(Company, Company.pipeline_status == "decision_pending"),
        verified_contacts=await count_where(
            Contact,
            Contact.verification_status.in_(["verified", "verified_public", "provider_verified"]),
        ),
        active_jobs=await count_where(JobOpening, JobOpening.active.is_(True)),
        active_campaigns=await count_where(Campaign, Campaign.status == "active"),
        waiting_review=await count_where(Company, Company.pipeline_status == "review"),
        sent=await count_where(Company, Company.pipeline_status.in_(["sent", "waiting_reply"])),
        replies=await count_where(Company, Company.pipeline_status == "replied"),
        interviews=await count_where(Company, Company.pipeline_status == "interview"),
        project_discussions=await count_where(
            Company, Company.pipeline_status == "project_discussion"
        ),
        consulting_discussions=await count_where(
            Company, Company.pipeline_status == "consulting_discussion"
        ),
        offers_or_agreements=await count_where(
            Company, Company.pipeline_status.in_(["offer", "agreement"])
        ),
        followups_due=await count_where(
            FollowUp,
            FollowUp.status.in_(["planned", "due", "draft_ready", "deferred"]),
            FollowUp.due_at <= datetime.now(UTC),
        ),
        recent_events=cast(list[TimelineEventRead], recent),
    )
