"""Global single-owner session and CSRF enforcement."""

from datetime import UTC, datetime
from hmac import compare_digest
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings
from app.infrastructure.db.session import SessionFactory
from app.modules.auth.models import AuthSession, User
from app.modules.auth.service import opaque_hash

PUBLIC_PATHS = {
    "/login",
    "/auth/login",
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_LOCALE_COOKIE = "outreach_dashboard_locale"


def public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/static/")


def unauthorized(request: Request) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=401,
            content={"detail": {"code": "authentication_required", "message": "Login required"}},
        )
    target = request.url.path if request.method == "GET" else "/"
    return RedirectResponse(url=f"/login?next={target}", status_code=303)


class OwnerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        request.state.owner = None
        request.state.auth_session = None
        request.state.csrf_token = None
        request.state.dashboard_locale = "ru"
        request.state.outreach_language = "auto"
        if not settings.auth_required:
            local_locale = request.cookies.get(LOCAL_LOCALE_COOKIE)
            if local_locale in {"ru", "en"}:
                request.state.dashboard_locale = local_locale
            return await call_next(request)
        if public_path(request.url.path):
            return await call_next(request)

        raw_session = request.cookies.get(settings.auth_session_cookie_name)
        raw_csrf = request.cookies.get(settings.auth_csrf_cookie_name)
        if not raw_session:
            return unauthorized(request)

        async with SessionFactory() as session:
            auth_session = await session.scalar(
                select(AuthSession).where(AuthSession.token_hash == opaque_hash(raw_session))
            )
            now = datetime.now(UTC)
            if (
                auth_session is None
                or auth_session.revoked_at is not None
                or auth_session.expires_at <= now
            ):
                response = unauthorized(request)
                response.delete_cookie(settings.auth_session_cookie_name)
                response.delete_cookie(settings.auth_csrf_cookie_name)
                return response
            owner = await session.get(User, auth_session.user_id)
            if owner is None or owner.status != "active":
                return unauthorized(request)
            request.state.owner = owner
            request.state.auth_session = auth_session
            request.state.csrf_token = raw_csrf
            request.state.dashboard_locale = owner.dashboard_locale
            request.state.outreach_language = owner.outreach_language

            if request.method not in SAFE_METHODS:
                supplied = request.headers.get("X-CSRF-Token")
                if supplied is None and request.headers.get("content-type", "").startswith(
                    "application/x-www-form-urlencoded"
                ):
                    body = await request.body()
                    values = parse_qs(body.decode("utf-8", errors="strict"), keep_blank_values=True)
                    supplied_values = values.get("csrf_token", [])
                    supplied = supplied_values[0] if supplied_values else None
                valid = bool(
                    supplied
                    and raw_csrf
                    and compare_digest(supplied, raw_csrf)
                    and compare_digest(opaque_hash(supplied), auth_session.csrf_token_hash)
                )
                if not valid:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {
                                "code": "csrf_validation_failed",
                                "message": "Valid CSRF token required",
                            }
                        },
                    )

        return await call_next(request)
