"""Owner-facing opportunity presentation regressions."""

from datetime import UTC, datetime

from app.modules.opportunities.display import format_local_datetime, localized_risk


def test_utc_timestamp_is_rendered_in_moscow_time() -> None:
    value = datetime(2026, 8, 14, 12, 30, tzinfo=UTC)

    assert format_local_datetime(value) == "14.08.2026 · 15:30"


def test_naive_database_timestamp_is_treated_as_utc() -> None:
    value = datetime(2026, 8, 14, 12, 30)

    assert format_local_datetime(value) == "14.08.2026 · 15:30"


def test_known_system_risk_is_localized_for_russian_dashboard() -> None:
    value = "No explicit public need or timing signal was detected"

    assert localized_risk(value, "ru") == (
        "Явная публичная потребность или сигнал подходящего момента не обнаружены."
    )


def test_source_text_is_not_rewritten_when_no_known_translation_exists() -> None:
    value = "Named evidence from an external source"

    assert localized_risk(value, "ru") == value
