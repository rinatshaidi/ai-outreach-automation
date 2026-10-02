from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.candidate_profile.models import CandidateContact, CandidateFact
from app.modules.crm.models import Company, Contact
from app.modules.generation.schemas import (
    ApprovedWritingExampleCreate,
    DraftFormat,
    DraftRecipientChange,
    DraftRegenerateCreate,
    DraftReviewDecisionCreate,
    DraftStatus,
)
from app.modules.generation.service import (
    GenerationContext,
    LocalStructuredGenerationAdapter,
    choose_language,
    primary_match_fingerprint,
    validate_draft,
)
from app.modules.opportunities.models import CompanyOpportunity, PositioningRecommendation
from app.modules.research.models import CompanyFact


def generation_context(*, verified_contact: bool = True) -> GenerationContext:
    company_id = uuid4()
    profile_id = uuid4()
    source_id = uuid4()
    opportunity_id = uuid4()
    company_fact_id = uuid4()
    candidate_fact_id = uuid4()
    return GenerationContext(
        company=Company(
            id=company_id,
            name="Synthetic Operations",
            normalized_domain="synthetic-operations.example",
            language_signals=["en"],
        ),
        contact=Contact(
            id=uuid4(),
            company_id=company_id,
            name="Jordan Example",
            email="jordan@synthetic-operations.example",
            verification_status="verified" if verified_contact else "unverified",
        ),
        recommendation=PositioningRecommendation(
            id=uuid4(),
            company_id=company_id,
            assessment_id=uuid4(),
            primary_strategy="business_first",
            primary_message_line="Operations leadership first",
            secondary_advantage="Practical automation",
            rationale="Verified fit",
            value_proposition="Improve operational visibility",
            concrete_first_message_offer="map one workflow and identify a measurable pilot",
            primary_decision_maker_role="coo",
            secondary_decision_maker_role="head_of_operations",
            collaboration_format="project_based",
            possible_role="Operations automation lead",
        ),
        opportunities=[
            CompanyOpportunity(
                id=opportunity_id,
                company_id=company_id,
                opportunity_type="operations_improvement",
                rationale="Verified operational fit",
                confidence=0.9,
                status="verified",
            )
        ],
        signals=[],
        company_facts=[
            CompanyFact(
                id=company_fact_id,
                company_id=company_id,
                source_id=source_id,
                fact_type="activity",
                value="the company operates a distributed service network",
                exact_fragment="distributed service network",
                confidence=0.9,
                status="verified",
            )
        ],
        candidate_facts=[
            CandidateFact(
                id=candidate_fact_id,
                profile_id=profile_id,
                fact_type="experience",
                text="operational project delivery and workflow automation",
                verified=True,
                store_private=True,
                use_in_draft=True,
            )
        ],
        signature_contacts=[
            CandidateContact(
                id=uuid4(),
                profile_id=profile_id,
                contact_type="email",
                value="owner@example.test",
                verified=True,
                store_private=True,
                use_in_draft=True,
                allowed_in_signature=True,
            )
        ],
        rules=[],
        language=choose_language(
            Company(language_signals=["en"], name="x", normalized_domain="x.example"),
            "auto",
            [],
        ),
        campaign_goal="explore a small operational automation pilot",
        prompt_version="outreach-generation-v1",
        min_words=80,
        max_words=160,
        decision_brief={
            "draft_primary_match": {
                "company_context": "the company operates a distributed service network",
                "outreach_company_fact": "The company operates a distributed service network.",
                "relevant_candidate_evidence": (
                    "operational project delivery and workflow automation"
                ),
                "intersection": "The company context connects to verified operations experience.",
                "value_hypothesis": "help structure a repeatable operating process",
                "outreach_angle": (
                    "I would welcome a short conversation about whether this experience could "
                    "help with analysing one concrete workflow."
                ),
                "opportunity_id": str(opportunity_id),
                "company_fact_id": str(company_fact_id),
                "candidate_ids": [str(candidate_fact_id)],
                "source_id": str(source_id),
                "signal_id": "",
            }
        },
    )


def test_language_selection_uses_manual_override_and_safe_fallback() -> None:
    company = Company(name="x", normalized_domain="x.example", language_signals=[])
    assert choose_language(company, "ru", []).code == "ru"
    fallback = choose_language(company, "auto", [])
    assert fallback.code == "en"
    assert fallback.needs_review is True


def test_primary_match_fingerprint_changes_with_owner_visible_collaboration_angle() -> None:
    primary = generation_context().decision_brief["draft_primary_match"]
    changed = {**primary, "value_hypothesis": "different, current hypothesis"}

    assert primary_match_fingerprint(primary) == primary_match_fingerprint(dict(primary))
    assert primary_match_fingerprint(primary) != primary_match_fingerprint(changed)


@pytest.mark.asyncio
async def test_adapter_returns_format_and_tone_matrix() -> None:
    context = replace(generation_context(), min_words=120, max_words=250)
    drafts = await LocalStructuredGenerationAdapter().generate(context)

    assert [item.variant.value for item in drafts] == ["A", "B", "C", "D"]
    assert {(item.message_format.value, item.tone.value) for item in drafts} == {
        ("expanded", "professional"),
        ("expanded", "friendly"),
        ("short", "professional"),
        ("short", "friendly"),
    }
    assert context.company.name in drafts[0].subject
    assert len({item.body for item in drafts}) == 4
    assert "operational project delivery and workflow automation" in drafts[0].body
    assert drafts[1].body.startswith("Hello Jordan Example,")
    forbidden = ("my verified background", "public materials report", "campaign goal")
    for draft in drafts:
        report = validate_draft(draft, context, outreach_allowed=True)
        assert report.passed, report.model_dump()
        if draft.message_format == DraftFormat.SHORT:
            assert 25 <= len(draft.body.split()) <= 90
        else:
            assert 120 <= len(draft.body.split()) <= 250
        assert not any(marker in draft.body.casefold() for marker in forbidden)
        assert draft.candidate_fact_ids == [context.candidate_facts[0].id]
        assert draft.company_fact_ids == [context.company_facts[0].id]
        assert draft.opportunity_type_ids == [context.opportunities[0].id]
        assert [str(item) for item in draft.source_ids] == [
            str(context.company_facts[0].source_id)
        ]
        assert "reference the verified company context" not in draft.body.casefold()
        assert "сослаться на" not in draft.body.casefold()


@pytest.mark.asyncio
async def test_validator_blocks_unverified_contact_and_closed_decision_gate() -> None:
    context = generation_context(verified_contact=False)
    draft = (await LocalStructuredGenerationAdapter().generate(context))[0]
    report = validate_draft(draft, context, outreach_allowed=False)

    assert report.passed is False
    codes = {item.code for item in report.issues}
    assert {"CONTACT_NOT_VERIFIED", "OUTREACH_DECISION_REQUIRED"} <= codes
    assert DraftStatus.BLOCKED.value == "blocked"


def test_review_decision_requires_explicit_confirmation() -> None:
    with pytest.raises(ValidationError, match="explicit confirmation"):
        DraftReviewDecisionCreate(revision=1, confirmed=False)


def test_recipient_change_requires_explicit_confirmation() -> None:
    with pytest.raises(ValidationError, match="explicit confirmation"):
        DraftRecipientChange(revision=1, contact_id=uuid4(), confirmed=False)

    change = DraftRecipientChange(revision=1, contact_id=uuid4(), confirmed=True)
    assert change.confirmed is True


def test_regeneration_language_is_explicit_and_independent_from_dashboard_locale() -> None:
    assert DraftRegenerateCreate(revision=1, campaign_goal="Keep it focused").language == "same"
    assert (
        DraftRegenerateCreate(
            revision=1, campaign_goal="Keep it focused", language="en"
        ).language
        == "en"
    )


@pytest.mark.asyncio
async def test_adapter_refuses_company_without_evidenced_profile_fit() -> None:
    context = generation_context()
    context = replace(context, decision_brief={})
    with pytest.raises(ValueError, match="draft_primary_match_missing"):
        await LocalStructuredGenerationAdapter().generate(context)


@pytest.mark.asyncio
async def test_adapter_keeps_russian_message_in_russian() -> None:
    context = generation_context()
    context.company.name = "Тестовая компания"
    context.company_facts[0].value = "Компания развивает операционные процессы."
    context.candidate_facts[0].text = "управление операционными процессами"
    context = replace(
        context,
        language=choose_language(context.company, "ru", []),
        decision_brief={
            "draft_primary_match": {
                "company_context": "Компания развивает операционные процессы.",
                "outreach_company_fact": "Компания развивает операционные процессы.",
                "relevant_candidate_evidence": "управление операционными процессами",
                "intersection": "Контекст компании связан с подтверждённым опытом.",
                "value_hypothesis": "помочь структурировать операционный процесс",
                "outreach_angle": (
                    "Мне было бы интересно коротко обсудить, может ли такой опыт быть полезен "
                    "для конкретного рабочего процесса."
                ),
                "opportunity_id": str(context.opportunities[0].id),
                "company_fact_id": str(context.company_facts[0].id),
                "candidate_ids": [str(context.candidate_facts[0].id)],
                "source_id": str(context.company_facts[0].source_id),
                "signal_id": "",
            }
        },
    )
    drafts = await LocalStructuredGenerationAdapter().generate(context)
    assert all("операцион" in draft.body.casefold() for draft in drafts)
    assert all("Dear " not in draft.body for draft in drafts)


@pytest.mark.asyncio
async def test_adapter_refuses_incomplete_company_source_fragment() -> None:
    primary = generation_context().decision_brief["draft_primary_match"]
    context = replace(
        generation_context(),
        decision_brief={
            "draft_primary_match": {
                **primary,
                "outreach_company_fact": "The company compares actual work to a schedule",
            }
        },
    )

    with pytest.raises(ValueError, match="draft_primary_match_missing"):
        await LocalStructuredGenerationAdapter().generate(context)


def test_approved_style_example_requires_explicit_owner_confirmation() -> None:
    with pytest.raises(ValidationError, match="explicit owner confirmation"):
        ApprovedWritingExampleCreate(
            language="en",
            company_context="Example company",
            purpose="outreach",
            text="A sufficiently long owner-approved example message.",
            approved=True,
        )

    payload = ApprovedWritingExampleCreate(
        language="en",
        company_context="Example company",
        purpose="outreach",
        text="A sufficiently long owner-approved example message.",
        approved=True,
        confirmed=True,
    )
    assert payload.approved is True
