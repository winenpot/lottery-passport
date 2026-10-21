import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import (
    ApiError,
    api_error_handler,
    document_validation_errors,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.api.middleware import (
    CSRF_HEADER,
    CsrfMiddleware,
    ErrorEnvelopeMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)
from app.api.routes import router
from app.application.achievements import AchievementService
from app.application.admin_users import AdminUserService
from app.application.app_config import AppConfigService, FeatureFlags
from app.application.authentication import AuthenticationService, AuthenticationSettings
from app.application.avatars import AvatarService
from app.application.challenges import ChallengeService
from app.application.coin_adjustments import CoinAdjustmentService
from app.application.failure_throttle import ThrottleSettings
from app.application.legal import LegalDocumentService
from app.application.me import MeService
from app.application.mini_games import MiniGameService
from app.application.passports import PassportService
from app.application.ports import ReadinessChecker
from app.application.profile import ProfileService
from app.application.redemption_codes import (
    PepperGuard,
    RedemptionService,
    pepper_fingerprint,
    verify_active_batch_peppers,
)
from app.application.referrals import ReferralService
from app.application.teams import TeamService
from app.application.unit_of_work import UnitOfWork
from app.application.wallets import WalletService
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.codes import verify_frozen_formats
from app.infrastructure.admin import mount_admin
from app.infrastructure.authentication import (
    SecureAuthenticationCodeGenerator,
    SystemClock,
)
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.failure_throttle import PostgreSQLFailureThrottle
from app.infrastructure.postgres.repositories import (
    PostgreSQLAchievementsReader,
    PostgreSQLAvatarCatalogue,
    PostgreSQLChallengeRepository,
    PostgreSQLChallengesReader,
    PostgreSQLLastScanReader,
    PostgreSQLLegalDocuments,
    PostgreSQLPassportRepository,
    PostgreSQLSessionRepository,
    PostgreSQLStatsReader,
    PostgreSQLTeamsReader,
    PostgreSQLUserRepository,
    PostgreSQLVenueRepository,
    PostgreSQLWalletReader,
)
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.sms import ConsoleSmsSender, KavenegarSmsSender

logger = logging.getLogger(__name__)


APP_VERSION = "0.1.0"  # keep in step with pyproject.toml [project].version

OPENAPI_TAGS = [
    {
        "name": "authentication",
        "description": (
            "Sign-in and session lifecycle. See API_CONTRACT.md#authentication."
        ),
    },
    {
        "name": "config",
        "description": "Client configuration. See API_CONTRACT.md#config-and-profile.",
    },
    {
        "name": "users",
        "description": (
            "The signed-in player's own profile. "
            "See API_CONTRACT.md#config-and-profile."
        ),
    },
    {
        "name": "redemptions",
        "description": (
            "Scanning printed codes and the coin wallet. "
            "See API_CONTRACT.md#scanning-codes."
        ),
    },
    {
        "name": "avatars",
        "description": "The avatar catalogue. See API_CONTRACT.md#config-and-profile.",
    },
    {
        "name": "legal",
        "description": (
            "The terms of use + privacy page, edited in /admin. "
            "See API_CONTRACT.md#terms-and-privacy-page."
        ),
    },
    {
        "name": "teams",
        "description": "Flavor team membership. See API_CONTRACT.md#teams.",
    },
    {
        "name": "challenges",
        "description": (
            "Automatic challenges and claims. See API_CONTRACT.md#challenges."
        ),
    },
    {
        "name": "achievements",
        "description": (
            "Auto-unlocked, auto-paid milestones (streaks today). No claim "
            "step. See API_CONTRACT.md#achievements."
        ),
    },
    {
        "name": "mini-games",
        "description": (
            "Our own in-app reaction mini-game (Tap Reflex), server-issued "
            "and server-verified -- not the physical arcade machines at "
            "the lounges. Rewards pay only through /challenges. "
            "See API_CONTRACT.md#mini-games."
        ),
    },
    {
        "name": "health",
        "description": "Liveness/readiness probes. See API_CONTRACT.md#health.",
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    database = PostgreSQLAdapter(resolved_settings)
    readiness_checker = ReadinessChecker(database)
    expected_pepper_fingerprint = (
        pepper_fingerprint(resolved_settings.redemption_code_pepper.get_secret_value())
        if resolved_settings.redemption_code_pepper is not None
        else None
    )
    pepper_guard = PepperGuard(database, expected_pepper_fingerprint)
    sms_sender = (
        KavenegarSmsSender(
            api_key=resolved_settings.kavenegar_otp_api_key.get_secret_value(),
            template_by_purpose={
                "login": resolved_settings.kavenegar_template_login,
                "signup": resolved_settings.kavenegar_template_signup,
            },
        )
        if resolved_settings.kavenegar_otp_api_key is not None
        else ConsoleSmsSender()
    )
    authentication_service = AuthenticationService(
        users=PostgreSQLUserRepository(database.session_factory),
        challenges=PostgreSQLChallengeRepository(database.session_factory),
        sessions=PostgreSQLSessionRepository(database.session_factory),
        code_generator=SecureAuthenticationCodeGenerator(),
        clock=SystemClock(),
        sms_sender=sms_sender,
        settings=AuthenticationSettings(
            challenge_ttl=timedelta(seconds=resolved_settings.otp_ttl_seconds),
            session_ttl=timedelta(seconds=resolved_settings.auth_session_ttl_seconds),
            max_verification_attempts=resolved_settings.otp_max_attempts,
            resend_cooldown=timedelta(seconds=resolved_settings.otp_resend_seconds),
            daily_limit=resolved_settings.otp_daily_limit_per_phone,
            # TODO: remove this on production (otp_test_numbers.py).
            test_numbers_enabled=resolved_settings.test_numbers_enabled,
            allowed_phones=resolved_settings.allowed_otp_phones,
        ),
    )
    admin_user_service = AdminUserService(
        users=PostgreSQLUserRepository(database.session_factory)
    )
    profile_service = ProfileService(
        store=PostgreSQLUserRepository(database.session_factory),
        clock=SystemClock(),
        current_terms_version=resolved_settings.terms_version,
        venues=PostgreSQLVenueRepository(database.session_factory),
        avatars=PostgreSQLAvatarCatalogue(database.session_factory),
    )
    avatar_service = AvatarService(
        catalogue=PostgreSQLAvatarCatalogue(database.session_factory)
    )
    legal_document_service = LegalDocumentService(
        PostgreSQLLegalDocuments(database.session_factory)
    )
    app_config_service = AppConfigService(
        clock=SystemClock(),
        zone=resolved_settings.campaign_zone,
        terms_version=resolved_settings.terms_version,
        scans_per_day=resolved_settings.redemption_daily_limit_per_user,
        venues=PostgreSQLVenueRepository(database.session_factory),
        terms_required=resolved_settings.terms_required,
        terms_url=resolved_settings.terms_url,
        privacy_url=resolved_settings.privacy_url,
        features=FeatureFlags(
            mini_games=resolved_settings.feature_mini_games,
            leaderboard=resolved_settings.feature_leaderboard,
            venue_checkin=resolved_settings.feature_venue_checkin,
            diamonds=resolved_settings.feature_diamonds,
        ),
    )
    passport_service = PassportService(
        passports=PostgreSQLPassportRepository(database.session_factory)
    )

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory)

    redemption_service = RedemptionService(
        unit_of_work=unit_of_work,
        clock=SystemClock(),
        pepper=(
            resolved_settings.redemption_code_pepper.get_secret_value()
            if resolved_settings.redemption_code_pepper is not None
            else None
        ),
        daily_limit=resolved_settings.redemption_daily_limit_per_user,
        campaign_zone=resolved_settings.campaign_zone,
        throttle=PostgreSQLFailureThrottle(database.session_factory),
        throttle_settings=ThrottleSettings(
            max_attempts=resolved_settings.redemption_max_invalid_attempts_per_hour,
            window_seconds=3600,
        ),
        first_code_bonus_coins=resolved_settings.first_code_bonus_coins,
    )
    wallet_service = WalletService(
        wallets=PostgreSQLWalletReader(database.session_factory)
    )
    coin_adjustment_service = CoinAdjustmentService(
        unit_of_work=unit_of_work,
        users=PostgreSQLUserRepository(database.session_factory),
        clock=SystemClock(),
    )
    teams_reader = PostgreSQLTeamsReader(database.session_factory)
    team_service = TeamService(
        reader=teams_reader,
        unit_of_work=unit_of_work,
        clock=SystemClock(),
        lock=timedelta(days=resolved_settings.team_lock_days),
    )
    challenges_reader = PostgreSQLChallengesReader(database.session_factory)
    me_service = MeService(
        teams=teams_reader,
        last_scans=PostgreSQLLastScanReader(database.session_factory),
        stats=PostgreSQLStatsReader(database.session_factory),
        challenges=challenges_reader,
        clock=SystemClock(),
        zone=resolved_settings.campaign_zone,
    )
    challenge_service = ChallengeService(
        reader=challenges_reader,
        teams=teams_reader,
        unit_of_work=unit_of_work,
        clock=SystemClock(),
        zone=resolved_settings.campaign_zone,
    )
    achievement_service = AchievementService(
        reader=PostgreSQLAchievementsReader(database.session_factory),
    )
    mini_game_service = MiniGameService(
        unit_of_work=unit_of_work,
        clock=SystemClock(),
        zone=resolved_settings.campaign_zone,
        rejected_review_threshold=resolved_settings.mini_game_rejected_review_threshold,
    )
    referral_service = ReferralService(
        code_store=PostgreSQLUserRepository(database.session_factory),
        unit_of_work=unit_of_work,
        clock=SystemClock(),
        terms_required=resolved_settings.terms_required,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            frozen_formats = await database.frozen_batch_formats()
            active_batch_peppers = await database.active_batch_peppers()
        except Exception as error:  # noqa: BLE001 - DB down is /ready's job, not a crash
            logger.warning("startup code-format/pepper check skipped: %s", error)
        else:
            verify_frozen_formats(frozen_formats)
            if expected_pepper_fingerprint is not None:
                verify_active_batch_peppers(
                    active_batch_peppers, expected_pepper_fingerprint
                )
        yield
        await database.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=APP_VERSION,
        description=(
            "Backend for the TorshX x Oxin campaign passport. The contract is "
            "docs/API_CONTRACT.md; if this schema and that file disagree about a "
            "live endpoint, the contract wins and it is a bug here."
        ),
        openapi_tags=OPENAPI_TAGS,
        generate_unique_id_function=lambda route: route.name,
        docs_url="/docs"
        if resolved_settings.environment.lower() != "production"
        else None,
        redoc_url=(
            "/redoc" if resolved_settings.environment.lower() != "production" else None
        ),
        openapi_url=(
            "/openapi.json"
            if resolved_settings.environment.lower() != "production"
            else None
        ),
        lifespan=lifespan,
    )
    # Registration order here is innermost-first (Starlette wraps each new
    # middleware around the ones already added), so outer-to-inner at
    # request time is the reverse of the calls below:
    #   RequestLogging -> CORS -> RateLimit -> Csrf -> ErrorEnvelope -> app
    # CORS must wrap RateLimit and ErrorEnvelope so a 429 or an unhandled
    # exception still carries Access-Control-* headers the browser can read
    # (FX1); Csrf stays inside CORS so a 403 also gets them.
    application.add_middleware(ErrorEnvelopeMiddleware)
    application.add_middleware(
        CsrfMiddleware,
        cookie_name=resolved_settings.session_cookie_name,
        allowed_origins=resolved_settings.allowed_cors_origins,
    )
    application.add_middleware(
        RateLimitMiddleware,
        requests=resolved_settings.rate_limit_requests,
        window_seconds=resolved_settings.rate_limit_window_seconds,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_cors_origins,
        allow_credentials=resolved_settings.allowed_cors_origins != ["*"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", CSRF_HEADER, "Idempotency-Key"],
        expose_headers=["Retry-After", "X-Request-ID"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
    build_openapi = application.openapi

    def openapi_with_error_envelope() -> dict[str, Any]:
        if application.openapi_schema is None:
            document_validation_errors(build_openapi())
        return application.openapi_schema or {}

    application.openapi = openapi_with_error_envelope  # type: ignore[method-assign]
    application.include_router(router)
    application.state.admin = mount_admin(
        application,
        database.engine,
        authentication_service,
        secret_key=(
            resolved_settings.admin_session_secret.get_secret_value()
            if resolved_settings.admin_session_secret is not None
            else None
        ),
        max_age_seconds=resolved_settings.admin_session_max_age_seconds,
        secure=resolved_settings.secure_session_cookies,
        # TODO: remove this on production (otp_test_numbers.py).
        show_test_codes=resolved_settings.test_numbers_enabled,
        session_factory=database.session_factory,
        coin_adjustment_service=coin_adjustment_service,
    )
    application.state.readiness_checker = readiness_checker
    application.state.pepper_guard = pepper_guard
    application.state.authentication_service = authentication_service
    application.state.passport_service = passport_service
    application.state.redemption_service = redemption_service
    application.state.wallet_service = wallet_service
    application.state.admin_user_service = admin_user_service
    application.state.profile_service = profile_service
    application.state.app_config_service = app_config_service
    application.state.coin_adjustment_service = coin_adjustment_service
    application.state.avatar_service = avatar_service
    application.state.legal_document_service = legal_document_service
    application.state.team_service = team_service
    application.state.me_service = me_service
    application.state.challenge_service = challenge_service
    application.state.achievement_service = achievement_service
    application.state.mini_game_service = mini_game_service
    application.state.referral_service = referral_service
    application.state.sms_sender = sms_sender
    application.state.settings = resolved_settings
    return application
