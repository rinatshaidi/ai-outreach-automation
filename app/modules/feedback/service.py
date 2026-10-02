"""Persist and summarize explicit owner feedback without automatic rule changes."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profile_review.models import PilotCalibrationNote

RULE_VERSION = "owner-feedback-v1"
CALIBRATION_THRESHOLD = 5
COMPANY_DECISIONS = {"good_match", "uncertain", "not_match"}
DRAFT_DECISIONS = {"good", "needs_edit", "not_usable"}
REASONS = {
    "wrong_company", "weak_fit", "insufficient_research", "wrong_contact",
    "too_generic", "too_long", "too_formal", "too_casual",
    "good_personalization", "good_fit", "other",
}


async def record_owner_feedback(
    session: AsyncSession,
    *,
    category: str,
    decision: str,
    allowed_decisions: set[str],
    reason: str | None,
    comment: str | None,
    company_id: UUID | None,
    context: dict[str, Any],
) -> PilotCalibrationNote:
    """Append one local signal; never mutate scoring or generation rules."""
    if decision not in allowed_decisions:
        raise ValueError("Unsupported feedback decision")
    if reason and reason not in REASONS:
        raise ValueError("Unsupported feedback reason")
    payload = {
        "decision": decision,
        "reason": reason or None,
        "comment": (comment or "").strip() or None,
        "context": context,
    }
    note = PilotCalibrationNote(
        company_id=company_id,
        category=category,
        observation=json.dumps(payload, ensure_ascii=False),
        proposed_change=None,
        status="open",
        rule_version=RULE_VERSION,
    )
    session.add(note)
    await session.flush()
    return note


def summarize_feedback_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(str(item.get("decision")) for item in payloads if item.get("decision"))
    reasons = Counter(str(item.get("reason")) for item in payloads if item.get("reason"))
    total = len(payloads)
    return {
        "total": total,
        "decisions": dict(decisions),
        "top_reasons": reasons.most_common(5),
        "calibration_threshold": CALIBRATION_THRESHOLD,
        "ready_for_calibration": total >= CALIBRATION_THRESHOLD,
        "remaining": max(0, CALIBRATION_THRESHOLD - total),
    }


async def owner_feedback_summary(session: AsyncSession) -> dict[str, Any]:
    notes = list(
        await session.scalars(
            select(PilotCalibrationNote)
            .where(PilotCalibrationNote.rule_version == RULE_VERSION)
            .order_by(PilotCalibrationNote.created_at)
        )
    )
    payloads: list[dict[str, Any]] = []
    for note in notes:
        try:
            payload = json.loads(note.observation)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return summarize_feedback_payloads(payloads)
