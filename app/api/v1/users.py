from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_authentication_service,
    get_current_user,
    get_me_service,
    get_passport_service,
    get_profile_service,
    get_referral_service,
    get_terms_required,
)
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import (
    PassportProgressResponse,
    ReferralStatusResponse,
    UserResponse,
    UserStatsResponse,
    UserUpdate,
)
from app.application.authentication import AuthenticationService, DisplayNameReserved
from app.application.me import MeService
from app.application.passports import PassportService
from app.application.profile import (
    AvatarLocked,
    AvatarUnknown,
    LocationCityUnknown,
    NicknameTaken,
    ProfileService,
    TermsVersionMismatch,
    VenueUnknown,
)
from app.application.referrals import (
    ReferralBindError,
    ReferralBindRefusal,
    ReferralService,
)
from app.domain.nickname import NicknameError
from app.domain.passports import CAMPAIGN_BY_CITY
from app.domain.users import User

router = APIRouter(tags=["users"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


async def _response(
    user: User,
    me_service: MeService,
    referral_service: ReferralService,
    *,
    terms_required: bool,
) -> UserResponse:
    # Settling is a no-op unless this user was referred (app/application/
    # referrals.py's module docstring explains why it lives here rather
    # than inside redeem/team-join/profile-update/mini-game-finish).
    await referral_service.settle(user.id)
    extras = await me_service.extras(user.id)
    referral_code = await referral_service.ensure_code(user.id)
    return UserResponse.from_domain(
        user,
        terms_required=terms_required,
        team=CAMPAIGN_BY_CITY[extras.team].value if extras.team else None,
        last_scanned_flavor=(
            CAMPAIGN_BY_CITY[extras.last_scanned_flavor].value
            if extras.last_scanned_flavor
            else None
        ),
        referral_code=referral_code,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The signed-in user",
    responses=_AUTH_REQUIRED,
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    me_service: Annotated[MeService, Depends(get_me_service)],
    referral_service: Annotated[ReferralService, Depends(get_referral_service)],
    terms_required: Annotated[bool, Depends(get_terms_required)],
) -> UserResponse:
    return await _response(
        current_user, me_service, referral_service, terms_required=terms_required
    )


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update the signed-in user",
    description=(
        "Send any of ``display_name``, ``nickname``, ``accept_terms_version``, "
        "``home_venue_id``, ``location_city``, ``avatar_id`` and "
        "``referrer_code``; only the fields sent change. ``profile_complete`` "
        "becomes true once a nickname is set and the terms are accepted "
        "(only the nickname when ``/config`` says ``terms_required: false``)."
    ),
    responses={
        **_AUTH_REQUIRED,
        409: {
            "model": ErrorResponse,
            "description": "NICKNAME_TAKEN or REFERRAL_ALREADY_BOUND",
        },
        422: {
            "model": ErrorResponse,
            "description": (
                "NICKNAME_INVALID, DISPLAY_NAME_RESERVED, TERMS_VERSION_INVALID, "
                "CATALOGUE_UNKNOWN, AVATAR_LOCKED, REFERRAL_CODE_UNKNOWN, "
                "REFERRAL_SELF or REFERRAL_CODE_TOO_LATE"
            ),
        },
    },
)
async def update_me(
    payload: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
    me_service: Annotated[MeService, Depends(get_me_service)],
    referral_service: Annotated[ReferralService, Depends(get_referral_service)],
    terms_required: Annotated[bool, Depends(get_terms_required)],
) -> UserResponse:
    user = current_user
    sent = payload.model_fields_set
    try:
        if sent & {
            "nickname",
            "accept_terms_version",
            "home_venue_id",
            "location_city",
            "avatar_id",
        }:
            user = await profile_service.update(
                current_user.id,
                nickname=payload.nickname,
                accept_terms_version=payload.accept_terms_version,
                home_venue_id=payload.home_venue_id,
                location_city=payload.location_city,
                avatar_id=payload.avatar_id,
            )
    except NicknameError as error:
        raise ApiError(422, "NICKNAME_INVALID", f"nickname {error}") from error
    except NicknameTaken as error:
        raise ApiError(409, "NICKNAME_TAKEN", "nickname is already taken") from error
    except TermsVersionMismatch as error:
        raise ApiError(
            422, "TERMS_VERSION_INVALID", "terms version is not current"
        ) from error
    except (VenueUnknown, LocationCityUnknown, AvatarUnknown) as error:
        raise ApiError(422, "CATALOGUE_UNKNOWN", "unknown catalogue item") from error
    except AvatarLocked as error:
        raise ApiError(422, "AVATAR_LOCKED", "this avatar is locked") from error
    if "display_name" in sent:
        try:
            user = await auth_service.update_display_name(
                current_user.id, payload.display_name
            )
        except DisplayNameReserved as error:
            raise ApiError(
                422, "DISPLAY_NAME_RESERVED", "this name is reserved"
            ) from error
    if "referrer_code" in sent and payload.referrer_code is not None:
        try:
            await referral_service.bind(current_user.id, payload.referrer_code)
        except ReferralBindError as error:
            raise _referral_bind_api_error(error) from error
    return await _response(
        user, me_service, referral_service, terms_required=terms_required
    )


def _referral_bind_api_error(error: ReferralBindError) -> ApiError:
    if error.reason is ReferralBindRefusal.CODE_UNKNOWN:
        return ApiError(422, "REFERRAL_CODE_UNKNOWN", "unknown referral code")
    if error.reason is ReferralBindRefusal.SELF:
        return ApiError(422, "REFERRAL_SELF", "cannot refer yourself")
    if error.reason is ReferralBindRefusal.TOO_LATE:
        return ApiError(
            422,
            "REFERRAL_CODE_TOO_LATE",
            "can only bind a referrer before redeeming any code",
        )
    return ApiError(409, "REFERRAL_ALREADY_BOUND", "a referrer is already bound")


@router.get(
    "/me/referrals",
    response_model=ReferralStatusResponse,
    summary="Your invite code and referral counts",
    responses=_AUTH_REQUIRED,
)
async def get_my_referrals(
    current_user: Annotated[User, Depends(get_current_user)],
    referral_service: Annotated[ReferralService, Depends(get_referral_service)],
) -> ReferralStatusResponse:
    status = await referral_service.status(current_user.id)
    return ReferralStatusResponse.from_status(status)


@router.get(
    "/me/passports",
    response_model=list[PassportProgressResponse],
    summary="Per-city passport progress",
    description=(
        "Parked for the MVP (ADR 0009): kept out of the player-facing contract "
        "but still tracked."
    ),
    responses=_AUTH_REQUIRED,
)
async def get_my_passports(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PassportService, Depends(get_passport_service)],
) -> list[PassportProgressResponse]:
    progress = await service.list_for_user(current_user.id)
    return [PassportProgressResponse.from_domain(item) for item in progress]


@router.get(
    "/me/stats",
    response_model=UserStatsResponse,
    summary="Scan, challenge, achievement and mini-game counts",
    description=(
        "Coins and referrals are not repeated here -- see ``GET /me/wallet`` "
        "and ``GET /me/referrals``."
    ),
    responses=_AUTH_REQUIRED,
)
async def get_my_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    me_service: Annotated[MeService, Depends(get_me_service)],
) -> UserStatsResponse:
    return UserStatsResponse.from_domain(await me_service.stats(current_user.id))
