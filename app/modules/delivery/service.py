"""Pure delivery safety helpers."""

from hashlib import sha256
from hmac import compare_digest

from app.config import Settings

VERIFIED_CONTACT_STATUSES = {"verified", "verified_public", "provider_verified"}
SAFE_TEST_SMTP_HOSTS = {"mailpit", "localhost", "127.0.0.1", "::1"}
PLACEHOLDER_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "localhost",
}


def mask_email(email: str) -> str:
    local, domain = email.rsplit("@", 1)
    visible = local[:2] if len(local) > 1 else local[:1]
    suffix = domain.rsplit(".", 1)[-1] if "." in domain else "***"
    return f"{visible}***@***.{suffix}"


def recipient_hash(email: str) -> str:
    return sha256(email.strip().casefold().encode()).hexdigest()


def is_placeholder_email(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].casefold()
    return domain in PLACEHOLDER_DOMAINS or domain.endswith(
        (".example", ".test", ".invalid", ".localhost")
    )


def real_delivery_authenticated(authorization: str | None, settings: Settings) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    expected = settings.delivery_owner_token
    if expected is None:
        return False
    supplied = authorization.removeprefix("Bearer ").strip()
    return compare_digest(supplied, expected.get_secret_value())
