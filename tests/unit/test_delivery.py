"""Delivery helpers fail closed without exposing recipient addresses."""

from pydantic import SecretStr

from app.config import Settings
from app.modules.delivery.service import (
    is_placeholder_email,
    mask_email,
    real_delivery_authenticated,
    recipient_hash,
)


def test_recipient_is_masked_and_hash_is_normalized() -> None:
    assert mask_email("person@company.co.uk") == "pe***@***.uk"
    assert recipient_hash(" Person@Company.COM ") == recipient_hash("person@company.com")
    assert "company.com" not in recipient_hash("person@company.com")


def test_placeholder_domains_are_blocked_for_real_delivery() -> None:
    assert is_placeholder_email("person@example.com") is True
    assert is_placeholder_email("person@synthetic.test") is True
    assert is_placeholder_email("person@integration-fixture.example") is True
    assert is_placeholder_email("person@company.invalid") is True
    assert is_placeholder_email("person@company.com") is False


def test_owner_authentication_uses_bearer_secret() -> None:
    settings = Settings(
        _env_file=None,
        delivery_owner_token=SecretStr("synthetic-owner-token"),
    )

    assert real_delivery_authenticated("Bearer synthetic-owner-token", settings) is True
    assert real_delivery_authenticated("Bearer wrong", settings) is False
    assert real_delivery_authenticated("Basic synthetic-owner-token", settings) is False
    assert real_delivery_authenticated(None, settings) is False
