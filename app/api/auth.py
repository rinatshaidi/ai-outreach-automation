"""Local single-owner login, session inspection and logout."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from secrets import token_bytes, token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.api.crm import DbSession
from app.config import get_settings
from app.modules.auth.models import AuthSession, LoginAttempt, User
from app.modules.auth.service import normalize_login, opaque_hash, password_matches

router = APIRouter(tags=["authentication"])
templates = Jinja2Templates(directory="app/templates")
LOGIN_CSRF_COOKIE = "outreach_login_csrf_v2"
LEGACY_LOGIN_CSRF_COOKIE = "outreach_login_csrf"
LOGIN_CSRF_TTL_SECONDS = 600
_LOGIN_CSRF_SECRET = token_bytes(32)


def fingerprint(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    agent = request.headers.get("user-agent", "unknown")[:300]
    return opaque_hash(f"{host}|{agent}")


def safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def set_session_cookies(response: RedirectResponse, session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    max_age = settings.auth_session_minutes * 60
    response.set_cookie(
        settings.auth_session_cookie_name,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.auth_csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def create_login_csrf_token(*, now: datetime | None = None) -> str:
    timestamp = int((now or datetime.now(UTC)).timestamp())
    payload = f"{timestamp}.{token_urlsafe(24)}"
    signature = hmac_new(_LOGIN_CSRF_SECRET, payload.encode(), sha256).hexdigest()
    return f"{payload}.{signature}"


def login_csrf_is_valid(token: str, *, now: datetime | None = None) -> bool:
    try:
        timestamp_text, nonce, supplied = token.split(".", 2)
        timestamp = int(timestamp_text)
    except (TypeError, ValueError):
        return False
    current = int((now or datetime.now(UTC)).timestamp())
    if not nonce or timestamp > current + 60 or current - timestamp > LOGIN_CSRF_TTL_SECONDS:
        return False
    payload = f"{timestamp}.{nonce}"
    expected = hmac_new(_LOGIN_CSRF_SECRET, payload.encode(), sha256).hexdigest()
    return compare_digest(expected, supplied)


def clear_login_csrf_cookies(response: Response) -> None:
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
    response.delete_cookie(LEGACY_LOGIN_CSRF_COOKIE, path="/auth/login")


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, session: DbSession, next: str | None = None) -> HTMLResponse:
    configured = bool(await session.scalar(select(func.count(User.id))))
    login_csrf = create_login_csrf_token()
    response = templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "configured": configured,
            "error": None,
            "next_path": safe_next(next),
            "login_csrf": login_csrf,
        },
    )
    clear_login_csrf_cookies(response)
    return response


@router.post("/auth/login", response_class=HTMLResponse, include_in_schema=False)
async def login(
    request: Request,
    session: DbSession,
    login_identifier: Annotated[str, Form(min_length=1, max_length=200)],
    password: Annotated[str, Form(min_length=1, max_length=1024)],
    csrf_token: Annotated[str, Form(min_length=20, max_length=200)],
    next_path: Annotated[str, Form()] = "/",
) -> Response:
    settings = get_settings()
    normalized = normalize_login(login_identifier)
    login_hash = opaque_hash(normalized)
    client_hash = fingerprint(request)
    request_id = getattr(request.state, "request_id", "login")
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=settings.auth_login_window_minutes)
    recent_failures = int(
        await session.scalar(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.login_hash == login_hash,
                LoginAttempt.reason_code.in_(["invalid_credentials", "login_rate_limited"]),
                LoginAttempt.occurred_at >= cutoff,
            )
        )
        or 0
    )
    csrf_valid = login_csrf_is_valid(csrf_token, now=now)
    owner = await session.scalar(select(User).where(User.login_identifier == normalized))
    success = bool(
        csrf_valid
        and recent_failures < settings.auth_login_max_attempts
        and owner is not None
        and owner.status == "active"
        and password_matches(owner.password_hash, password)
    )
    if not csrf_valid:
        reason = "login_csrf_invalid"
    elif recent_failures >= settings.auth_login_max_attempts:
        reason = "login_rate_limited"
    elif not success:
        reason = "invalid_credentials"
    else:
        reason = "authenticated"
    session.add(
        LoginAttempt(
            login_hash=login_hash,
            result="success"
            if success
            else ("rate_limited" if "rate_limited" in reason else "failed"),
            reason_code=reason,
            client_fingerprint=client_hash,
            request_id=request_id,
        )
    )
    if not success or owner is None:
        await session.commit()
        replacement_csrf = create_login_csrf_token()
        response = templates.TemplateResponse(
            request=request,
            name="login.html",
            status_code=429 if "rate_limited" in reason else 401,
            context={
                "configured": owner is not None,
                "error": "Слишком много попыток. Повторите позже."
                if "rate_limited" in reason
                else "Неверный логин или пароль.",
                "next_path": safe_next(next_path),
                "login_csrf": replacement_csrf,
            },
        )
        clear_login_csrf_cookies(response)
        return response

    session_token = token_urlsafe(48)
    session_csrf = token_urlsafe(32)
    owner.last_login_at = now
    session.add(
        AuthSession(
            user_id=owner.id,
            token_hash=opaque_hash(session_token),
            csrf_token_hash=opaque_hash(session_csrf),
            expires_at=now + timedelta(minutes=settings.auth_session_minutes),
            client_fingerprint=client_hash,
        )
    )
    await session.commit()
    redirect_response = RedirectResponse(url=safe_next(next_path), status_code=303)
    clear_login_csrf_cookies(redirect_response)
    set_session_cookies(redirect_response, session_token, session_csrf)
    return redirect_response


@router.get("/api/v1/auth/session")
async def current_session(request: Request) -> dict[str, str]:
    owner: User | None = request.state.owner
    if owner is None:
        return {"status": "disabled"}
    return {"status": "authenticated", "owner_id": str(owner.id)}


@router.post("/auth/logout", include_in_schema=False)
async def logout(request: Request, session: DbSession) -> RedirectResponse:
    auth_session: AuthSession | None = request.state.auth_session
    if auth_session is not None:
        stored = await session.get(AuthSession, auth_session.id)
        if stored is not None:
            stored.revoked_at = datetime.now(UTC)
            await session.commit()
    settings = get_settings()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(settings.auth_session_cookie_name)
    response.delete_cookie(settings.auth_csrf_cookie_name)
    return response


@router.post("/preferences/locale", include_in_schema=False)
async def update_dashboard_locale(
    request: Request,
    session: DbSession,
    locale: Annotated[str, Form()],
    next_path: Annotated[str, Form()] = "/",
) -> RedirectResponse:
    if locale not in {"ru", "en"}:
        return RedirectResponse(url=safe_next(next_path), status_code=303)
    owner: User | None = request.state.owner
    if owner is not None:
        stored = await session.get(User, owner.id)
        if stored is not None:
            stored.dashboard_locale = locale
            await session.commit()
    response = RedirectResponse(url=safe_next(next_path), status_code=303)
    if owner is None and not get_settings().auth_required:
        response.set_cookie(
            "outreach_dashboard_locale",
            locale,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="strict",
        )
    return response


@router.post("/preferences/outreach-language", include_in_schema=False)
async def update_outreach_language(
    request: Request,
    session: DbSession,
    language: Annotated[str, Form()],
    next_path: Annotated[str, Form()] = "/",
) -> RedirectResponse:
    if language not in {"auto", "en", "ru"}:
        return RedirectResponse(url=safe_next(next_path), status_code=303)
    owner: User | None = request.state.owner
    if owner is not None:
        stored = await session.get(User, owner.id)
        if stored is not None:
            stored.outreach_language = language
            await session.commit()
    return RedirectResponse(url=safe_next(next_path), status_code=303)
