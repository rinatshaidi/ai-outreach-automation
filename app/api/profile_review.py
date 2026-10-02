"""Owner-only profile review, safe import and local pilot readiness API."""

from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_profile import change_record_verification, require_primary_profile
from app.infrastructure.db.session import get_db_session
from app.modules.auth.models import User
from app.modules.candidate_profile.models import CandidateProfile
from app.modules.candidate_profile.readiness import calculate_profile_readiness
from app.modules.candidate_profile.schemas import VerificationDecision
from app.modules.crm.models import Company
from app.modules.profile_review.models import (
    CandidateProfileSection,
    PilotCalibrationNote,
    ProfileImportBatch,
    ProfileImportItem,
)
from app.modules.profile_review.schemas import (
    CalibrationNoteCreate,
    CalibrationNoteRead,
    CandidateRecordVerification,
    ImportItemDecision,
    ImportSectionDecision,
    ProfileImportBatchRead,
    ProfileImportCreate,
    ProfileImportItemRead,
    ProfileSectionRead,
    ProfileSectionReview,
    ProfileSectionType,
)
from app.modules.profile_review.service import (
    PERMISSION_DEFAULTS,
    create_import_entity,
    ensure_profile_sections,
    find_import_target,
    operation_for,
    prepare_import_data,
    review_section,
    safe_snapshot,
    source_hash,
)

router = APIRouter(prefix="/api/v1", tags=["profile-review"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def owner_actor(request: Request) -> str:
    owner: User | None = getattr(request.state, "owner", None)
    return str(owner.id) if owner is not None else "local-test-owner"


async def batch_read(session: AsyncSession, batch: ProfileImportBatch) -> ProfileImportBatchRead:
    items = list(
        await session.scalars(
            select(ProfileImportItem)
            .where(ProfileImportItem.batch_id == batch.id)
            .order_by(ProfileImportItem.id)
        )
    )
    payload = ProfileImportBatchRead.model_validate(batch, from_attributes=True)
    return payload.model_copy(
        update={"items": [ProfileImportItemRead.model_validate(item) for item in items]}
    )


@router.get("/candidate-profile/sections", response_model=list[ProfileSectionRead])
async def list_profile_sections(session: DbSession) -> list[CandidateProfileSection]:
    profile = await require_primary_profile(session)
    items = await ensure_profile_sections(session, profile)
    await session.commit()
    return items


@router.get("/candidate-profile/sections/{section_type}", response_model=ProfileSectionRead)
async def read_profile_section(
    section_type: ProfileSectionType, session: DbSession
) -> CandidateProfileSection:
    profile = await require_primary_profile(session)
    await ensure_profile_sections(session, profile)
    item = await session.scalar(
        select(CandidateProfileSection).where(
            CandidateProfileSection.profile_id == profile.id,
            CandidateProfileSection.section_type == section_type.value,
        )
    )
    await session.commit()
    return cast(CandidateProfileSection, item)


@router.post("/candidate-profile/sections/{section_type}/review", response_model=ProfileSectionRead)
async def decide_profile_section(
    section_type: ProfileSectionType,
    payload: ProfileSectionReview,
    request: Request,
    session: DbSession,
) -> CandidateProfileSection:
    profile = await require_primary_profile(session)
    await ensure_profile_sections(session, profile)
    item = cast(
        CandidateProfileSection,
        await session.scalar(
            select(CandidateProfileSection).where(
                CandidateProfileSection.profile_id == profile.id,
                CandidateProfileSection.section_type == section_type.value,
            )
        ),
    )
    if item.version != payload.version:
        raise api_error(409, "version_conflict", "Refresh this profile section")
    try:
        await review_section(
            session,
            item,
            decision=payload.decision,
            actor=owner_actor(request),
            comment=payload.comment,
            content_hash=payload.content_hash,
            request_id=str(getattr(request.state, "request_id", "profile-review")),
        )
    except ValueError as exc:
        raise api_error(422, "invalid_profile_transition", str(exc)) from exc
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/candidate-profile/records/{entity_type}/{entity_id}/verify")
async def verify_candidate_record(
    entity_type: str,
    entity_id: UUID,
    payload: CandidateRecordVerification,
    request: Request,
    session: DbSession,
) -> dict[str, Any]:
    if entity_type not in {"fact", "contact", "experience", "skill", "strength"}:
        raise api_error(404, "candidate_record_type_unknown", "Candidate record type unknown")
    profile = await require_primary_profile(session)
    section = await session.scalar(
        select(CandidateProfileSection).where(
            CandidateProfileSection.profile_id == profile.id,
            CandidateProfileSection.section_type == payload.section_type.value,
        )
    )
    if section is None or section.status not in {"user_approved", "verified"}:
        raise api_error(
            422,
            "profile_section_not_approved",
            "Approve the related profile section before record verification",
        )
    return await change_record_verification(
        entity_type,
        entity_id,
        VerificationDecision(
            version=payload.version,
            verified=True,
            confirmed=payload.confirmed,
        ),
        request,
        session,
    )


@router.post(
    "/candidate-profile/imports",
    response_model=ProfileImportBatchRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile_import(
    payload: ProfileImportCreate, session: DbSession
) -> ProfileImportBatchRead:
    profile = await require_primary_profile(session)
    raw_items = [item.model_dump(mode="json") for item in payload.items]
    batch = ProfileImportBatch(
        profile_id=profile.id,
        source_filename=payload.source_filename,
        source_format="json",
        source_hash=source_hash(raw_items),
        status="uploaded",
    )
    session.add(batch)
    await session.flush()
    invalid = 0
    conflicts = 0
    for incoming in payload.items:
        proposed, messages = prepare_import_data(incoming.entity_type, incoming.data)
        target = await find_import_target(session, profile.id, incoming.entity_type, proposed)
        operation = operation_for(target, proposed)
        invalid_item = any(not message.startswith("permission ignored") for message in messages)
        invalid += int(invalid_item)
        conflicts += int(operation == "conflict")
        session.add(
            ProfileImportItem(
                batch_id=batch.id,
                section_type=incoming.section_type.value,
                operation="skipped" if invalid_item else operation,
                target_entity_type=incoming.entity_type,
                target_entity_id=getattr(target, "id", None),
                proposed_data=proposed,
                current_data_snapshot=safe_snapshot(target, proposed) if target else None,
                validation_messages=messages,
                default_permissions=PERMISSION_DEFAULTS,
            )
        )
    batch.status = "preview_ready"
    batch.validation_report = {
        "items": len(payload.items),
        "invalid": invalid,
        "conflicts": conflicts,
        "validation_pending": True,
        "automatic_apply": False,
        "permissions_enabled": False,
    }
    await session.commit()
    await session.refresh(batch)
    return await batch_read(session, batch)


@router.post(
    "/candidate-profile/imports/{batch_id}/validate", response_model=ProfileImportBatchRead
)
async def validate_profile_import(batch_id: UUID, session: DbSession) -> ProfileImportBatchRead:
    batch = await session.get(ProfileImportBatch, batch_id)
    if batch is None:
        raise api_error(404, "import_not_found", "Import batch not found")
    items = list(
        await session.scalars(
            select(ProfileImportItem).where(ProfileImportItem.batch_id == batch.id)
        )
    )
    invalid = sum(
        any(not message.startswith("permission ignored") for message in item.validation_messages)
        for item in items
    )
    conflicts = sum(item.operation == "conflict" for item in items)
    batch.status = "validation_failed" if invalid else "review_required"
    batch.validation_report = {
        "items": len(items),
        "invalid": invalid,
        "conflicts": conflicts,
        "validation_pending": False,
        "automatic_apply": False,
        "permissions_enabled": False,
    }
    await session.commit()
    await session.refresh(batch)
    return await batch_read(session, batch)


@router.get("/candidate-profile/imports/{batch_id}/preview", response_model=ProfileImportBatchRead)
async def profile_import_preview(batch_id: UUID, session: DbSession) -> ProfileImportBatchRead:
    batch = await session.get(ProfileImportBatch, batch_id)
    if batch is None:
        raise api_error(404, "import_not_found", "Import batch not found")
    return await batch_read(session, batch)


@router.post(
    "/candidate-profile/imports/{batch_id}/items/{item_id}/decision",
    response_model=ProfileImportItemRead,
)
async def decide_import_item(
    batch_id: UUID,
    item_id: UUID,
    payload: ImportItemDecision,
    session: DbSession,
) -> ProfileImportItem:
    item = await session.get(ProfileImportItem, item_id)
    if item is None or item.batch_id != batch_id:
        raise api_error(404, "import_item_not_found", "Import item not found")
    if item.version != payload.version:
        raise api_error(409, "version_conflict", "Refresh this import item")
    if payload.decision == "corrected":
        if payload.corrected_data is None:
            raise api_error(422, "corrected_data_required", "Corrected data is required")
        batch = cast(ProfileImportBatch, await session.get(ProfileImportBatch, batch_id))
        proposed, messages = prepare_import_data(item.target_entity_type, payload.corrected_data)
        target = await find_import_target(
            session, batch.profile_id, item.target_entity_type, proposed
        )
        item.proposed_data = proposed
        item.validation_messages = messages
        item.target_entity_id = getattr(target, "id", None)
        item.current_data_snapshot = safe_snapshot(target, proposed) if target else None
        item.operation = operation_for(target, proposed)
    item.decision = payload.decision
    item.version += 1
    await session.commit()
    await session.refresh(item)
    return item


@router.post(
    "/candidate-profile/imports/{batch_id}/sections/{section_type}/decision",
    response_model=list[ProfileImportItemRead],
)
async def decide_import_section(
    batch_id: UUID,
    section_type: ProfileSectionType,
    payload: ImportSectionDecision,
    session: DbSession,
) -> list[ProfileImportItem]:
    batch = await session.get(ProfileImportBatch, batch_id)
    if batch is None:
        raise api_error(404, "import_not_found", "Import batch not found")
    if batch.status != "review_required":
        raise api_error(409, "import_validation_required", "Validate the import before review")
    items = list(
        await session.scalars(
            select(ProfileImportItem).where(
                ProfileImportItem.batch_id == batch_id,
                ProfileImportItem.section_type == section_type.value,
            )
        )
    )
    if not items:
        raise api_error(404, "import_section_empty", "Import section has no proposed items")
    if payload.decision == "approved" and any(
        item.operation in {"conflict", "skipped"} for item in items
    ):
        raise api_error(
            409,
            "unsafe_import_section",
            "A section containing conflicts or invalid items cannot be approved as a group",
        )
    for item in items:
        item.decision = payload.decision
        item.version += 1
    batch.reviewed_at = datetime.now(UTC)
    await session.commit()
    return items


@router.post("/candidate-profile/imports/{batch_id}/apply", response_model=ProfileImportBatchRead)
async def apply_profile_import(batch_id: UUID, session: DbSession) -> ProfileImportBatchRead:
    batch = await session.get(ProfileImportBatch, batch_id)
    if batch is None:
        raise api_error(404, "import_not_found", "Import batch not found")
    if batch.status not in {"review_required", "partially_applied"}:
        raise api_error(409, "import_validation_required", "Validate the import before apply")
    profile = cast(CandidateProfile, await session.get(CandidateProfile, batch.profile_id))
    items = list(
        await session.scalars(
            select(ProfileImportItem).where(ProfileImportItem.batch_id == batch.id)
        )
    )
    approved = [item for item in items if item.decision == "approved"]
    if any(item.decision == "pending" for item in items):
        raise api_error(
            409,
            "import_review_incomplete",
            "Review every proposed item before apply",
        )
    if not approved:
        raise api_error(422, "no_approved_items", "Approve at least one import item")
    sections = {item.section_type: item for item in await ensure_profile_sections(session, profile)}
    applied = 0
    for item in approved:
        invalid = any(
            not message.startswith("permission ignored") for message in item.validation_messages
        )
        if invalid or item.operation in {"conflict", "skipped"}:
            raise api_error(
                409,
                "unsafe_import_item",
                "Conflicting or invalid items cannot be applied without correction",
            )
        if item.operation == "match":
            item.applied_entity_id = item.target_entity_id
        else:
            entity = await create_import_entity(
                session, profile, item.target_entity_type, item.proposed_data
            )
            item.applied_entity_id = entity.id
        item.version += 1
        section = sections[item.section_type]
        section.status = "review_required"
        section.version += 1
        section.approved_at = None
        section.verified_at = None
        applied += 1
    batch.status = "applied" if applied == len(items) else "partially_applied"
    batch.reviewed_at = datetime.now(UTC)
    batch.applied_at = datetime.now(UTC)
    await session.commit()
    return await batch_read(session, batch)


@router.post(
    "/pilot/calibration-notes",
    response_model=CalibrationNoteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_calibration_note(
    payload: CalibrationNoteCreate, session: DbSession
) -> PilotCalibrationNote:
    if payload.company_id is not None and await session.get(Company, payload.company_id) is None:
        raise api_error(404, "company_not_found", "Company not found")
    note = PilotCalibrationNote(**payload.model_dump())
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


@router.get("/pilot/readiness")
async def pilot_readiness(session: DbSession) -> dict[str, Any]:
    profile = await require_primary_profile(session)
    company_count = int(
        await session.scalar(
            select(func.count(Company.id)).where(Company.is_synthetic.is_(False))
        )
        or 0
    )
    readiness = await calculate_profile_readiness(session, profile)
    readiness["profile_ready"] = readiness["pilot_first_wave_ready"]
    readiness["companies_available"] = company_count
    return readiness
