"""Deterministic secondary ranking for evidence-backed opportunity matching."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from app.config import get_settings
from app.modules.candidate_profile.models import (
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateSkill,
)
from app.modules.crm.models import Company, Contact
from app.modules.opportunities.models import CompanyOpportunity, OpportunitySignal
from app.modules.opportunities.schemas import (
    CollaborationFormat,
    OpportunityAssessmentCreate,
    ScoreBreakdown,
    ScoreContribution,
    WorkplaceFormat,
)
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis

FORMULA_VERSION = "opportunity-relevance-v2"
THRESHOLD_OPPORTUNITY = 70.0
THRESHOLD_REVIEW = 45.0
DEFAULT_WEIGHTS = {
    "core_fit": 0.40,
    "format_fit_score": 0.15,
    "geography_fit_score": 0.10,
    "timing_signal_score": 0.10,
    "contactability_score": 0.10,
    "value_proposition_realism": 0.15,
}

BUSINESS_OPPORTUNITIES = {
    "business_expansion",
    "market_entry",
    "operations_improvement",
    "new_product_or_direction",
    "active_hiring",
    "investment_or_growth",
    "project_work",
    "consulting",
    "local_representation",
}
AI_OPPORTUNITIES = {"ai_adoption", "process_automation"}
SKILL_LEVEL_POINTS = {
    "learning": 4.0,
    "foundational": 8.0,
    "practical": 15.0,
    "proficient": 22.0,
    "advanced": 28.0,
}


def clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def relevance_status(score: float, *, evidence_sufficient: bool = True) -> str:
    if not evidence_sufficient:
        return "needs_review"
    if score >= THRESHOLD_OPPORTUNITY:
        return "opportunity_identified"
    if score >= THRESHOLD_REVIEW:
        return "needs_review"
    return "not_relevant"


def contribution(
    factor: str,
    points: float,
    rationale: str,
    *,
    candidate_fact_ids: list[object] | None = None,
    company_fact_ids: list[object] | None = None,
    source_ids: list[object] | None = None,
) -> ScoreContribution:
    return ScoreContribution(
        factor=factor,
        points=round(points, 2),
        rationale=rationale,
        candidate_fact_ids=candidate_fact_ids or [],
        company_fact_ids=company_fact_ids or [],
        source_ids=source_ids or [],
    )


def calculate_assessment(
    *,
    company: Company,
    profile: CandidateProfile,
    experiences: Iterable[CandidateExperience],
    skills: Iterable[CandidateSkill],
    candidate_facts: Iterable[CandidateFact],
    opportunities: Iterable[CompanyOpportunity],
    signals: Iterable[OpportunitySignal],
    contacts: Iterable[Contact],
    company_facts: Iterable[CompanyFact],
    hypotheses: Iterable[CompanyTaskHypothesis],
    weights: Mapping[str, float] | None = None,
) -> OpportunityAssessmentCreate:
    formula_weights = dict(weights or DEFAULT_WEIGHTS)
    if set(formula_weights) != set(DEFAULT_WEIGHTS):
        raise ValueError("Scoring weights must contain every formula factor")
    if abs(sum(formula_weights.values()) - 1.0) > 0.000001:
        raise ValueError("Scoring weights must sum to 1.0")
    experiences = list(experiences)
    skills = list(skills)
    candidate_facts = list(candidate_facts)
    opportunities = list(opportunities)
    signals = list(signals)
    contacts = list(contacts)
    company_facts = list(company_facts)
    hypotheses = list(hypotheses)
    scoring_permission_required = get_settings().auth_required
    verified_experiences = [
        item
        for item in experiences
        if item.verified
        and item.store_private
        and (item.use_in_scoring or not scoring_permission_required)
    ]
    verified_skills = [
        item
        for item in skills
        if item.verified
        and item.store_private
        and (item.use_in_scoring or not scoring_permission_required)
    ]
    verified_candidate_facts = [
        item
        for item in candidate_facts
        if item.verified
        and item.store_private
        and (item.use_in_scoring or not scoring_permission_required)
    ]
    active_opportunities = [item for item in opportunities if item.status != "rejected"]
    opportunity_types = {item.opportunity_type for item in active_opportunities}
    verified_company_facts = [item for item in company_facts if item.status == "verified"]

    breakdown: dict[str, list[ScoreContribution]] = {}

    business_parts: list[ScoreContribution] = []
    matching_business = opportunity_types & BUSINESS_OPPORTUNITIES
    experience_points = min(36.0, len(verified_experiences) * 12.0) if matching_business else 0.0
    if experience_points:
        business_parts.append(
            contribution(
                "verified_experience",
                experience_points,
                "Verified management or project experience linked to a company opportunity",
            )
        )
    capability_count = sum(
        int(getattr(item, field))
        for item in verified_experiences
        for field in (
            "contractor_management",
            "negotiations",
            "territory_development",
            "launches",
            "operations_management",
        )
    )
    if matching_business:
        business_parts.append(
            contribution(
                "business_capabilities",
                min(25.0, capability_count * 5.0),
                "Verified operational capabilities linked to a company opportunity",
            )
        )
    business_parts.append(
        contribution(
            "business_opportunity_match",
            min(24.0, len(matching_business) * 8.0),
            "Company opportunity types match business, operations or expansion experience",
            source_ids=[
                source_id for item in active_opportunities for source_id in item.source_ids
            ],
        )
    )
    business_score = clamp(sum(item.points for item in business_parts))
    breakdown["business_fit_score"] = business_parts

    ai_parts: list[ScoreContribution] = []
    matching_ai = opportunity_types & AI_OPPORTUNITIES
    relevant_skills = [
        item for item in verified_skills if item.skill_group in {"ai", "technology"}
    ]
    skill_points = min(
        56.0,
        sum(SKILL_LEVEL_POINTS.get(item.actual_level, 0) for item in relevant_skills),
    )
    if matching_ai:
        ai_parts.append(
            contribution(
                "verified_ai_skills",
                skill_points,
                "Verified practical AI/technology skills linked to a company opportunity",
            )
        )
    legacy_ai_facts = [
        item for item in verified_candidate_facts if item.fact_type in {"skill", "technology"}
    ]
    if matching_ai and legacy_ai_facts:
        ai_parts.append(
            contribution(
                "verified_legacy_skill_facts",
                min(15.0, len(legacy_ai_facts) * 5.0),
                "Verified legacy Candidate Profile skill facts remain usable",
                candidate_fact_ids=[item.id for item in legacy_ai_facts],
            )
        )
    if matching_ai:
        ai_parts.append(
            contribution(
                "ai_opportunity_match",
                min(30.0, len(matching_ai) * 15.0),
                "AI or automation opportunity types are present",
            )
        )
    ai_score = clamp(sum(item.points for item in ai_parts))
    breakdown["ai_automation_fit_score"] = ai_parts

    hybrid_score = clamp(business_score * 0.45 + ai_score * 0.45)
    breakdown["hybrid_fit_score"] = [
        contribution(
            "combined_fit",
            hybrid_score,
            (
                "Hybrid fit combines independently evidenced business and AI fit "
                "with an explicit hybrid bonus"
            ),
        )
    ]

    collaboration = set(profile.collaboration_formats)
    workplace = set(profile.workplace_formats)
    format_parts: list[ScoreContribution] = []
    if "open_vacancy" in opportunity_types and "full_time" in collaboration:
        format_parts.append(
            contribution("full_time_match", 20, "Full-time is allowed for vacancy-led work")
        )
    if "project_work" in opportunity_types and "project_based" in collaboration:
        format_parts.append(
            contribution("project_match", 25, "Project-based collaboration is allowed")
        )
    if "consulting" in opportunity_types and "consulting" in collaboration:
        format_parts.append(
            contribution("consulting_match", 25, "Consulting collaboration is allowed")
        )
    if "local_representation" in opportunity_types and "local_representative" in collaboration:
        format_parts.append(
            contribution("local_representation_match", 25, "Local representation is allowed")
        )
    format_score = clamp(sum(item.points for item in format_parts))
    breakdown["format_fit_score"] = format_parts

    geography_parts: list[ScoreContribution] = []
    country = (company.country or "").casefold()
    remote_countries = {item.casefold() for item in profile.remote_work_countries}
    relocation_countries = {item.casefold() for item in profile.relocation_countries}
    travel_countries = {item.casefold() for item in profile.business_trip_countries}
    if country and country in remote_countries and "remote" in workplace:
        geography_parts.append(
            contribution(
                "remote_country_match", 25, "Remote work is allowed for the company country"
            )
        )
    if country and country in relocation_countries and "relocation" in workplace:
        geography_parts.append(
            contribution("relocation_match", 30, "Relocation is allowed for the company country")
        )
    if country and country in travel_countries:
        geography_parts.append(
            contribution(
                "business_trip_match", 15, "Business travel is allowed for the company country"
            )
        )
    geography_score = clamp(sum(item.points for item in geography_parts))
    breakdown["geography_fit_score"] = geography_parts

    timing_parts: list[ScoreContribution] = []
    now = datetime.now(UTC)
    for signal in signals:
        if signal.status in {"rejected", "stale"}:
            continue
        age_days = max(0, (now - signal.detected_at).days)
        freshness = 1.0 if age_days <= 90 else 0.6 if age_days <= 365 else 0.3
        evidence = 1.0 if signal.status == "verified" else 0.65
        points = min(20.0, signal.confidence * freshness * evidence * 20.0)
        timing_parts.append(
            contribution(
                signal.signal_type,
                points,
                f"Signal confidence adjusted for {age_days}-day freshness and evidence status",
                source_ids=[signal.source_id] if signal.source_id else [],
            )
        )
    timing_score = clamp(sum(item.points for item in timing_parts))
    breakdown["timing_signal_score"] = timing_parts

    contact_parts: list[ScoreContribution] = []
    contact_scores: list[float] = []
    for contact in contacts:
        if contact.do_not_contact or contact.verification_status in {
            "invalid",
            "suppressed",
            "rejected",
        }:
            continue
        score = 35.0 if contact.verification_status == "unverified" else 70.0
        if contact.decision_maker_role:
            score += 20.0
        if contact.decision_priority == 1:
            score += 10.0
        contact_scores.append(score)
    if contact_scores:
        contact_parts.append(
            contribution(
                "best_public_contact",
                max(contact_scores),
                "Best lawful public decision-maker route",
            )
        )
    contact_score = clamp(max((item.points for item in contact_parts), default=0.0))
    breakdown["contactability_score"] = contact_parts

    realism_parts: list[ScoreContribution] = []
    verified_opportunities = [item for item in active_opportunities if item.status == "verified"]
    if verified_opportunities:
        realism_parts.extend(
            [
                contribution(
                    "verified_company_facts",
                    min(30.0, len(verified_company_facts) * 10.0),
                    "Verified company facts support the proposed value",
                    company_fact_ids=[item.id for item in verified_company_facts],
                    source_ids=[item.source_id for item in verified_company_facts],
                ),
                contribution(
                    "verified_candidate_facts",
                    min(25.0, len(verified_candidate_facts) * 5.0),
                    "Verified Candidate Profile facts support claims",
                    candidate_fact_ids=[item.id for item in verified_candidate_facts],
                ),
                contribution(
                    "verified_opportunities",
                    min(25.0, len(verified_opportunities) * 12.5),
                    "Verified opportunities strengthen value-proposition realism",
                ),
            ]
        )
    value_realism = clamp(sum(item.points for item in realism_parts))
    breakdown["value_proposition_realism"] = realism_parts

    core_fit = max(business_score, ai_score, hybrid_score)
    overall = clamp(
        core_fit * formula_weights["core_fit"]
        + format_score * formula_weights["format_fit_score"]
        + geography_score * formula_weights["geography_fit_score"]
        + timing_score * formula_weights["timing_signal_score"]
        + contact_score * formula_weights["contactability_score"]
        + value_realism * formula_weights["value_proposition_realism"]
    )
    breakdown["overall_opportunity_score"] = [
        contribution(
            factor,
            score * formula_weights[factor],
            f"{formula_weights[factor]:.0%} × {label}",
        )
        for factor, score, label in (
            ("core_fit", core_fit, "maximum of business, AI and hybrid fit"),
            ("format_fit_score", format_score, "format fit"),
            ("geography_fit_score", geography_score, "geography fit"),
            ("timing_signal_score", timing_score, "timing signal fit"),
            ("contactability_score", contact_score, "contactability"),
            ("value_proposition_realism", value_realism, "value-proposition realism"),
        )
    ]

    candidate_fact_ids = [item.id for item in verified_candidate_facts]
    company_fact_ids = [item.id for item in company_facts if item.status != "rejected"]
    source_ids = list(
        dict.fromkeys(
            [item.source_id for item in company_facts]
            + [item.source_id for item in signals if item.source_id]
        )
    )
    risks = list(dict.fromkeys(risk for item in hypotheses for risk in item.risks))
    warnings = [
        "Company size, maturity and absence of a vacancy are not negative factors by themselves"
    ]
    if not verified_company_facts:
        warnings.append("No verified company facts; value-proposition realism remains conservative")
    if not signals:
        warnings.append("No opportunity signal; GENERAL_COMPETENCE_FIT remains reviewable")

    recommended_collaboration: list[CollaborationFormat] = []
    for value in profile.collaboration_formats:
        try:
            recommended_collaboration.append(CollaborationFormat(value))
        except ValueError:
            continue
    recommended_workplace: list[WorkplaceFormat] = []
    for value in profile.workplace_formats:
        try:
            recommended_workplace.append(WorkplaceFormat(value))
        except ValueError:
            continue

    return OpportunityAssessmentCreate(
        candidate_profile_version=profile.version,
        business_fit_score=business_score,
        ai_automation_fit_score=ai_score,
        hybrid_fit_score=hybrid_score,
        format_fit_score=format_score,
        geography_fit_score=geography_score,
        timing_signal_score=timing_score,
        contactability_score=contact_score,
        overall_opportunity_score=overall,
        score_breakdown=ScoreBreakdown(
            formula_version=FORMULA_VERSION,
            weights=formula_weights,
            contributions=breakdown,
            warnings=warnings,
        ),
        opportunity_ids=[item.id for item in active_opportunities],
        candidate_fact_ids=candidate_fact_ids,
        company_fact_ids=company_fact_ids,
        opportunity_signal_ids=[item.id for item in signals if item.status != "rejected"],
        source_ids=source_ids,
        possible_business_tasks=[
            item.description for item in hypotheses if item.status != "rejected"
        ],
        candidate_value_hypotheses=[
            item.rationale for item in hypotheses if item.status != "rejected"
        ],
        recommended_collaboration_formats=recommended_collaboration,
        recommended_workplace_formats=recommended_workplace,
        possible_roles=list(profile.desired_roles),
        reasons_to_contact=[item.rationale for item in active_opportunities],
        reasons_not_to_contact=(
            ["Overall deterministic score is below the review threshold"]
            if overall < THRESHOLD_REVIEW
            else []
        ),
        risks=risks,
        next_action=(
            "Select positioning strategy"
            if overall >= THRESHOLD_OPPORTUNITY
            else "Review evidence and opportunity hypotheses"
            if overall >= THRESHOLD_REVIEW
            else "Do not pursue unless new evidence appears"
        ),
        model_or_rule_version=FORMULA_VERSION,
    )
