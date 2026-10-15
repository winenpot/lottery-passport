from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_team_service
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import TeamChangeRequest, TeamStatusResponse
from app.application.teams import TeamService
from app.domain.passports import CAMPAIGN_BY_CITY
from app.domain.teams import TeamChangeError, TeamChangeRefusal
from app.domain.users import User

router = APIRouter(tags=["teams"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}

_FLAVOR_BY_SLUG = {campaign.value: city for city, campaign in CAMPAIGN_BY_CITY.items()}


@router.get(
    "/me/team",
    response_model=TeamStatusResponse,
    summary="Current flavor team and per-flavor unlock progress",
    responses=_AUTH_REQUIRED,
)
async def get_my_team(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> TeamStatusResponse:
    return TeamStatusResponse.from_domain(await service.status(current_user.id))


@router.post(
    "/me/team",
    response_model=TeamStatusResponse,
    summary="Join or switch flavor team",
    description=(
        "Joins (first time) or switches to an unlocked flavor (5+ lifetime "
        "codes of it). Switching is locked for a while after each join; see "
        "``GET /me/team`` for ``switch_allowed_at``."
    ),
    responses={
        **_AUTH_REQUIRED,
        409: {
            "model": ErrorResponse,
            "description": "FLAVOR_NOT_UNLOCKED or TEAM_LOCKED",
        },
        422: {"model": ErrorResponse, "description": "TEAM_SAME or unknown flavor"},
    },
)
async def change_my_team(
    payload: TeamChangeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> TeamStatusResponse:
    flavor = _FLAVOR_BY_SLUG.get(payload.flavor)
    if flavor is None:
        raise ApiError(422, "CATALOGUE_UNKNOWN", "unknown flavor")
    try:
        await service.change(current_user.id, flavor)
    except TeamChangeError as error:
        raise _api_error(error) from error
    return TeamStatusResponse.from_domain(await service.status(current_user.id))


def _api_error(error: TeamChangeError) -> ApiError:
    if error.reason is TeamChangeRefusal.SAME_TEAM:
        return ApiError(422, "TEAM_SAME", "already on this team")
    if error.reason is TeamChangeRefusal.FLAVOR_NOT_UNLOCKED:
        return ApiError(
            409,
            "FLAVOR_NOT_UNLOCKED",
            "this flavor is not unlocked yet",
            details={"required": error.required, "have": error.have},
        )
    allowed_at = error.allowed_at.isoformat() if error.allowed_at else None
    return ApiError(
        409,
        "TEAM_LOCKED",
        "team switching is locked for now",
        details={"switch_allowed_at": allowed_at},
    )
