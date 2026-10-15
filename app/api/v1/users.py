from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_authentication_service,
    get_current_user,
    get_me_service,
    get_passport_service,
    get_profile_service,
)
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import (
    PassportProgressResponse,
    UserResponse,
    UserUpdate,
)
from app.application.authentication import AuthenticationService
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
from app.domain.nickname import NicknameError
from app.domain.passports import CAMPAIGN_BY_CITY
from app.domain.users import User

router = APIRouter(tags=["users"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


async def _response(user: User, me_service: MeService) -> UserResponse:
    extras = await me_service.extras(user.id)
    return UserResponse.from_domain(
        user,
        team=CAMPAIGN_BY_CITY[extras.team].value if extras.team else None,
        last_scanned_flavor=(
            CAMPAIGN_BY_CITY[extras.last_scanned_flavor].value
            if extras.last_scanned_flavor
            else None
        ),
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
) -> UserResponse:
    return await _response(current_user, me_service)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update the signed-in user",
    description=(
        "Send any of ``display_name``, ``nickname``, ``accept_terms_version``, "
        "``home_venue_id``, ``location_city`` and ``avatar_id``; only the fields "
        "sent change. ``profile_complete`` becomes true once a nickname is set "
        "and the terms are accepted."
    ),
    responses={
        **_AUTH_REQUIRED,
        409: {"model": ErrorResponse, "description": "NICKNAME_TAKEN"},
        422: {
            "model": ErrorResponse,
            "description": (
                "NICKNAME_INVALID, TERMS_VERSION_INVALID, CATALOGUE_UNKNOWN or "
                "AVATAR_LOCKED"
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
        user = await auth_service.update_display_name(
            current_user.id, payload.display_name
        )
    return await _response(user, me_service)


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
