import pytest
from pydantic import SecretStr

from app.config import Settings


def test_external_actions_are_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.demo_mode is True
    assert settings.allow_real_email is False
    assert settings.allow_publication is False
    assert settings.allow_external_export is False
    assert "database_url" not in settings.safe_summary()
    assert settings.safe_summary()["openai_api_key_configured"] is False


def test_demo_mode_rejects_real_email() -> None:
    settings = Settings(_env_file=None, demo_mode=True, allow_real_email=True)

    with pytest.raises(ValueError, match="Real email cannot be enabled"):
        settings.assert_safe_runtime()


def test_production_rejects_demo_mode() -> None:
    settings = Settings(_env_file=None, app_environment="production", demo_mode=True)

    with pytest.raises(ValueError, match="DEMO_MODE must be false"):
        settings.assert_safe_runtime()


def test_production_requires_authentication() -> None:
    settings = Settings(
        _env_file=None,
        app_environment="production",
        demo_mode=False,
        auth_required=False,
        auth_cookie_secure=True,
    )

    with pytest.raises(ValueError, match="AUTH_REQUIRED must be true"):
        settings.assert_safe_runtime()


def test_production_requires_secure_session_cookies() -> None:
    settings = Settings(
        _env_file=None,
        app_environment="production",
        demo_mode=False,
        auth_required=True,
        auth_cookie_secure=False,
    )

    with pytest.raises(ValueError, match="AUTH_COOKIE_SECURE must be true"):
        settings.assert_safe_runtime()


def test_real_email_requires_owner_token() -> None:
    settings = Settings(_env_file=None, demo_mode=False, allow_real_email=True)

    with pytest.raises(ValueError, match="DELIVERY_OWNER_TOKEN is required"):
        settings.assert_safe_runtime()


def test_real_email_can_be_enabled_with_owner_token() -> None:
    settings = Settings(
        _env_file=None,
        demo_mode=False,
        allow_real_email=True,
        delivery_owner_token=SecretStr("synthetic-owner-token"),
    )

    settings.assert_safe_runtime()


def test_runtime_rejects_unknown_user_timezone() -> None:
    settings = Settings(_env_file=None, user_timezone="Invalid/Timezone")

    with pytest.raises(ValueError, match="valid IANA timezone"):
        settings.assert_safe_runtime()


def test_openai_provider_requires_key_and_explicit_owner_data_gate() -> None:
    missing_key = Settings(
        _env_file=None,
        ai_rewrite_provider="openai",
        allow_owner_data_to_ai=True,
    )
    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        missing_key.assert_safe_runtime()

    missing_consent = Settings(
        _env_file=None,
        ai_rewrite_provider="openai",
        openai_api_key=SecretStr("sk-synthetic-test-key-1234567890"),
        allow_owner_data_to_ai=False,
    )
    with pytest.raises(ValueError, match="ALLOW_OWNER_DATA_TO_AI"):
        missing_consent.assert_safe_runtime()


def test_safe_summary_reports_key_presence_without_value() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("synthetic-secret-never-print"),
    )

    summary = settings.safe_summary()

    assert summary["openai_api_key_configured"] is True
    assert "synthetic-secret-never-print" not in str(summary)


def test_openai_provider_rejects_repeated_or_control_character_key() -> None:
    repeated = Settings(
        _env_file=None,
        ai_rewrite_provider="openai",
        openai_api_key=SecretStr("sk-synthetic-test-key-123sk-repeated-456"),
        allow_owner_data_to_ai=True,
    )
    with pytest.raises(ValueError, match="invalid, repeated, or control"):
        repeated.assert_safe_runtime()

    control = Settings(
        _env_file=None,
        ai_rewrite_provider="openai",
        openai_api_key=SecretStr("sk-synthetic-test-key-1234567890\r"),
        allow_owner_data_to_ai=True,
    )
    with pytest.raises(ValueError, match="invalid, repeated, or control"):
        control.assert_safe_runtime()


def test_openai_provider_accepts_modern_project_key_without_fixed_length() -> None:
    settings = Settings(
        _env_file=None,
        ai_rewrite_provider="openai",
        openai_api_key=SecretStr("sk-proj-" + "A_b-9" * 100),
        allow_owner_data_to_ai=True,
    )

    settings.assert_safe_runtime()


def test_gmail_stays_fail_closed_until_every_secret_is_configured() -> None:
    missing_secrets = Settings(_env_file=None, gmail_oauth_enabled=True)
    with pytest.raises(ValueError, match="Gmail OAuth requires"):
        missing_secrets.assert_safe_runtime()

    sync_without_oauth = Settings(_env_file=None, gmail_sync_enabled=True)
    with pytest.raises(ValueError, match="GMAIL_SYNC_ENABLED"):
        sync_without_oauth.assert_safe_runtime()

    provider_without_oauth = Settings(_env_file=None, email_delivery_provider="gmail")
    with pytest.raises(ValueError, match="Gmail delivery provider"):
        provider_without_oauth.assert_safe_runtime()
