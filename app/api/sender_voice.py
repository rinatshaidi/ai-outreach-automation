"""Single-owner Personal Voice / Motivation Profile and approved style references."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.session import get_db_session
from app.modules.candidate_profile.models import CandidateProfile
from app.modules.generation.models import ApprovedWritingExample, SenderVoiceProfile
from app.modules.generation.schemas import (
    ApprovedWritingExampleCreate,
    ApprovedWritingExampleRead,
    SenderVoiceProfileRead,
    SenderVoiceProfileUpsert,
)

router = APIRouter(prefix="/api/v1/sender-voice-profile", tags=["sender-voice-profile"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def primary_profile(session: AsyncSession) -> CandidateProfile:
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    if profile is None:
        raise HTTPException(status_code=409, detail="Candidate Profile must exist")
    return profile


async def voice_profile(session: AsyncSession) -> SenderVoiceProfile:
    profile = await primary_profile(session)
    voice = await session.scalar(
        select(SenderVoiceProfile).where(SenderVoiceProfile.candidate_profile_id == profile.id)
    )
    if voice is None:
        raise HTTPException(status_code=404, detail="Sender Voice Profile was not found")
    return voice


@router.get("", response_model=SenderVoiceProfileRead)
async def get_sender_voice_profile(session: DbSession) -> SenderVoiceProfile:
    return await voice_profile(session)


@router.put("", response_model=SenderVoiceProfileRead)
async def put_sender_voice_profile(
    payload: SenderVoiceProfileUpsert, session: DbSession
) -> SenderVoiceProfile:
    profile = await primary_profile(session)
    voice = await session.scalar(
        select(SenderVoiceProfile).where(SenderVoiceProfile.candidate_profile_id == profile.id)
    )
    values = payload.model_dump()
    if voice is None:
        voice = SenderVoiceProfile(candidate_profile_id=profile.id, **values)
        session.add(voice)
    else:
        for key, value in values.items():
            setattr(voice, key, value)
        voice.version += 1
    await session.commit()
    await session.refresh(voice)
    return voice


@router.get("/examples", response_model=list[ApprovedWritingExampleRead])
async def list_approved_examples(session: DbSession) -> list[ApprovedWritingExample]:
    voice = await voice_profile(session)
    return list(
        await session.scalars(
            select(ApprovedWritingExample)
            .where(ApprovedWritingExample.sender_voice_profile_id == voice.id)
            .order_by(ApprovedWritingExample.created_at.desc())
        )
    )


@router.post(
    "/examples",
    response_model=ApprovedWritingExampleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_approved_example(
    payload: ApprovedWritingExampleCreate, session: DbSession
) -> ApprovedWritingExample:
    voice = await voice_profile(session)
    values = payload.model_dump(exclude={"confirmed"})
    example = ApprovedWritingExample(sender_voice_profile_id=voice.id, **values)
    session.add(example)
    await session.commit()
    await session.refresh(example)
    return example
