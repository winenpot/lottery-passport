from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_authentication_service,
    get_current_user,
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
from app.application.passports import PassportService
from app.application.profile import NicknameTaken, ProfileService, TermsVersionMismatch
from app.domain.nickname import NicknameError
from app.domain.users import User

router = APIRouter(tags=["users"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The signed-in user",
    responses=_AUTH_REQUIRED,
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.from_domain(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update the signed-in user",
    description=(
        "Send any of ``display_name``, ``nickname`` and ``accept_terms_version``; "
        "only the fields sent change. ``profile_complete`` becomes true once a "
        "nickname is set and the terms are accepted."
    ),
    responses={
        **_AUTH_REQUIRED,
        409: {"model": ErrorResponse, "description": "NICKNAME_TAKEN"},
        422: {
            "model": ErrorResponse,
            "description": "NICKNAME_INVALID or TERMS_VERSION_INVALID",
        },
    },
)
async def update_me(
    payload: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
) -> UserResponse:
    user = current_user
    sent = payload.model_fields_set
    try:
        if "nickname" in sent or "accept_terms_version" in sent:
            user = await profile_service.update(
                current_user.id,
                nickname=payload.nickname,
                accept_terms_version=payload.accept_terms_version,
            )
    except NicknameError as error:
        raise ApiError(422, "NICKNAME_INVALID", f"nickname {error}") from error
    except NicknameTaken as error:
        raise ApiError(409, "NICKNAME_TAKEN", "nickname is already taken") from error
    except TermsVersionMismatch as error:
        raise ApiError(
            422, "TERMS_VERSION_INVALID", "terms version is not current"
        ) from error
    if "display_name" in sent:
        user = await auth_service.update_display_name(
            current_user.id, payload.display_name
        )
    return UserResponse.from_domain(user)


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
