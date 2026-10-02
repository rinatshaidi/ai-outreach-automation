from datetime import UTC, datetime
from uuid import uuid4

from app.modules.candidate_profile.models import (
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateSkill,
)
from app.modules.crm.models import Company, Contact
from app.modules.opportunities.models import CompanyOpportunity, OpportunitySignal
from app.modules.relevance.scoring import (
    FORMULA_VERSION,
    THRESHOLD_OPPORTUNITY,
    calculate_assessment,
    relevance_status,
)
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis


def scoring_fixture(company_size: str = "large") -> dict[str, object]:
    profile_id = uuid4()
    company_id = uuid4()
    source_id = uuid4()
    profile = CandidateProfile(
        id=profile_id,
        version=4,
        collaboration_formats=["project_based", "consulting"],
        workplace_formats=["remote", "relocation"],
        remote_work_countries=["Germany"],
        relocation_countries=["Germany"],
        business_trip_countries=[],
        desired_roles=["Market Launch Lead"],
    )
    company = Company(
        id=company_id,
        name="Synthetic Company",
        normalized_domain="synthetic.example",
        country="Germany",
        company_size=company_size,
        opportunity_types=[],
        recommended_collaboration_formats=[],
        recommended_workplace_formats=[],
        language_signals=[],
    )
    experience = CandidateExperience(
        id=uuid4(),
        profile_id=profile_id,
        position="Operations Lead",
        verified=True,
        store_private=True,
        contractor_management=True,
        negotiations=True,
        territory_development=True,
        launches=True,
        operations_management=True,
    )
    skill = CandidateSkill(
        id=uuid4(),
        profile_id=profile_id,
        name="AI workflow delivery",
        skill_group="ai",
        actual_level="practical",
        limitations="No model-training claim",
        verified=True,
        store_private=True,
    )
    candidate_fact = CandidateFact(
        id=uuid4(),
        profile_id=profile_id,
        fact_type="skill",
        text="Synthetic verified automation project",
        verified=True,
        store_private=True,
    )
    opportunity = CompanyOpportunity(
        id=uuid4(),
        company_id=company_id,
        opportunity_type="hybrid_opportunity",
        source_ids=[str(source_id)],
        signal_ids=[],
        rationale="Verified synthetic hybrid opportunity",
        confidence=0.9,
        status="verified",
    )
    signal = OpportunitySignal(
        id=uuid4(),
        company_id=company_id,
        source_id=source_id,
        signal_type="market_entry",
        title="Market entry",
        description="Synthetic verified entry",
        detected_at=datetime.now(UTC),
        confidence=0.9,
        exact_fragment="Synthetic market entry",
        status="verified",
    )
    contact = Contact(
        id=uuid4(),
        company_id=company_id,
        name="Synthetic COO",
        email="coo@synthetic.example",
        verification_status="verified_public",
        decision_maker_role="coo",
        decision_priority=1,
    )
    company_fact = CompanyFact(
        id=uuid4(),
        company_id=company_id,
        source_id=source_id,
        fact_type="company_activity",
        value="Synthetic expansion",
        exact_fragment="Synthetic expansion",
        confidence=0.9,
        status="verified",
    )
    hypothesis = CompanyTaskHypothesis(
        id=uuid4(),
        company_id=company_id,
        source_ids=[str(source_id)],
        title="Launch coordination",
        description="Potential launch coordination task",
        rationale="Explicitly a hypothesis",
        confidence=0.5,
        status="hypothesis",
        risks=["Internal need is not confirmed"],
    )
    return {
        "company": company,
        "profile": profile,
        "experiences": [experience],
        "skills": [skill],
        "candidate_facts": [candidate_fact],
        "opportunities": [opportunity],
        "signals": [signal],
        "contacts": [contact],
        "company_facts": [company_fact],
        "hypotheses": [hypothesis],
    }


def test_scoring_is_deterministic_and_has_complete_breakdown() -> None:
    inputs = scoring_fixture()
    first = calculate_assessment(**inputs)  # type: ignore[arg-type]
    second = calculate_assessment(**inputs)  # type: ignore[arg-type]

    assert first == second
    assert first.model_or_rule_version == FORMULA_VERSION
    assert first.score_breakdown.formula_version == FORMULA_VERSION
    assert set(first.score_breakdown.contributions) >= {
        "business_fit_score",
        "ai_automation_fit_score",
        "hybrid_fit_score",
        "format_fit_score",
        "geography_fit_score",
        "timing_signal_score",
        "contactability_score",
        "value_proposition_realism",
        "overall_opportunity_score",
    }
    assert 0 < first.overall_opportunity_score < THRESHOLD_OPPORTUNITY
    # A generic hybrid tag is not evidence of any one approved owner track.
    assert relevance_status(first.overall_opportunity_score) == "not_relevant"


def test_company_size_does_not_change_score() -> None:
    large = calculate_assessment(**scoring_fixture("large"))  # type: ignore[arg-type]
    startup = calculate_assessment(**scoring_fixture("startup"))  # type: ignore[arg-type]
    assert large.overall_opportunity_score == startup.overall_opportunity_score


def test_missing_opportunity_or_signal_cannot_receive_baseline_fit_points() -> None:
    inputs = scoring_fixture()
    inputs["signals"] = []
    inputs["opportunities"] = []
    result = calculate_assessment(**inputs)  # type: ignore[arg-type]
    assert result.timing_signal_score == 0
    assert result.business_fit_score == 0
    assert result.ai_automation_fit_score == 0


def test_thresholds_are_explicit() -> None:
    assert relevance_status(70) == "opportunity_identified"
    assert relevance_status(45) == "needs_review"
    assert relevance_status(44.99) == "not_relevant"
    assert relevance_status(20, evidence_sufficient=False) == "needs_review"


def test_custom_weights_are_used_and_preserved() -> None:
    weights = {
        "core_fit": 0.25,
        "format_fit_score": 0.25,
        "geography_fit_score": 0.20,
        "timing_signal_score": 0.10,
        "contactability_score": 0.10,
        "value_proposition_realism": 0.10,
    }
    default = calculate_assessment(**scoring_fixture())  # type: ignore[arg-type]
    custom = calculate_assessment(**scoring_fixture(), weights=weights)  # type: ignore[arg-type]

    assert custom.score_breakdown.weights == weights
    assert custom.overall_opportunity_score != default.overall_opportunity_score
