from types import SimpleNamespace
from uuid import uuid4

from app.modules.candidate_profile.models import CandidateFact
from app.modules.opportunities.quality import (
    build_match_theses,
    company_evidence_excerpt,
    language_matches,
    quality_checks,
    ready_for_inbox,
    supported_matches,
)
from app.modules.research.models import CompanyFact


def candidate_fact(*, permitted: bool = True) -> CandidateFact:
    return CandidateFact(
        id=uuid4(),
        profile_id=uuid4(),
        fact_type="experience",
        text="управление операционными процессами",
        verified=True,
        store_private=True,
        use_in_scoring=permitted,
        use_in_draft=permitted,
    )


def company_fact() -> CompanyFact:
    return CompanyFact(
        id=uuid4(),
        company_id=uuid4(),
        source_id=uuid4(),
        fact_type="activity",
        value="Компания развивает операционные процессы для распределённой команды.",
        exact_fragment="операционные процессы",
        confidence=0.9,
        status="verified",
    )


def test_fit_requires_evidence_on_both_sides_and_permission() -> None:
    evidence = company_fact()
    assert supported_matches([candidate_fact()], [evidence], "ru")
    assert not supported_matches([candidate_fact(permitted=False)], [evidence], "ru")
    assert not supported_matches([candidate_fact()], [], "ru")


def test_generic_project_word_does_not_create_a_professional_fit() -> None:
    record = CandidateFact(
        id=uuid4(),
        profile_id=uuid4(),
        fact_type="experience",
        text="участие в проекте",
        verified=True,
        store_private=True,
        use_in_scoring=True,
    )
    evidence = CompanyFact(
        id=uuid4(),
        company_id=uuid4(),
        source_id=uuid4(),
        fact_type="activity",
        value="Компания запускает новый проект.",
        exact_fragment="новый проект",
        confidence=0.8,
        status="verified",
    )

    assert not supported_matches([record], [evidence], "ru")


def test_fit_evidence_removes_cookie_banner_and_duplicate_chrome() -> None:
    raw = (
        "Bechtel: Инжиниринг, строительство, закупки и управление проектами. "
        "Пропустить к содержимому. Этот веб-сайт использует файлы cookie."
    )

    assert company_evidence_excerpt(raw) == (
        "Bechtel: Инжиниринг, строительство, закупки и управление проектами"
    )


def test_cookie_banner_is_not_fit_evidence() -> None:
    evidence = company_fact()
    evidence.value = "Этот веб-сайт использует файлы cookie. Принять все."

    assert not supported_matches([candidate_fact()], [evidence], "ru")


def test_match_thesis_requires_a_source_backed_company_opportunity() -> None:
    source_id = uuid4()
    signal_id = uuid4()
    experience = SimpleNamespace(
        id=uuid4(),
        verified=True,
        store_private=True,
        use_in_scoring=True,
        contractor_management=True,
        launches=True,
        operations_management=True,
        skill_group=None,
        actual_level="",
    )
    fact = company_fact()
    fact.source_id = source_id
    opportunity = SimpleNamespace(
        opportunity_type="project_work",
        status="verified",
        source_ids=[str(source_id)],
        signal_ids=[str(signal_id)],
    )

    theses = build_match_theses(
        [experience],
        [fact],
        [opportunity],
        [],
        [],
        "ru",
    )

    assert len(theses) == 1
    assert theses[0]["track"] == "project_delivery"
    assert theses[0]["state"] == "match_confirmed_contact_pending"
    assert theses[0]["candidate_ids"] == [str(experience.id)]
    assert theses[0]["company_fact_id"] == str(fact.id)
    assert theses[0]["opportunity_id"] == ""
    assert theses[0]["candidate_evidence"] == "Запуск проектов и операционное управление"


def test_match_thesis_does_not_accept_generic_or_unlinked_opportunity() -> None:
    source_id = uuid4()
    experience = SimpleNamespace(
        id=uuid4(),
        verified=True,
        store_private=True,
        use_in_scoring=True,
        contractor_management=True,
        launches=False,
        operations_management=False,
        skill_group=None,
        actual_level="",
    )
    fact = company_fact()
    fact.source_id = source_id
    generic = SimpleNamespace(
        opportunity_type="general_competence_fit",
        status="verified",
        source_ids=[str(source_id)],
        signal_ids=[],
    )
    unlinked = SimpleNamespace(
        opportunity_type="project_work",
        status="verified",
        source_ids=[str(uuid4())],
        signal_ids=[],
    )

    assert not build_match_theses([experience], [fact], [generic], [], [], "ru")
    assert not build_match_theses([experience], [fact], [unlinked], [], [], "ru")


def test_language_guard_rejects_mixed_dynamic_prose() -> None:
    assert language_matches("Компания развивает операционные процессы.", "ru")
    assert language_matches("The company develops operational workflows.", "en")
    assert not language_matches("The company develops operational workflows.", "ru")
    assert not language_matches("Компания развивает операционные процессы.", "en")


def test_worldwide_search_does_not_require_a_country_gate() -> None:
    company = SimpleNamespace(
        identity_verification_status="verified",
        geography_verification_status="not_required",
        relevance_status="relevant",
    )
    payload = {
        "one_line": "Компания развивает продукты.",
        "overview": "Проверенный профиль компании.",
        "matches": ["Совпадение с профилем"],
        "research_status": "complete",
        "locale_validated": True,
        "vacancy_reviewed": True,
        "risk_reviewed": True,
    }

    assert quality_checks(company, payload, contact_ready=True)["geography"] is True
    assert quality_checks(company, payload, contact_ready=False)["contact"] is True
    assert ready_for_inbox(company, payload, contact_ready=False) is True


def test_geography_remains_a_gate_when_verification_was_required() -> None:
    company = SimpleNamespace(
        identity_verification_status="verified",
        geography_verification_status="unconfirmed",
        relevance_status="relevant",
    )
    assert quality_checks(company, {}, contact_ready=False)["geography"] is False
