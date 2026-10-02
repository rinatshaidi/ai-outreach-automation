"""Gmail integration keeps OAuth, tokens, and reply parsing fail-closed."""

import base64
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.config import Settings
from app.modules.mailbox.gmail import (
    GMAIL_SCOPES,
    authorization_url,
    decrypt_refresh_token,
    encrypt_refresh_token,
    parse_gmail_reply,
)


def gmail_settings() -> Settings:
    return Settings(
        _env_file=None,
        gmail_oauth_enabled=True,
        gmail_oauth_client_id="synthetic-client.apps.googleusercontent.com",
        gmail_oauth_client_secret=SecretStr("synthetic-client-secret"),
        gmail_token_encryption_key=SecretStr(Fernet.generate_key().decode()),
    )


def test_oauth_url_has_exact_callback_state_and_minimum_scopes() -> None:
    settings = gmail_settings()
    url = authorization_url(settings, "synthetic-state")
    query = parse_qs(urlparse(url).query)

    assert query["redirect_uri"] == [
        "https://outreach.shaidigroup.com/auth/gmail/callback"
    ]
    assert query["state"] == ["synthetic-state"]
    assert set(query["scope"][0].split()) == set(GMAIL_SCOPES)
    assert query["access_type"] == ["offline"]
    assert "synthetic-client-secret" not in url


def test_refresh_token_is_encrypted_at_rest() -> None:
    settings = gmail_settings()
    token = "synthetic-refresh-token"  # noqa: S105 - non-secret test fixture

    encrypted = encrypt_refresh_token(settings, token)

    assert token not in encrypted
    assert decrypt_refresh_token(settings, encrypted) == token


def test_parse_gmail_reply_extracts_plain_text_without_html() -> None:
    body = base64.urlsafe_b64encode(b"Thanks, let's talk.").decode().rstrip("=")
    message: dict[str, object] = {
        "internalDate": "1760000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Person <person@company.com>"},
                {"name": "Subject", "value": "Re: Project"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": body}},
                {"mimeType": "text/html", "body": {"data": "ignored"}},
            ],
        },
    }

    sender, subject, text, received_at = parse_gmail_reply(message)

    assert sender == "person@company.com"
    assert subject == "Re: Project"
    assert text == "Thanks, let's talk."
    assert received_at.tzinfo is not None
