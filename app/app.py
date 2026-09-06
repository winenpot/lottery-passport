from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.api.routes import router
from app.application.authentication import AuthenticationService, AuthenticationSettings
from app.application.passports import PassportService
from app.application.ports import ReadinessChecker
from app.application.redemption_codes import RedemptionService
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.infrastructure.authentication import (
    SecureAuthenticationCodeGenerator,
    SystemClock,
)
from app.infrastructure.email import DevelopmentEmailSender, UnavailableEmailSender
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.repositories import (
    PostgreSQLChallengeRepository,
    PostgreSQLPassportRepository,
    PostgreSQLRedemptionCodeRepository,
    PostgreSQLSessionRepository,
    PostgreSQLUserRepository,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    database = PostgreSQLAdapter(resolved_settings)
    readiness_checker = ReadinessChecker(database)
    email_sender = (
        DevelopmentEmailSender()
        if resolved_settings.email_provider == "development"
        else UnavailableEmailSender()
    )
    authentication_service = AuthenticationService(
        users=PostgreSQLUserRepository(database.session_factory),
        challenges=PostgreSQLChallengeRepository(database.session_factory),
        sessions=PostgreSQLSessionRepository(database.session_factory),
        code_generator=SecureAuthenticationCodeGenerator(),
        clock=SystemClock(),
        email_sender=email_sender,
        settings=AuthenticationSettings(
            challenge_ttl=timedelta(
                seconds=resolved_settings.auth_challenge_ttl_seconds
            ),
            session_ttl=timedelta(seconds=resolved_settings.auth_session_ttl_seconds),
            max_verification_attempts=resolved_settings.auth_max_verification_attempts,
        ),
    )
    passport_repository = PostgreSQLPassportRepository(database.session_factory)
    passport_service = PassportService(passports=passport_repository)
    redemption_service = RedemptionService(
        codes=PostgreSQLRedemptionCodeRepository(database.session_factory),
        passports=passport_repository,
        clock=SystemClock(),
        pepper=(
            resolved_settings.redemption_code_pepper.get_secret_value()
            if resolved_settings.redemption_code_pepper is not None
            else None
        ),
    )

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
        allow_origins=resolved_settings.allowed_cors_origins,
        allow_credentials=resolved_settings.allowed_cors_origins != ["*"],
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
    application.state.authentication_service = authentication_service
    application.state.passport_service = passport_service
    application.state.redemption_service = redemption_service
    application.state.email_sender = email_sender
    application.state.settings = resolved_settings
    return application
