"""Idempotently configure the explicitly provided single-owner voice profile."""

import asyncio

from sqlalchemy import select

from app.infrastructure.db.session import SessionFactory, close_database
from app.modules.candidate_profile.models import CandidateProfile
from app.modules.generation.models import SenderVoiceProfile

VOICE_VALUES = {
    "communication_style": [
        "personal, natural, and calm",
        "may explain genuine motivation when relevant",
        "avoids dry corporate language and CV retelling",
    ],
    "values": [
        "practical work and real outcomes",
        "honest positioning without inflated seniority",
        "combining business understanding with technology",
    ],
    "motivations": [
        "AI and automation are an important new professional direction",
        "AI has changed the sender's approach to work and professional development",
        "interest in teams actively building practical products around AI",
        "use AI to strengthen more than 10 years of management and business experience",
    ],
    "interests": [
        "AI and automation",
        "international teams",
        "business development and new market launches",
        "practical operational improvement",
    ],
    "preferred_tone": "personal, lively, calm, and professional",
    "preferred_openings": {
        "ru": ["Добрый день"],
        "en": ["Dear", "Hello"],
    },
    "things_to_avoid": [
        "automatic Hi opening",
        "AI clichés",
        "recruiter or template-bot tone",
        "CV retelling",
        "unnecessary technology lists",
        "internal system terminology",
        "inflated AI or Python seniority",
    ],
    "active": True,
}


async def main() -> None:
    async with SessionFactory() as session:
        profile = await session.scalar(
            select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
        )
        if profile is None:
            raise RuntimeError("Primary Candidate Profile was not found")
        voice = await session.scalar(
            select(SenderVoiceProfile).where(
                SenderVoiceProfile.candidate_profile_id == profile.id
            )
        )
        if voice is None:
            voice = SenderVoiceProfile(candidate_profile_id=profile.id, **VOICE_VALUES)
            session.add(voice)
            action = "created"
        else:
            for key, value in VOICE_VALUES.items():
                setattr(voice, key, value)
            voice.version += 1
            action = "updated"
        await session.commit()
        await session.refresh(voice)
        print(f"Sender Voice Profile {action}: id={voice.id}, version={voice.version}")
        print("Approved examples were not changed.")
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
