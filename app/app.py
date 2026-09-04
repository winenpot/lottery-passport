from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.application.ports import ReadinessChecker
from app.core.config import Settings, get_settings
from app.infrastructure.postgres.database import PostgreSQLAdapter


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
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
    application.include_router(router)
    application.state.readiness_checker = readiness_checker
    return application
