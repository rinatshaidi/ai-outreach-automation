"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings with privacy-safe defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AI Outreach System"
    app_environment: Literal["development", "test", "demo", "production"] = "development"
    app_host: str = "0.0.0.0"  # noqa: S104 - required inside a container
    app_port: int = 8000
    log_level: str = "INFO"

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://outreach:outreach_dev_only@localhost:5432/outreach"
    )

    demo_mode: bool = True
    allow_real_email: bool = False
    allow_publication: bool = False
    allow_external_export: bool = False

    auth_required: bool = True
    auth_session_minutes: int = 480
    auth_login_window_minutes: int = 15
    auth_login_max_attempts: int = 5
    auth_cookie_secure: bool = False
    auth_session_cookie_name: str = "outreach_session"
    auth_csrf_cookie_name: str = "outreach_csrf"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_use_tls: bool = False
    smtp_username: SecretStr | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str = "outreach@example.test"
    smtp_from_name: str = "AI Outreach System"
    smtp_test_recipient: str = "mailpit@example.test"
    smtp_test_mode: bool = True
    delivery_owner_token: SecretStr | None = None
    user_timezone: str = "Europe/Moscow"
    ai_rewrite_provider: Literal["unavailable", "openai"] = "unavailable"
    openai_api_key: SecretStr | None = None
    openai_company_discovery_enabled: bool = False
    openai_rewrite_model: str = "gpt-5-mini"
    allow_owner_data_to_ai: bool = False
    email_delivery_provider: Literal["smtp", "gmail"] = "smtp"
    gmail_oauth_enabled: bool = False
    gmail_oauth_client_id: str | None = None
    gmail_oauth_client_secret: SecretStr | None = None
    gmail_oauth_redirect_uri: str = (
        "https://outreach.shaidigroup.com/auth/gmail/callback"
    )
    gmail_token_encryption_key: SecretStr | None = None
    gmail_sync_enabled: bool = False
    gmail_sync_interval_seconds: int = 60
    gmail_sync_batch_size: int = 25
    background_worker_poll_seconds: int = 5
    background_worker_max_attempts: int = 3
    daily_discovery_enabled: bool = False
    daily_discovery_hour: int = 9
    daily_discovery_result_limit: int = 5

    def assert_safe_runtime(self) -> None:
        """Fail closed when production is configured with unsafe demo assumptions."""

        if self.app_environment == "production" and self.demo_mode:
            raise ValueError("DEMO_MODE must be false in production")
        if self.demo_mode and self.allow_real_email:
            raise ValueError("Real email cannot be enabled while DEMO_MODE is true")
        if self.allow_real_email and self.delivery_owner_token is None:
            raise ValueError("DELIVERY_OWNER_TOKEN is required when real email is enabled")
        if self.ai_rewrite_provider == "openai" and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when AI_REWRITE_PROVIDER=openai")
        if self.ai_rewrite_provider == "openai" and self.openai_api_key is not None:
            secret = self.openai_api_key.get_secret_value()
            prefixes = ("sk-proj-", "sk-svcacct-", "sk-")
            prefix = next((item for item in prefixes if secret.startswith(item)), None)
            remainder = secret[len(prefix) :] if prefix else secret
            repeated = "sk-proj-" in remainder or "sk-svcacct-" in remainder
            if prefix == "sk-" and "sk-" in remainder:
                repeated = True
            if (
                not secret
                or prefix is None
                or any(character.isspace() or ord(character) < 32 for character in secret)
                or repeated
            ):
                raise ValueError(
                    "OPENAI_API_KEY contains invalid, repeated, or control characters"
                )
        if self.ai_rewrite_provider == "openai" and not self.allow_owner_data_to_ai:
            raise ValueError(
                "ALLOW_OWNER_DATA_TO_AI must be explicitly enabled when AI_REWRITE_PROVIDER=openai"
            )
        if self.gmail_oauth_enabled and not (
            self.gmail_oauth_client_id
            and self.gmail_oauth_client_secret
            and self.gmail_token_encryption_key
        ):
            raise ValueError(
                "Gmail OAuth requires client id, client secret, and token encryption key"
            )
        if self.gmail_sync_enabled and not self.gmail_oauth_enabled:
            raise ValueError("GMAIL_SYNC_ENABLED requires GMAIL_OAUTH_ENABLED")
        if self.email_delivery_provider == "gmail" and not self.gmail_oauth_enabled:
            raise ValueError("Gmail delivery provider requires GMAIL_OAUTH_ENABLED")
        if self.gmail_sync_interval_seconds < 30:
            raise ValueError("GMAIL_SYNC_INTERVAL_SECONDS must be at least 30")
        if not 1 <= self.gmail_sync_batch_size <= 100:
            raise ValueError("GMAIL_SYNC_BATCH_SIZE must be between 1 and 100")
        if self.app_environment == "production" and not self.auth_required:
            raise ValueError("AUTH_REQUIRED must be true in production")
        if self.app_environment == "production" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true in production")
        if self.auth_session_minutes < 5:
            raise ValueError("AUTH_SESSION_MINUTES must be at least 5")
        if self.background_worker_poll_seconds < 1:
            raise ValueError("BACKGROUND_WORKER_POLL_SECONDS must be at least 1")
        if self.background_worker_max_attempts < 1:
            raise ValueError("BACKGROUND_WORKER_MAX_ATTEMPTS must be at least 1")
        if not 0 <= self.daily_discovery_hour <= 23:
            raise ValueError("DAILY_DISCOVERY_HOUR must be between 0 and 23")
        if not 1 <= self.daily_discovery_result_limit <= 10:
            raise ValueError("DAILY_DISCOVERY_RESULT_LIMIT must be between 1 and 10")
        try:
            ZoneInfo(self.user_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("USER_TIMEZONE must be a valid IANA timezone") from exc

    def safe_summary(self) -> dict[str, str | bool | int]:
        """Return non-secret settings suitable for diagnostics."""

        return {
            "app_name": self.app_name,
            "environment": self.app_environment,
            "app_port": self.app_port,
            "demo_mode": self.demo_mode,
            "allow_real_email": self.allow_real_email,
            "allow_publication": self.allow_publication,
            "allow_external_export": self.allow_external_export,
            "auth_required": self.auth_required,
            "auth_cookie_secure": self.auth_cookie_secure,
            "ai_rewrite_provider": self.ai_rewrite_provider,
            "openai_company_discovery_enabled": self.openai_company_discovery_enabled,
            "openai_api_key_configured": bool(
                self.openai_api_key and self.openai_api_key.get_secret_value().strip()
            ),
            "allow_owner_data_to_ai": self.allow_owner_data_to_ai,
            "email_delivery_provider": self.email_delivery_provider,
            "gmail_oauth_enabled": self.gmail_oauth_enabled,
            "gmail_oauth_configured": bool(
                self.gmail_oauth_client_id
                and self.gmail_oauth_client_secret
                and self.gmail_token_encryption_key
            ),
            "gmail_sync_enabled": self.gmail_sync_enabled,
            "daily_discovery_enabled": self.daily_discovery_enabled,
            "daily_discovery_hour": self.daily_discovery_hour,
            "daily_discovery_result_limit": self.daily_discovery_result_limit,
        }


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_safe_runtime()
    return settings
