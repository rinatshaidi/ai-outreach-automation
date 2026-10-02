"""FastAPI application factory and ASGI entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.analytics import router as analytics_router
from app.api.analytics_web import router as analytics_web_router
from app.api.auth import router as auth_router
from app.api.candidate_profile import router as candidate_profile_router
from app.api.candidate_profile_web import router as candidate_profile_web_router
from app.api.crm import router as crm_router
from app.api.crm_web import router as crm_web_router
from app.api.delivery import router as delivery_router
from app.api.followups import router as followups_router
from app.api.followups_web import router as followups_web_router
from app.api.generation import router as generation_router
from app.api.health import router as health_router
from app.api.mailbox import router as mailbox_router
from app.api.opportunities import router as opportunities_router
from app.api.profile_review import router as profile_review_router
from app.api.relevance import router as relevance_router
from app.api.research import router as research_router
from app.api.review import router as review_router
from app.api.review_web import router as review_web_router
from app.api.safety import router as safety_router
from app.api.search_tasks import api_router as search_tasks_router
from app.api.search_tasks import web_router as search_tasks_web_router
from app.api.sender_voice import router as sender_voice_router
from app.api.web import router as web_router
from app.config import get_settings
from app.infrastructure.auth_middleware import OwnerAuthMiddleware
from app.infrastructure.db.session import close_database
from app.infrastructure.logging import configure_logging
from app.infrastructure.middleware import RequestContextMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    yield
    await close_database()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Privacy-first AI outreach mini-CRM",
        lifespan=lifespan,
    )
    application.state.auth_required = settings.auth_required
    application.add_middleware(OwnerAuthMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.mount("/static", StaticFiles(directory="app/static"), name="static")
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(analytics_router)
    application.include_router(analytics_web_router)
    application.include_router(candidate_profile_router)
    application.include_router(candidate_profile_web_router)
    application.include_router(crm_router)
    application.include_router(delivery_router)
    application.include_router(followups_router)
    application.include_router(followups_web_router)
    application.include_router(opportunities_router)
    application.include_router(profile_review_router)
    application.include_router(research_router)
    application.include_router(relevance_router)
    application.include_router(generation_router)
    application.include_router(mailbox_router)
    application.include_router(review_router)
    application.include_router(review_web_router)
    application.include_router(search_tasks_router)
    application.include_router(search_tasks_web_router)
    application.include_router(safety_router)
    application.include_router(sender_voice_router)
    application.include_router(crm_web_router)
    application.include_router(web_router)
    return application


app = create_app()
