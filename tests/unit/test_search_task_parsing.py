"""Manual Search Task parsing remains conservative and language-independent."""

from app.modules.search_tasks.parsing import (
    detect_query_language,
    infer_search_task_intent,
    parse_search_query,
)
from app.modules.search_tasks.schemas import SearchTaskCreate


def test_parses_confident_russian_constraints() -> None:
    parsed = parse_search_query(
        "Найди 10 компаний в Мексике в логистике для Business Development и Expansion"
    )

    assert parsed.language == "mixed"
    assert parsed.country == "Mexico"
    assert parsed.industry == "Logistics"
    assert parsed.focus == "Business Development"
    assert parsed.explicit_limit == 10


def test_parses_equivalent_english_constraints() -> None:
    parsed = parse_search_query("Find 5 companies in Mexico in logistics for Business Development")

    assert parsed.language == "en"
    assert parsed.country == "Mexico"
    assert parsed.industry == "Logistics"
    assert parsed.focus == "Business Development"
    assert parsed.explicit_limit == 5


def test_unknown_language_and_uncertain_limit_are_not_invented() -> None:
    parsed = parse_search_query("会社を探す 50")

    assert parsed.language == "unknown"
    assert parsed.country is None
    assert parsed.industry is None
    assert parsed.focus is None
    assert parsed.explicit_limit is None


def test_direct_url_is_normalized_separately_from_original_query() -> None:
    original = "  Analyze https://www.airalo.com/about, please  "
    payload = SearchTaskCreate(original_query=original)
    parsed = parse_search_query(payload.original_query)

    assert payload.original_query == original
    assert parsed.direct_target == "https://www.airalo.com/about"
    assert detect_query_language(original) == "en"


def test_natural_language_infers_list_or_single_company() -> None:
    assert infer_search_task_intent("Найди 5 компаний в Мексике") == (
        "find_companies",
        None,
    )
    assert infer_search_task_intent("Проанализируй компанию Airalo") == (
        "analyze_company",
        "Airalo",
    )
    assert infer_search_task_intent("Analyze https://airalo.com/about") == (
        "analyze_company",
        "https://airalo.com/about",
    )
