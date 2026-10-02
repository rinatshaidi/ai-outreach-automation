import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.candidate_profile import content_was_changed, ensure_version
from app.modules.candidate_profile.schemas import (
    BulkVerificationDecision,
    CandidateContactCreate,
    CandidateFactCreate,
    VerificationDecision,
)


def test_fact_requires_explicit_private_storage_consent() -> None:
    with pytest.raises(ValidationError):
        CandidateFactCreate(
            fact_type="skill",
            text="Synthetic Python skill",
            store_private=False,
        )


def test_external_send_requires_draft_permission() -> None:
    with pytest.raises(ValidationError, match="use_in_draft is required"):
        CandidateFactCreate(
            fact_type="project",
            text="Synthetic automation project",
            store_private=True,
            send_externally=True,
        )


def test_contact_permissions_are_independent_from_signature() -> None:
    contact = CandidateContactCreate(
        contact_type="email",
        value="synthetic@example.test",
        store_private=True,
        use_in_draft=True,
        send_externally=True,
        allowed_in_signature=False,
    )

    assert contact.send_externally is True
    assert contact.allowed_in_signature is False


def test_optimistic_locking_rejects_stale_version() -> None:
    with pytest.raises(HTTPException) as error:
        ensure_version(actual=3, supplied=2)

    assert getattr(error.value, "status_code", None) == 409
    assert error.value.detail["code"] == "version_conflict"


def test_single_record_verification_requires_explicit_owner_confirmation() -> None:
    with pytest.raises(ValidationError, match="explicit owner confirmation"):
        VerificationDecision(version=1, verified=True, confirmed=False)

    decision = VerificationDecision(version=1, verified=True, confirmed=True)
    assert decision.verified is True


def test_bulk_verification_requires_explicit_owner_confirmation() -> None:
    with pytest.raises(ValidationError, match="explicit owner confirmation"):
        BulkVerificationDecision(confirmed=False)

    assert BulkVerificationDecision(confirmed=True).confirmed is True


def test_verified_record_requires_review_only_after_content_change() -> None:
    record = type("Record", (), {"text": "Approved fact", "use_in_draft": False})()

    assert content_was_changed(record, {"use_in_draft": True}) is False
    assert content_was_changed(record, {"text": "Changed fact"}) is True
