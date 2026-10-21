from typing import Annotated, cast

from fastapi import Depends, Request, Security, status
from fastapi.security import APIKeyCookie

from app.api.errors import ApiError
from app.application.achievements import AchievementService
from app.application.admin_users import AdminUserService
from app.application.app_config import AppConfigService
from app.application.authentication import AuthenticationError, AuthenticationService
from app.application.avatars import AvatarService
from app.application.challenges import ChallengeService
from app.application.leaderboards import LeaderboardService
from app.application.legal import LegalDocumentService
from app.application.me import MeService
from app.application.media import MediaService
from app.application.mini_games import MiniGameService
from app.application.passports import PassportService
from app.application.ports import ReadinessChecker
from app.application.profile import ProfileService
from app.application.redemption_codes import PepperGuard, RedemptionService
from app.application.referrals import ReferralService
from app.application.teams import TeamService
from app.application.wallets import WalletService
from app.domain.users import User, UserRole

session_cookie_scheme = APIKeyCookie(
    name="lottery_passport_session",
    scheme_name="Session Cookie",
    auto_error=False,
)


def session_cookie(
    request: Request,
    _documented: Annotated[str | None, Security(session_cookie_scheme)] = None,
) -> str | None:
    """The session token from the cookie named by ``SESSION_COOKIE_NAME``.

    ``session_cookie_scheme`` only documents the cookie in OpenAPI (default
    name); it is built at import time and cannot know the served app's
    setting, so reading through it ignored a renamed cookie (e.g.
    ``__Host-lp_session``) and every session looked logged out.
    """
    name: str = request.app.state.settings.session_cookie_name
    return request.cookies.get(name)


def get_readiness_checker(request: Request) -> ReadinessChecker:
    return cast(ReadinessChecker, request.app.state.readiness_checker)


def get_pepper_guard(request: Request) -> PepperGuard:
    return cast(PepperGuard, request.app.state.pepper_guard)


def get_profile_service(request: Request) -> ProfileService:
    return cast(ProfileService, request.app.state.profile_service)


def get_app_config_service(request: Request) -> AppConfigService:
    return cast(AppConfigService, request.app.state.app_config_service)


def get_terms_required(request: Request) -> bool:
    """``TERMS_REQUIRED`` of the app being served (not the env-cached Settings)."""
    return bool(request.app.state.settings.terms_required)


def get_admin_user_service(request: Request) -> AdminUserService:
    return cast(AdminUserService, request.app.state.admin_user_service)


def get_authentication_service(request: Request) -> AuthenticationService:
    return cast(AuthenticationService, request.app.state.authentication_service)


def get_passport_service(request: Request) -> PassportService:
    return cast(PassportService, request.app.state.passport_service)


def get_redemption_service(request: Request) -> RedemptionService:
    return cast(RedemptionService, request.app.state.redemption_service)


def get_wallet_service(request: Request) -> WalletService:
    return cast(WalletService, request.app.state.wallet_service)


def get_avatar_service(request: Request) -> AvatarService:
    return cast(AvatarService, request.app.state.avatar_service)


def get_legal_document_service(request: Request) -> LegalDocumentService:
    return cast(LegalDocumentService, request.app.state.legal_document_service)


def get_team_service(request: Request) -> TeamService:
    return cast(TeamService, request.app.state.team_service)


def get_challenge_service(request: Request) -> ChallengeService:
    return cast(ChallengeService, request.app.state.challenge_service)


def get_achievement_service(request: Request) -> AchievementService:
    return cast(AchievementService, request.app.state.achievement_service)


def get_media_service(request: Request) -> MediaService:
    return cast(MediaService, request.app.state.media_service)


def get_mini_game_service(request: Request) -> MiniGameService:
    return cast(MiniGameService, request.app.state.mini_game_service)


def get_leaderboard_service(request: Request) -> LeaderboardService:
    return cast(LeaderboardService, request.app.state.leaderboard_service)


def get_me_service(request: Request) -> MeService:
    return cast(MeService, request.app.state.me_service)


def get_referral_service(request: Request) -> ReferralService:
    return cast(ReferralService, request.app.state.referral_service)


async def get_current_user(
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    session_token: Annotated[str | None, Security(session_cookie)] = None,
) -> User:
    try:
        return await service.get_current_user(session_token)
    except AuthenticationError as error:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "authentication required"
        ) from error


async def require_complete_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    terms_required: Annotated[bool, Depends(get_terms_required)],
) -> User:
    """Gate for actions that need a finished sign-up (scanning codes).

    Terms are checked first: accepting them is the first onboarding step the
    player can still be missing, and the frontend shows that screen. With
    ``TERMS_REQUIRED=false`` (never in production) only the nickname counts.
    """
    if terms_required and current_user.terms_accepted_at is None:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "TERMS_NOT_ACCEPTED",
            "accept the current terms first (PATCH /me accept_terms_version)",
        )
    if current_user.nickname is None:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "PROFILE_INCOMPLETE",
            "set a nickname first (PATCH /me nickname)",
        )
    return current_user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Gate for staff-only routes.

    Every admin route depends on this, so "signed in" and "signed in as
    staff" stay two separate checks.
    """
    if current_user.role is not UserRole.ADMIN:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "ADMIN_REQUIRED", "admin role required"
        )
    return current_user
