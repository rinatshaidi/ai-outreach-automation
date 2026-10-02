from app.modules.opportunities.presentation import (
    PILOT_PRESENTATIONS_RU,
    localized_blockers,
    localized_dynamic_text,
    localized_status,
    localized_values,
    pilot_presentation,
)


def test_all_first_wave_companies_have_complete_russian_presentation() -> None:
    expected = {"Airalo", "Bolt", "n8n", "what3words", "Einride", "Banco Plata"}

    assert set(PILOT_PRESENTATIONS_RU) == expected
    for company in expected:
        presentation = pilot_presentation(company, "ru")
        assert presentation["country"]
        assert presentation["industry"]
        assert presentation["conclusion"]
        assert presentation["why"]
        assert presentation["scenario"]
        assert presentation["upside"]
        assert presentation["risk"]
        assert len(presentation["scenarios"]) == 3


def test_presentation_does_not_replace_source_data_in_english_mode() -> None:
    assert pilot_presentation("Airalo", "en") == {}
    assert pilot_presentation("Unknown company", "ru") == {}


def test_airalo_owner_presentation_is_localized_and_not_rejected() -> None:
    presentation = pilot_presentation("Airalo", "ru")

    assert presentation["country"] == "Сингапур"
    assert presentation["conclusion"] == "Стоит рассмотреть"
    assert "eSIM" in presentation["description"]
    assert "пока не подтверждена" in presentation["current_activity"]


def test_internal_format_values_are_localized_for_owner_ui() -> None:
    assert localized_values(["full_time", "remote", "relocation"], "ru") == [
        "Полная занятость",
        "Удалённо",
        "Переезд",
    ]
    assert localized_values(["full_time", "remote"], "en") == ["Full-time", "Remote"]


def test_raw_statuses_and_blockers_have_owner_facing_labels() -> None:
    assert localized_status("decision_pending", "ru") == "Ожидает решения"
    assert localized_status("decision_pending", "en") == "Awaiting decision"
    assert localized_status("VERIFIED_CONTACT", "ru") == "Контакт проверен"
    assert localized_blockers(["public_contact_path"], "ru") == [
        "нет проверенного публичного контакта"
    ]
    assert localized_blockers(["public_contact_path"], "en") == [
        "verified public contact is missing"
    ]


def test_dynamic_analysis_never_hides_evidence_behind_technical_placeholder() -> None:
    ru = localized_dynamic_text("Unmapped English research conclusion", "ru")
    en = localized_dynamic_text("Непереведённый русский вывод", "en")
    assert ru == "Unmapped English research conclusion"
    assert en == "Непереведённый русский вывод"
    assert "Локализованный вывод пока не сформирован" not in ru
    assert localized_dynamic_text("Mexico", "ru") == "Мексика"
    assert localized_dynamic_text("Мексика", "en") == "Mexico"
    assert localized_dynamic_text("Russia", "ru") == "Россия"
    assert (
        localized_dynamic_text("Computer vision / Artificial intelligence", "ru")
        == "Компьютерное зрение / искусственный интеллект"
    )
