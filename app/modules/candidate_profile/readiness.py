"""Computed Candidate Profile readiness for the local pilot."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateSkill,
    CandidateStrength,
)
from app.modules.profile_review.models import CandidateProfileSection

PROFILE_RECORD_MODELS: dict[str, Any] = {
    "experience": CandidateExperience,
    "skill": CandidateSkill,
    "strength": CandidateStrength,
    "fact": CandidateFact,
    "contact": CandidateContact,
}


async def profile_records(
    session: AsyncSession, profile_id: object
) -> dict[str, list[Any]]:
    return {
        name: list(
            await session.scalars(
                select(model).where(model.profile_id == profile_id).order_by(model.created_at)
            )
        )
        for name, model in PROFILE_RECORD_MODELS.items()
    }


def permission_summary(records: dict[str, list[Any]]) -> dict[str, bool]:
    all_items = [item for items in records.values() for item in items]
    scoring_items = [
        item
        for name in ("experience", "skill", "strength", "fact")
        for item in records[name]
    ]
    return {
        "local_storage": bool(all_items) and all(item.store_private for item in all_items),
        "ai_analysis": bool(scoring_items)
        and all(item.use_for_ai_analysis for item in scoring_items),
        "scoring": bool(scoring_items) and all(item.use_in_scoring for item in scoring_items),
        "draft": bool(scoring_items) and all(item.use_in_draft for item in scoring_items),
        "external_send_disabled": all(not item.send_externally for item in all_items),
        "signature_disabled": all(not item.use_in_signature for item in all_items),
        "publication_disabled": all(not item.publish_publicly for item in all_items),
    }


async def calculate_profile_readiness(
    session: AsyncSession, profile: CandidateProfile
) -> dict[str, Any]:
    sections = list(
        await session.scalars(
            select(CandidateProfileSection).where(
                CandidateProfileSection.profile_id == profile.id
            )
        )
    )
    records = await profile_records(session, profile.id)
    status_counts = {
        value: sum(item.status == value for item in sections)
        for value in ("draft", "review_required", "user_approved", "verified")
    }
    section_ready = bool(sections) and all(
        item.status in {"user_approved", "verified"} for item in sections
    )
    group_counts = {
        name: {
            "total": len(items),
            "verified": sum(item.verified for item in items),
            "pending": sum(not item.verified for item in items),
        }
        for name, items in records.items()
    }
    required_groups = ("experience", "skill", "strength", "fact")
    structured_ready = all(
        group_counts[name]["total"] > 0 and group_counts[name]["pending"] == 0
        for name in required_groups
    )
    contacts_ready = group_counts["contact"]["pending"] == 0
    permissions = permission_summary(records)
    settings = get_settings()
    safe_local_flags = (
        settings.demo_mode
        and not settings.allow_real_email
        and not settings.allow_publication
        and not settings.allow_external_export
    )
    permission_ready = all(permissions.values())
    ready = (
        section_ready
        and structured_ready
        and contacts_ready
        and permission_ready
        and safe_local_flags
        and settings.auth_required
    )
    return {
        "status": "READY_FOR_LOCAL_PILOT" if ready else "NOT_READY",
        "profile_sections": status_counts,
        "semantic_blocks_approved": section_ready,
        "record_groups": group_counts,
        "structured_records_verified": structured_ready,
        "contacts_verified": contacts_ready,
        "permissions": permissions,
        "required_permissions_available": permission_ready,
        "authentication_required": settings.auth_required,
        "safe_local_flags": safe_local_flags,
        "pilot_first_wave_ready": ready,
        "production_ready": False,
        "owner_acceptance_required": not ready,
    }
