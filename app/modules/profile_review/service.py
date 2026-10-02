"""Fail-closed profile review and preview-first import rules."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateSkill,
    CandidateStrength,
)
from app.modules.candidate_profile.schemas import (
    CandidateContactCreate,
    CandidateExperienceCreate,
    CandidateFactCreate,
    CandidateSkillCreate,
    CandidateStrengthCreate,
)
from app.modules.profile_review.models import CandidateProfileSection, ProfileReviewEvent
from app.modules.profile_review.schemas import ProfileSectionType, ReviewDecision

PERMISSION_DEFAULTS = {
    "store_private": False,
    "use_for_ai_analysis": False,
    "use_in_scoring": False,
    "use_in_draft": False,
    "send_externally": False,
    "use_in_signature": False,
    "publish_publicly": False,
}

IMPORT_SCHEMAS: dict[str, type[BaseModel]] = {
    "fact": CandidateFactCreate,
    "contact": CandidateContactCreate,
    "experience": CandidateExperienceCreate,
    "skill": CandidateSkillCreate,
    "strength": CandidateStrengthCreate,
}
IMPORT_MODELS: dict[str, Any] = {
    "fact": CandidateFact,
    "contact": CandidateContact,
    "experience": CandidateExperience,
    "skill": CandidateSkill,
    "strength": CandidateStrength,
}


def source_hash(items: list[dict[str, Any]]) -> str:
    payload = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()


def validation_messages(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()
    ]


def prepare_import_data(entity_type: str, data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    values = dict(data)
    ignored = sorted(key for key in PERMISSION_DEFAULTS if bool(values.pop(key, False)))
    values.pop("verified", None)
    values.pop("allowed_in_signature", None)
    values.update(PERMISSION_DEFAULTS, store_private=True)
    if entity_type == "contact":
        values["allowed_in_signature"] = False
    messages = [f"permission ignored and remains disabled: {key}" for key in ignored]
    try:
        validated = IMPORT_SCHEMAS[entity_type].model_validate(values)
    except ValidationError as exc:
        return values, messages + validation_messages(exc)
    normalized = validated.model_dump(mode="json")
    normalized["verified"] = False
    return normalized, messages


async def find_import_target(
    session: AsyncSession, profile_id: Any, entity_type: str, data: dict[str, Any]
) -> Any | None:
    model = IMPORT_MODELS[entity_type]
    query = select(model).where(model.profile_id == profile_id)
    if entity_type == "fact":
        query = query.where(CandidateFact.text == data.get("text", ""))
    elif entity_type == "contact":
        query = query.where(
            CandidateContact.contact_type == data.get("contact_type", ""),
            CandidateContact.value == data.get("value", ""),
        )
    elif entity_type == "experience":
        query = query.where(
            CandidateExperience.position == data.get("position", ""),
            CandidateExperience.organization_label == data.get("organization_label"),
        )
    elif entity_type == "skill":
        query = query.where(CandidateSkill.name == data.get("name", ""))
    else:
        query = query.where(CandidateStrength.text == data.get("text", ""))
    return await session.scalar(query.limit(1))


def safe_snapshot(entity: Any, proposed: dict[str, Any]) -> dict[str, Any]:
    return {
        key: getattr(entity, key, None)
        for key in proposed
        if key not in PERMISSION_DEFAULTS and key not in {"verified", "allowed_in_signature"}
    }


def operation_for(target: Any | None, proposed: dict[str, Any]) -> str:
    if target is None:
        return "proposed_create"
    snapshot = safe_snapshot(target, proposed)
    normalized = json.loads(json.dumps(snapshot, default=str))
    comparison = {key: proposed.get(key) for key in snapshot}
    return "match" if normalized == comparison else "conflict"


async def create_import_entity(
    session: AsyncSession, profile: CandidateProfile, entity_type: str, proposed: dict[str, Any]
) -> Any:
    validated = IMPORT_SCHEMAS[entity_type].model_validate(proposed)
    values = validated.model_dump(mode="python")
    values["verified"] = False
    for key, value in list(values.items()):
        if hasattr(value, "value"):
            values[key] = value.value
        elif isinstance(value, list):
            values[key] = [
                str(item) if hasattr(item, "hex") else getattr(item, "value", item)
                for item in value
            ]
        elif key == "source_link" and value is not None:
            values[key] = str(value)
    entity = IMPORT_MODELS[entity_type](profile_id=profile.id, **values)
    session.add(entity)
    await session.flush()
    return entity


async def ensure_profile_sections(
    session: AsyncSession, profile: CandidateProfile
) -> list[CandidateProfileSection]:
    existing = list(
        await session.scalars(
            select(CandidateProfileSection).where(CandidateProfileSection.profile_id == profile.id)
        )
    )
    known = {item.section_type for item in existing}
    initial_status = "review_required" if profile.version >= 1 else "draft"
    for section_type in ProfileSectionType:
        if section_type.value not in known:
            item = CandidateProfileSection(
                profile_id=profile.id,
                section_type=section_type.value,
                status=initial_status,
            )
            session.add(item)
            existing.append(item)
    await session.flush()
    return sorted(
        existing,
        key=lambda item: list(ProfileSectionType).index(ProfileSectionType(item.section_type)),
    )


async def review_section(
    session: AsyncSession,
    section: CandidateProfileSection,
    *,
    decision: ReviewDecision,
    actor: str,
    comment: str | None,
    content_hash: str | None,
    request_id: str,
) -> None:
    previous = section.status
    previous_content_hash = section.content_hash
    now = datetime.now(UTC)
    if decision == ReviewDecision.APPROVE:
        if section.status not in {"draft", "review_required"}:
            raise ValueError("Only a draft or review-required section can be approved")
        section.status = "user_approved"
        section.approved_at = now
        section.approved_by = actor
    elif decision == ReviewDecision.VERIFY:
        if section.status != "user_approved":
            raise ValueError("Verification requires prior user approval")
        section.status = "verified"
        section.verified_at = now
        section.approved_by = actor
    elif decision == ReviewDecision.CORRECT:
        section.status = "review_required"
        section.version += 1
        section.approved_at = None
        section.verified_at = None
        section.approved_by = None
    elif decision == ReviewDecision.REJECT:
        section.status = "draft"
        section.version += 1
        section.approved_at = None
        section.verified_at = None
        section.approved_by = None
    elif decision == ReviewDecision.DEFER:
        section.status = "review_required"
    section.user_comment = comment
    if content_hash is not None:
        section.content_hash = content_hash
    safe_diff: dict[str, Any] = {"status": {"from": previous, "to": section.status}}
    if content_hash is not None and content_hash != previous_content_hash:
        safe_diff["content_hash"] = {
            "from": previous_content_hash,
            "to": content_hash,
        }
    session.add(
        ProfileReviewEvent(
            profile_section_id=section.id,
            from_status=previous,
            to_status=section.status,
            decision=decision.value,
            actor=actor,
            comment=comment,
            safe_diff=safe_diff,
            request_id=request_id,
        )
    )
