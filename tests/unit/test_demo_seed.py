import pytest

from app.config import get_settings
from scripts import seed_demo


def test_synthetic_seed_is_safe(capsys: object, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_seed_database() -> int:
        return 5

    get_settings.cache_clear()
    monkeypatch.setattr(seed_demo, "seed_database", fake_seed_database)
    seed_demo.main()
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert "synthetic_seed_completed" in output
    assert '"records": 5' in output
