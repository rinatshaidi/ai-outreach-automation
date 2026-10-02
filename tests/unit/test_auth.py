from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, Form, Request
from httpx import ASGITransport, AsyncClient

import app.infrastructure.auth_middleware as auth_middleware
from app.api.auth import create_login_csrf_token, login_csrf_is_valid
from app.config import get_settings
from app.infrastructure.auth_middleware import OwnerAuthMiddleware
from app.modules.auth.models import AuthSession, User
from app.modules.auth.service import hash_password, opaque_hash, password_matches


def test_argon2id_password_hash_is_one_way() -> None:
    encoded = hash_password("synthetic-password-123")
    assert encoded.startswith("$argon2id$")
    assert "synthetic-password-123" not in encoded
    assert password_matches(encoded, "synthetic-password-123") is True
    assert password_matches(encoded, "wrong-password") is False


def test_login_csrf_token_is_signed_and_expires() -> None:
    issued_at = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    token = create_login_csrf_token(now=issued_at)
    assert login_csrf_is_valid(token, now=issued_at + timedelta(minutes=5)) is True
    assert login_csrf_is_valid(f"{token}tampered", now=issued_at) is False
    assert login_csrf_is_valid(token, now=issued_at + timedelta(minutes=11)) is False


class FakeSession:
    def __init__(self, auth_session: AuthSession, owner: User) -> None:
        self.auth_session = auth_session
        self.owner = owner

    async def scalar(self, _: object) -> AuthSession:
        return self.auth_session

    async def get(self, _: object, __: object) -> User:
        return self.owner


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_owner_middleware_blocks_anonymous_and_requires_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    raw_session = "synthetic-session-token"
    raw_csrf = "synthetic-csrf-token"
    owner = User(
        id=uuid4(),
        login_identifier="owner",
        password_hash=opaque_hash(raw_session),
        status="active",
        dashboard_locale="en",
        outreach_language="ru",
    )
    auth_session = AuthSession(
        id=uuid4(),
        user_id=owner.id,
        token_hash=opaque_hash(raw_session),
        csrf_token_hash=opaque_hash(raw_csrf),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    fake_session = FakeSession(auth_session, owner)
    monkeypatch.setattr(
        auth_middleware,
        "SessionFactory",
        lambda: FakeSessionContext(fake_session),
    )
    test_app = FastAPI()
    test_app.add_middleware(OwnerAuthMiddleware)

    @test_app.get("/private")
    async def private_page(request: Request) -> dict[str, object]:
        state = request.state
        return {
            "ok": True,
            "dashboard_locale": state.dashboard_locale,
            "outreach_language": state.outreach_language,
        }

    @test_app.get("/api/private")
    async def private_api() -> dict[str, bool]:
        return {"ok": True}

    @test_app.post("/private")
    async def mutate(value: str = Form()) -> dict[str, str]:
        return {"value": value}

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous_html = await client.get("/private", follow_redirects=False)
        anonymous_api = await client.get("/api/private")
        client.cookies.set("outreach_session", raw_session)
        client.cookies.set("outreach_csrf", raw_csrf)
        authenticated = await client.get("/private")
        missing_csrf = await client.post("/private", data={"value": "safe"})
        valid_csrf = await client.post(
            "/private",
            data={"value": "safe", "csrf_token": raw_csrf},
        )

    assert anonymous_html.status_code == 303
    assert anonymous_html.headers["location"].startswith("/login")
    assert anonymous_api.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json()["dashboard_locale"] == "en"
    assert authenticated.json()["outreach_language"] == "ru"
    assert missing_csrf.status_code == 403
    assert valid_csrf.status_code == 200
    assert valid_csrf.json() == {"value": "safe"}
