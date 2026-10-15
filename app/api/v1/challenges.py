"""``GET /challenges``, ``POST /challenges/{id}/claim`` (C1, B17)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_challenge_service, get_current_user
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import ChallengeClaimResponse, ChallengeResponse
from app.application.challenges import ChallengeService
from app.domain.challenges import ChallengeClaimError, ChallengeClaimRefusal
from app.domain.users import User

router = APIRouter(tags=["challenges"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


@router.get(
    "/challenges",
    response_model=list[ChallengeResponse],
    summary="Active challenges and this player's progress",
    responses=_AUTH_REQUIRED,
)
async def list_challenges(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChallengeService, Depends(get_challenge_service)],
) -> list[ChallengeResponse]:
    progress = await service.list(current_user.id)
    return [ChallengeResponse.from_domain(p) for p in progress]


@router.post(
    "/challenges/{challenge_id}/claim",
    response_model=ChallengeClaimResponse,
    summary="Claim a completed challenge",
    description=(
        "Idempotent per period: claiming twice in the same period pays "
        "once (409 CHALLENGE_ALREADY_CLAIMED on the second try)."
    ),
    responses={
        **_AUTH_REQUIRED,
        404: {"model": ErrorResponse, "description": "Unknown or inactive challenge"},
        409: {
            "model": ErrorResponse,
            "description": "CHALLENGE_NOT_UNLOCKED or CHALLENGE_ALREADY_CLAIMED",
        },
    },
)
async def claim_challenge(
    challenge_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChallengeService, Depends(get_challenge_service)],
) -> ChallengeClaimResponse:
    try:
        result = await service.claim(current_user.id, challenge_id)
    except ChallengeClaimError as error:
        raise _api_error(error) from error
    return ChallengeClaimResponse.from_result(result)


def _api_error(error: ChallengeClaimError) -> ApiError:
    if error.reason is ChallengeClaimRefusal.UNKNOWN:
        return ApiError(404, "NOT_FOUND", "unknown or inactive challenge")
    if error.reason is ChallengeClaimRefusal.ALREADY_CLAIMED:
        return ApiError(409, "CHALLENGE_ALREADY_CLAIMED", "already claimed this period")
    return ApiError(
        409,
        "CHALLENGE_NOT_UNLOCKED",
        "this challenge is not complete yet",
        details={"required": error.required, "have": error.have},
    )
