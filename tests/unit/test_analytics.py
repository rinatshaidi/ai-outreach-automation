"""Pure analytics aggregation helpers."""

from collections import Counter

from app.modules.analytics.service import breakdown, count_multi, metric_names
from app.modules.crm.models import Company


def test_multi_value_breakdown_counts_each_company_once_per_value() -> None:
    companies = [
        Company(
            name="Synthetic A",
            normalized_domain="a.example",
            opportunity_types=[
                "general_competence_fit",
                "general_competence_fit",
                "process_automation",
            ],
        ),
        Company(
            name="Synthetic B",
            normalized_domain="b.example",
            opportunity_types=[],
        ),
    ]

    result = count_multi(companies, "opportunity_types")

    assert result == Counter({"general_competence_fit": 1, "process_automation": 1, "none": 1})


def test_breakdown_is_sorted_by_count_then_key() -> None:
    result = breakdown(Counter({"hybrid": 2, "business_first": 3, "ai_first": 2}))

    assert [(item.key, item.companies) for item in result] == [
        ("business_first", 3),
        ("ai_first", 2),
        ("hybrid", 2),
    ]


def test_metric_contract_contains_quality_and_outcome_kpis() -> None:
    names = set(metric_names())

    assert {
        "opportunities_without_vacancy",
        "hybrid",
        "positive_replies",
        "project_discussions",
        "followups_due",
        "average_hours_to_current_stage",
    } <= names
