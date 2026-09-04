from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.api.routes import router
from app.application.ports import ReadinessChecker
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.infrastructure.postgres.database import PostgreSQLAdapter


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    database = PostgreSQLAdapter(resolved_settings)
    readiness_checker = ReadinessChecker(database)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await database.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )
    application.add_middleware(
        RateLimitMiddleware,
        requests=resolved_settings.rate_limit_requests,
        window_seconds=resolved_settings.rate_limit_window_seconds,
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.include_router(router)
    application.state.readiness_checker = readiness_checker
    return application
