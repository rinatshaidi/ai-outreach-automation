from datetime import UTC, datetime
from types import SimpleNamespace

from app.modules.search_tasks.daily import daily_query, local_today


def test_daily_query_uses_confirmed_tracks_without_country_restriction() -> None:
    profile = SimpleNamespace(
        desired_roles=["Project Manager", "Business Development"],
        preferred_industries=["AI", "Infrastructure"],
        preferred_countries=["Serbia", "UAE"],
    )

    query = daily_query(profile)  # type: ignore[arg-type]

    assert "project delivery" in query
    assert "business development" in query
    assert "workflow automation" in query
    assert "worldwide" in query
    assert "Country is not a selection criterion" in query
    assert "Serbia" not in query
    assert "Project Manager" not in query
    assert "Business Development" not in query
    assert "Rinat" not in query
    assert "email" not in query.lower()


def test_daily_schedule_uses_moscow_calendar_day() -> None:
    now = datetime(2026, 8, 24, 21, 30, tzinfo=UTC)

    assert local_today(now, "Europe/Moscow").isoformat() == "2026-08-25"
