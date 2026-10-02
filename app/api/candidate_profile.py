"""REST API for candidate profile data and permission-safe fact packs."""

from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infrastructure.db.session import get_db_session
from app.modules.audit.models import AuditEvent
from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateRule,
    CandidateSkill,
    CandidateStrength,
    ConsentEvent,
)
from app.modules.candidate_profile.readiness import (
    PROFILE_RECORD_MODELS,
    calculate_profile_readiness,
    profile_records,
)
from app.modules.candidate_profile.schemas import (
    BulkVerificationDecision,
    CandidateContactCreate,
    CandidateContactRead,
    CandidateContactUpdate,
    CandidateExperienceCreate,
    CandidateExperienceRead,
    CandidateExperienceUpdate,
    CandidateFactCreate,
    CandidateFactRead,
    CandidateFactUpdate,
    CandidateProfileRead,
    CandidateProfileUpsert,
    CandidateRuleCreate,
    CandidateRuleRead,
    CandidateSkillCreate,
    CandidateSkillRead,
    CandidateSkillUpdate,
    CandidateStrengthCreate,
    CandidateStrengthRead,
    CandidateStrengthUpdate,
    ConsentEventRead,
    FactPackPreview,
    FactPackPurpose,
    VerificationDecision,
)
from app.modules.candidate_profile.service import (
    StructuredCandidateRecord,
    build_fact_pack,
    validate_permissions,
    validate_structured_record,
)
from app.modules.generation.approval import invalidate_approvals_for_candidate_fact

router = APIRouter(prefix="/api/v1", tags=["candidate-profile"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

_PERMISSION_FIELDS = (
    "store_private",
    "use_for_ai_analysis",
    "use_in_scoring",
    "use_in_draft",
    "send_externally",
    "use_in_signature",
    "publish_publicly",
)


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def get_primary_profile(session: AsyncSession) -> CandidateProfile | None:
    return cast(
        CandidateProfile | None,
        await session.scalar(
            select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
        ),
    )


async def require_primary_profile(session: AsyncSession) -> CandidateProfile:
    profile = await get_primary_profile(session)
    if profile is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "profile_not_found", "Profile is not created")
    return profile


def request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "missing-request-id"))


def normalize_payload(values: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    for key, value in normalized.items():
        if isinstance(value, UUID):
            normalized[key] = str(value)
        elif isinstance(value, list):
            normalized[key] = [
                str(item) if isinstance(item, UUID) else getattr(item, "value", item)
                for item in value
            ]
        elif hasattr(value, "value"):
            normalized[key] = value.value
        elif key == "source_link" and value is not None:
            normalized[key] = str(value)
    return normalized


def record_permission_changes(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
    changes: dict[str, bool],
    request: Request,
) -> None:
    for permission, enabled in changes.items():
        if permission not in _PERMISSION_FIELDS:
            continue
        session.add(
            ConsentEvent(
                action_type="permission_changed",
                data_scope=permission,
                entity_type=entity_type,
                entity_id=entity_id,
                decision="allowed" if enabled else "denied",
                granted_at=datetime.now(UTC),
                request_id=request_id(request),
            )
        )


def _experience_identity(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


async def find_similar_experience(
    session: AsyncSession,
    *,
    profile_id: UUID,
    position: str,
    organization_label: str | None,
    exclude_id: UUID | None = None,
) -> CandidateExperience | None:
    """Return a likely duplicate without making duplicate roles impossible."""

    candidates = await session.scalars(
        select(CandidateExperience).where(CandidateExperience.profile_id == profile_id)
    )
    position_key = _experience_identity(position)
    organization_key = _experience_identity(organization_label)
    for candidate in candidates:
        if candidate.id == exclude_id:
            continue
        if (
            _experience_identity(candidate.position) == position_key
            and _experience_identity(candidate.organization_label) == organization_key
        ):
            return candidate
    return None


def duplicate_experience_error(existing: CandidateExperience) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "duplicate_candidate_experience",
            "message": (
                "Похожая запись уже существует. Проверьте её или подтвердите создание "
                "дубликата"
            ),
            "existing_id": str(existing.id),
            "existing_position": existing.position,
            "existing_organization": existing.organization_label,
        },
    )


def ensure_version(actual: int, supplied: int) -> None:
    if actual != supplied:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "version_conflict",
            "The record changed after it was loaded; refresh and try again",
        )


def ensure_valid_permissions(
    entity: CandidateFact | CandidateContact | StructuredCandidateRecord,
) -> None:
    try:
        validate_permissions(entity)
    except ValidationError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_permissions",
            "Permission dependencies are not satisfied",
        ) from exc


def ensure_valid_structured_record(entity: StructuredCandidateRecord) -> None:
    try:
        validate_structured_record(entity)
    except ValidationError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_candidate_record",
            "The structured profile record is inconsistent",
        ) from exc


def reject_direct_verification(verified: bool | None) -> None:
    if get_settings().auth_required and verified is True:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "record_review_required",
            "Verification requires an explicit approved-section review action",
        )


def owner_actor(request: Request) -> str:
    owner = getattr(request.state, "owner", None)
    return str(getattr(owner, "login_identifier", "local_owner"))


def content_was_changed(entity: object, changes: dict[str, Any]) -> bool:
    ignored = {*_PERMISSION_FIELDS, "verified"}
    return any(
        key not in ignored and getattr(entity, key, None) != value
        for key, value in changes.items()
    )


def require_reverification_after_edit(
    session: AsyncSession,
    *,
    profile: CandidateProfile,
    entity: Any,
    entity_type: str,
    changes: dict[str, Any],
    request: Request,
) -> None:
    if not bool(getattr(entity, "verified", False)) or not content_was_changed(entity, changes):
        return
    entity.verified = False
    profile.profile_status = "review_required"
    profile.version += 1
    session.add(
        AuditEvent(
            actor=owner_actor(request),
            action="candidate_record_verification_revoked_after_edit",
            entity_type=entity_type,
            entity_id=str(entity.id),
            result="success",
            safe_diff={"verified": {"from": True, "to": False}},
            request_id=request_id(request),
        )
    )


@router.get("/candidate-profile", response_model=CandidateProfileRead)
async def read_profile(session: DbSession) -> CandidateProfile:
    return await require_primary_profile(session)


@router.get("/candidate-profile/readiness")
async def candidate_profile_readiness(session: DbSession) -> dict[str, Any]:
    profile = await require_primary_profile(session)
    return await calculate_profile_readiness(session, profile)


@router.post("/candidate-profile/records/{entity_type}/{entity_id}/verification")
async def change_record_verification(
    entity_type: str,
    entity_id: UUID,
    payload: VerificationDecision,
    request: Request,
    session: DbSession,
) -> dict[str, Any]:
    model: Any = PROFILE_RECORD_MODELS.get(entity_type)
    if model is None:
        raise api_error(404, "verification_entity_unknown", "Unknown profile record type")
    profile = await require_primary_profile(session)
    readiness_before = await calculate_profile_readiness(session, profile)
    if payload.verified and not readiness_before["semantic_blocks_approved"]:
        raise api_error(
            409,
            "semantic_review_incomplete",
            "All 23 semantic blocks must be owner-approved before record verification",
        )
    entity = await session.scalar(
        select(model).where(model.id == entity_id, model.profile_id == profile.id)
    )
    if entity is None:
        raise api_error(404, "verification_record_not_found", "Profile record was not found")
    ensure_version(entity.version, payload.version)
    previous = bool(entity.verified)
    entity.verified = payload.verified
    entity.version += 1
    if entity_type == "fact" and previous and not payload.verified:
        await invalidate_approvals_for_candidate_fact(session, entity.id)
    session.add(
        AuditEvent(
            actor=owner_actor(request),
            action=(
                "candidate_record_verified"
                if payload.verified
                else "candidate_record_unverified"
            ),
            entity_type=f"candidate_{entity_type}",
            entity_id=str(entity.id),
            result="success",
            safe_diff={"verified": {"from": previous, "to": payload.verified}},
            request_id=request_id(request),
        )
    )
    readiness = await calculate_profile_readiness(session, profile)
    profile.profile_status = (
        "verified" if readiness["pilot_first_wave_ready"] else "review_required"
    )
    profile.version += 1
    await session.commit()
    return {
        "entity_type": entity_type,
        "entity_id": str(entity.id),
        "verified": entity.verified,
        "version": entity.version,
        "readiness": await calculate_profile_readiness(session, profile),
    }


@router.post("/candidate-profile/records/verify-reviewed")
async def verify_all_reviewed_records(
    payload: BulkVerificationDecision,
    request: Request,
    session: DbSession,
) -> dict[str, Any]:
    profile = await require_primary_profile(session)
    readiness_before = await calculate_profile_readiness(session, profile)
    if not readiness_before["semantic_blocks_approved"]:
        raise api_error(
            409,
            "semantic_review_incomplete",
            "All 23 semantic blocks must be owner-approved before bulk verification",
        )
    records = await profile_records(session, profile.id)
    changed = 0
    for entity_type, items in records.items():
        for entity in items:
            if entity.verified:
                continue
            entity.verified = True
            entity.version += 1
            changed += 1
            session.add(
                AuditEvent(
                    actor=owner_actor(request),
                    action="candidate_record_verified",
                    entity_type=f"candidate_{entity_type}",
                    entity_id=str(entity.id),
                    result="success",
                    safe_diff={"verified": {"from": False, "to": True}, "bulk": True},
                    request_id=request_id(request),
                )
            )
    await session.flush()
    readiness_after = await calculate_profile_readiness(session, profile)
    profile.profile_status = (
        "verified" if readiness_after["pilot_first_wave_ready"] else "review_required"
    )
    profile.version += 1
    session.add(
        AuditEvent(
            actor=owner_actor(request),
            action="candidate_profile_bulk_verification_confirmed",
            entity_type="candidate_profile",
            entity_id=str(profile.id),
            result="success",
            safe_diff={"records_verified": changed},
            request_id=request_id(request),
        )
    )
    await session.commit()
    return {
        "records_verified": changed,
        "readiness": await calculate_profile_readiness(session, profile),
    }


@router.put("/candidate-profile", response_model=CandidateProfileRead)
async def upsert_profile(payload: CandidateProfileUpsert, session: DbSession) -> CandidateProfile:
    if payload.profile_status.value in {"user_approved", "verified"}:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "profile_review_required",
            "Owner approval and verification require a section review action",
        )
    profile = await get_primary_profile(session)
    values = normalize_payload(payload.model_dump(exclude={"version"}))
    if profile is None:
        if payload.version is not None:
            raise api_error(
                status.HTTP_409_CONFLICT,
                "profile_missing",
                "Cannot update a profile that does not exist",
            )
        profile = CandidateProfile(owner_key="primary", **values)
        session.add(profile)
    else:
        if payload.version is None:
            raise api_error(
                status.HTTP_428_PRECONDITION_REQUIRED,
                "version_required",
                "Current profile version is required",
            )
        ensure_version(profile.version, payload.version)
        for key, value in values.items():
            setattr(profile, key, value)
        profile.version += 1

    await session.commit()
    await session.refresh(profile)
    return profile


@router.get("/candidate-facts", response_model=list[CandidateFactRead])
async def list_facts(session: DbSession) -> list[CandidateFact]:
    profile = await require_primary_profile(session)
    result = await session.scalars(
        select(CandidateFact)
        .where(CandidateFact.profile_id == profile.id)
        .order_by(CandidateFact.created_at.desc())
    )
    return list(result)


@router.post(
    "/candidate-facts", response_model=CandidateFactRead, status_code=status.HTTP_201_CREATED
)
async def create_fact(
    payload: CandidateFactCreate,
    request: Request,
    session: DbSession,
) -> CandidateFact:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    values = normalize_payload(payload.model_dump())
    fact = CandidateFact(profile_id=profile.id, **values)
    session.add(fact)
    await session.flush()
    record_permission_changes(
        session,
        entity_type="candidate_fact",
        entity_id=fact.id,
        changes={field: bool(values[field]) for field in _PERMISSION_FIELDS},
        request=request,
    )
    await session.commit()
    await session.refresh(fact)
    return fact


@router.patch("/candidate-facts/{fact_id}", response_model=CandidateFactRead)
async def update_fact(
    fact_id: UUID,
    payload: CandidateFactUpdate,
    request: Request,
    session: DbSession,
) -> CandidateFact:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    fact = await session.scalar(
        select(CandidateFact).where(
            CandidateFact.id == fact_id,
            CandidateFact.profile_id == profile.id,
        )
    )
    if fact is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "fact_not_found", "Fact was not found")
    ensure_version(fact.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    require_reverification_after_edit(
        session,
        profile=profile,
        entity=fact,
        entity_type="candidate_fact",
        changes=changes,
        request=request,
    )
    permission_changes = {
        key: bool(value) for key, value in changes.items() if key in _PERMISSION_FIELDS
    }
    for key, value in changes.items():
        setattr(fact, key, value)
    ensure_valid_permissions(fact)
    if any(
        key in permission_changes and not permission_changes[key]
        for key in ("store_private", "use_in_draft")
    ) or ("verified" in changes and not bool(changes["verified"])):
        await invalidate_approvals_for_candidate_fact(session, fact.id)
    fact.version += 1
    record_permission_changes(
        session,
        entity_type="candidate_fact",
        entity_id=fact.id,
        changes=permission_changes,
        request=request,
    )
    await session.commit()
    await session.refresh(fact)
    return fact


@router.delete("/candidate-facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    fact_id: UUID,
    version: int,
    request: Request,
    session: DbSession,
) -> Response:
    profile = await require_primary_profile(session)
    fact = await session.scalar(
        select(CandidateFact).where(
            CandidateFact.id == fact_id,
            CandidateFact.profile_id == profile.id,
        )
    )
    if fact is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "fact_not_found", "Fact was not found")
    ensure_version(fact.version, version)
    await invalidate_approvals_for_candidate_fact(session, fact.id)
    owner = getattr(request.state, "owner", None)
    session.add(
        AuditEvent(
            actor=str(getattr(owner, "login_identifier", "local_owner")),
            action="candidate_fact_deleted",
            entity_type="candidate_fact",
            entity_id=str(fact.id),
            result="success",
            safe_diff={"version": fact.version, "fact_type": fact.fact_type},
            request_id=request_id(request),
        )
    )
    await session.delete(fact)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/candidate-contacts", response_model=list[CandidateContactRead])
async def list_contacts(session: DbSession) -> list[CandidateContact]:
    profile = await require_primary_profile(session)
    result = await session.scalars(
        select(CandidateContact)
        .where(CandidateContact.profile_id == profile.id)
        .order_by(CandidateContact.created_at.desc())
    )
    return list(result)


@router.post(
    "/candidate-contacts",
    response_model=CandidateContactRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    payload: CandidateContactCreate,
    request: Request,
    session: DbSession,
) -> CandidateContact:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    values = normalize_payload(payload.model_dump())
    contact = CandidateContact(profile_id=profile.id, **values)
    session.add(contact)
    await session.flush()
    record_permission_changes(
        session,
        entity_type="candidate_contact",
        entity_id=contact.id,
        changes={field: bool(values[field]) for field in _PERMISSION_FIELDS},
        request=request,
    )
    await session.commit()
    await session.refresh(contact)
    return contact


@router.patch("/candidate-contacts/{contact_id}", response_model=CandidateContactRead)
async def update_contact(
    contact_id: UUID,
    payload: CandidateContactUpdate,
    request: Request,
    session: DbSession,
) -> CandidateContact:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    contact = await session.scalar(
        select(CandidateContact).where(
            CandidateContact.id == contact_id,
            CandidateContact.profile_id == profile.id,
        )
    )
    if contact is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "contact_not_found", "Contact was not found")
    ensure_version(contact.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    require_reverification_after_edit(
        session,
        profile=profile,
        entity=contact,
        entity_type="candidate_contact",
        changes=changes,
        request=request,
    )
    permission_changes = {
        key: bool(value) for key, value in changes.items() if key in _PERMISSION_FIELDS
    }
    for key, value in changes.items():
        setattr(contact, key, value)
    ensure_valid_permissions(contact)
    contact.version += 1
    record_permission_changes(
        session,
        entity_type="candidate_contact",
        entity_id=contact.id,
        changes=permission_changes,
        request=request,
    )
    await session.commit()
    await session.refresh(contact)
    return contact


@router.delete("/candidate-contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: UUID,
    version: int,
    request: Request,
    session: DbSession,
) -> Response:
    profile = await require_primary_profile(session)
    contact = await session.scalar(
        select(CandidateContact).where(
            CandidateContact.id == contact_id,
            CandidateContact.profile_id == profile.id,
        )
    )
    if contact is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "contact_not_found", "Contact was not found"
        )
    ensure_version(contact.version, version)
    owner = getattr(request.state, "owner", None)
    session.add(
        AuditEvent(
            actor=str(getattr(owner, "login_identifier", "local_owner")),
            action="candidate_contact_deleted",
            entity_type="candidate_contact",
            entity_id=str(contact.id),
            result="success",
            safe_diff={"version": contact.version, "contact_type": contact.contact_type},
            request_id=request_id(request),
        )
    )
    await session.delete(contact)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/candidate-rules", response_model=list[CandidateRuleRead])
async def list_rules(session: DbSession) -> list[CandidateRule]:
    profile = await require_primary_profile(session)
    result = await session.scalars(
        select(CandidateRule)
        .where(CandidateRule.profile_id == profile.id)
        .order_by(CandidateRule.priority)
    )
    return list(result)


@router.post(
    "/candidate-rules", response_model=CandidateRuleRead, status_code=status.HTTP_201_CREATED
)
async def create_rule(payload: CandidateRuleCreate, session: DbSession) -> CandidateRule:
    profile = await require_primary_profile(session)
    rule = CandidateRule(profile_id=profile.id, **normalize_payload(payload.model_dump()))
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.get("/candidate-experiences", response_model=list[CandidateExperienceRead])
async def list_experiences(session: DbSession) -> list[CandidateExperience]:
    profile = await require_primary_profile(session)
    return list(
        await session.scalars(
            select(CandidateExperience)
            .where(CandidateExperience.profile_id == profile.id)
            .order_by(CandidateExperience.started_at.desc().nullslast())
        )
    )


@router.post(
    "/candidate-experiences",
    response_model=CandidateExperienceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_experience(
    payload: CandidateExperienceCreate,
    request: Request,
    session: DbSession,
    confirm_duplicate: bool = False,
) -> CandidateExperience:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    similar = await find_similar_experience(
        session,
        profile_id=profile.id,
        position=payload.position,
        organization_label=payload.organization_label,
    )
    if similar is not None and not confirm_duplicate:
        raise duplicate_experience_error(similar)
    values = normalize_payload(payload.model_dump())
    experience = CandidateExperience(profile_id=profile.id, **values)
    session.add(experience)
    await session.flush()
    record_permission_changes(
        session,
        entity_type="candidate_experience",
        entity_id=experience.id,
        changes={field: bool(values[field]) for field in _PERMISSION_FIELDS},
        request=request,
    )
    await session.commit()
    await session.refresh(experience)
    return experience


@router.patch("/candidate-experiences/{experience_id}", response_model=CandidateExperienceRead)
async def update_experience(
    experience_id: UUID,
    payload: CandidateExperienceUpdate,
    request: Request,
    session: DbSession,
    confirm_duplicate: bool = False,
) -> CandidateExperience:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    experience = await session.scalar(
        select(CandidateExperience).where(
            CandidateExperience.id == experience_id,
            CandidateExperience.profile_id == profile.id,
        )
    )
    if experience is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "experience_not_found", "Experience was not found"
        )
    ensure_version(experience.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    require_reverification_after_edit(
        session,
        profile=profile,
        entity=experience,
        entity_type="candidate_experience",
        changes=changes,
        request=request,
    )
    candidate_position = str(changes.get("position", experience.position))
    candidate_organization = changes.get(
        "organization_label", experience.organization_label
    )
    similar = await find_similar_experience(
        session,
        profile_id=profile.id,
        position=candidate_position,
        organization_label=(
            str(candidate_organization) if candidate_organization is not None else None
        ),
        exclude_id=experience.id,
    )
    if similar is not None and not confirm_duplicate:
        raise duplicate_experience_error(similar)
    permission_changes = {
        key: bool(value) for key, value in changes.items() if key in _PERMISSION_FIELDS
    }
    for key, value in changes.items():
        setattr(experience, key, value)
    ensure_valid_permissions(experience)
    ensure_valid_structured_record(experience)
    experience.version += 1
    record_permission_changes(
        session,
        entity_type="candidate_experience",
        entity_id=experience.id,
        changes=permission_changes,
        request=request,
    )
    await session.commit()
    await session.refresh(experience)
    return experience


@router.delete("/candidate-experiences/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experience(
    experience_id: UUID,
    version: int,
    request: Request,
    session: DbSession,
) -> Response:
    profile = await require_primary_profile(session)
    experience = await session.scalar(
        select(CandidateExperience).where(
            CandidateExperience.id == experience_id,
            CandidateExperience.profile_id == profile.id,
        )
    )
    if experience is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "experience_not_found", "Experience was not found"
        )
    ensure_version(experience.version, version)
    owner = getattr(request.state, "owner", None)
    session.add(
        AuditEvent(
            actor=str(getattr(owner, "login_identifier", "local_owner")),
            action="candidate_experience_deleted",
            entity_type="candidate_experience",
            entity_id=str(experience.id),
            result="success",
            safe_diff={
                "version": experience.version,
                "position": experience.position,
                "organization_label": experience.organization_label,
            },
            request_id=request_id(request),
        )
    )
    await session.delete(experience)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/candidate-skills", response_model=list[CandidateSkillRead])
async def list_skills(session: DbSession) -> list[CandidateSkill]:
    profile = await require_primary_profile(session)
    return list(
        await session.scalars(
            select(CandidateSkill)
            .where(CandidateSkill.profile_id == profile.id)
            .order_by(CandidateSkill.skill_group, CandidateSkill.name)
        )
    )


@router.post(
    "/candidate-skills", response_model=CandidateSkillRead, status_code=status.HTTP_201_CREATED
)
async def create_skill(
    payload: CandidateSkillCreate, request: Request, session: DbSession
) -> CandidateSkill:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    values = normalize_payload(payload.model_dump())
    skill = CandidateSkill(profile_id=profile.id, **values)
    session.add(skill)
    await session.flush()
    record_permission_changes(
        session,
        entity_type="candidate_skill",
        entity_id=skill.id,
        changes={field: bool(values[field]) for field in _PERMISSION_FIELDS},
        request=request,
    )
    await session.commit()
    await session.refresh(skill)
    return skill


@router.patch("/candidate-skills/{skill_id}", response_model=CandidateSkillRead)
async def update_skill(
    skill_id: UUID,
    payload: CandidateSkillUpdate,
    request: Request,
    session: DbSession,
) -> CandidateSkill:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    skill = await session.scalar(
        select(CandidateSkill).where(
            CandidateSkill.id == skill_id,
            CandidateSkill.profile_id == profile.id,
        )
    )
    if skill is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "skill_not_found", "Skill was not found")
    ensure_version(skill.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    require_reverification_after_edit(
        session,
        profile=profile,
        entity=skill,
        entity_type="candidate_skill",
        changes=changes,
        request=request,
    )
    permission_changes = {
        key: bool(value) for key, value in changes.items() if key in _PERMISSION_FIELDS
    }
    for key, value in changes.items():
        setattr(skill, key, value)
    ensure_valid_permissions(skill)
    ensure_valid_structured_record(skill)
    skill.version += 1
    record_permission_changes(
        session,
        entity_type="candidate_skill",
        entity_id=skill.id,
        changes=permission_changes,
        request=request,
    )
    await session.commit()
    await session.refresh(skill)
    return skill


@router.delete("/candidate-skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: UUID, version: int, session: DbSession) -> Response:
    profile = await require_primary_profile(session)
    skill = await session.scalar(
        select(CandidateSkill).where(
            CandidateSkill.id == skill_id,
            CandidateSkill.profile_id == profile.id,
        )
    )
    if skill is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "skill_not_found", "Skill was not found")
    ensure_version(skill.version, version)
    await session.delete(skill)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/candidate-strengths", response_model=list[CandidateStrengthRead])
async def list_strengths(session: DbSession) -> list[CandidateStrength]:
    profile = await require_primary_profile(session)
    return list(
        await session.scalars(
            select(CandidateStrength)
            .where(CandidateStrength.profile_id == profile.id)
            .order_by(CandidateStrength.priority, CandidateStrength.created_at)
        )
    )


@router.post(
    "/candidate-strengths",
    response_model=CandidateStrengthRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_strength(
    payload: CandidateStrengthCreate, request: Request, session: DbSession
) -> CandidateStrength:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    values = normalize_payload(payload.model_dump())
    strength = CandidateStrength(profile_id=profile.id, **values)
    session.add(strength)
    await session.flush()
    record_permission_changes(
        session,
        entity_type="candidate_strength",
        entity_id=strength.id,
        changes={field: bool(values[field]) for field in _PERMISSION_FIELDS},
        request=request,
    )
    await session.commit()
    await session.refresh(strength)
    return strength


@router.patch("/candidate-strengths/{strength_id}", response_model=CandidateStrengthRead)
async def update_strength(
    strength_id: UUID,
    payload: CandidateStrengthUpdate,
    request: Request,
    session: DbSession,
) -> CandidateStrength:
    reject_direct_verification(payload.verified)
    profile = await require_primary_profile(session)
    strength = await session.scalar(
        select(CandidateStrength).where(
            CandidateStrength.id == strength_id,
            CandidateStrength.profile_id == profile.id,
        )
    )
    if strength is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "strength_not_found", "Strength was not found")
    ensure_version(strength.version, payload.version)
    changes = normalize_payload(payload.model_dump(exclude_unset=True, exclude={"version"}))
    require_reverification_after_edit(
        session,
        profile=profile,
        entity=strength,
        entity_type="candidate_strength",
        changes=changes,
        request=request,
    )
    permission_changes = {
        key: bool(value) for key, value in changes.items() if key in _PERMISSION_FIELDS
    }
    for key, value in changes.items():
        setattr(strength, key, value)
    ensure_valid_permissions(strength)
    ensure_valid_structured_record(strength)
    strength.version += 1
    record_permission_changes(
        session,
        entity_type="candidate_strength",
        entity_id=strength.id,
        changes=permission_changes,
        request=request,
    )
    await session.commit()
    await session.refresh(strength)
    return strength


@router.delete("/candidate-strengths/{strength_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strength(strength_id: UUID, version: int, session: DbSession) -> Response:
    profile = await require_primary_profile(session)
    strength = await session.scalar(
        select(CandidateStrength).where(
            CandidateStrength.id == strength_id,
            CandidateStrength.profile_id == profile.id,
        )
    )
    if strength is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "strength_not_found", "Strength was not found")
    ensure_version(strength.version, version)
    await session.delete(strength)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/consents", response_model=list[ConsentEventRead])
async def list_consents(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ConsentEvent]:
    result = await session.scalars(
        select(ConsentEvent).order_by(ConsentEvent.granted_at.desc()).limit(limit)
    )
    return list(result)


@router.get("/candidate-profile/fact-pack", response_model=FactPackPreview)
async def preview_fact_pack(
    session: DbSession,
    purpose: FactPackPurpose = FactPackPurpose.AI_ANALYSIS,
) -> FactPackPreview:
    profile = await require_primary_profile(session)
    facts = list(
        await session.scalars(select(CandidateFact).where(CandidateFact.profile_id == profile.id))
    )
    contacts = list(
        await session.scalars(
            select(CandidateContact).where(CandidateContact.profile_id == profile.id)
        )
    )
    rules = list(
        await session.scalars(select(CandidateRule).where(CandidateRule.profile_id == profile.id))
    )
    return build_fact_pack(profile, facts, contacts, rules, purpose)
