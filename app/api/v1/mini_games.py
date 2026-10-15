"""``POST /mini-games/{mini_game_id}/runs``, ``POST /mini-games/runs/{run_id}/finish``.

See app/domain/mini_games.py and app/application/mini_games.py for why a
rejected (implausible) finish is a normal 200, not a 4xx: rewards never
pay from this endpoint, only through GET/POST /challenges.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_mini_game_service
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import (
    MiniGameRunFinishRequest,
    MiniGameRunFinishResponse,
    MiniGameRunStartResponse,
)
from app.application.mini_games import (
    MiniGameRunError,
    MiniGameRunRefusal,
    MiniGameService,
    MiniGameStartError,
    MiniGameStartRefusal,
)
from app.domain.mini_games import MiniGameId
from app.domain.users import User

router = APIRouter(tags=["mini-games"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


@router.post(
    "/mini-games/{mini_game_id}/runs",
    response_model=MiniGameRunStartResponse,
    summary="Start a server-verified mini-game run",
    description=(
        "One open run per mini-game per player at a time; it expires 2 "
        "minutes after issue."
    ),
    responses={
        **_AUTH_REQUIRED,
        409: {
            "model": ErrorResponse,
            "description": "MINI_GAME_RUN_ALREADY_OPEN",
        },
    },
)
async def start_mini_game_run(
    mini_game_id: MiniGameId,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MiniGameService, Depends(get_mini_game_service)],
) -> MiniGameRunStartResponse:
    try:
        result = await service.start_run(current_user.id, mini_game_id)
    except MiniGameStartError as error:
        raise _start_api_error(error) from error
    return MiniGameRunStartResponse.from_result(result)


@router.post(
    "/mini-games/runs/{run_id}/finish",
    response_model=MiniGameRunFinishResponse,
    summary="Report a mini-game run's per-round reaction times",
    description=(
        "Always 200 for a structurally valid attempt, even when the server's "
        "plausibility check rejects it (`accepted: false`, no reward). "
        "Rewards pay only through GET/POST /challenges."
    ),
    responses={
        **_AUTH_REQUIRED,
        404: {"model": ErrorResponse, "description": "Unknown run"},
        409: {
            "model": ErrorResponse,
            "description": "MINI_GAME_RUN_ALREADY_FINISHED or MINI_GAME_RUN_EXPIRED",
        },
        422: {
            "model": ErrorResponse,
            "description": "MINI_GAME_ROUND_COUNT_MISMATCH",
        },
    },
)
async def finish_mini_game_run(
    run_id: UUID,
    body: MiniGameRunFinishRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MiniGameService, Depends(get_mini_game_service)],
) -> MiniGameRunFinishResponse:
    try:
        result = await service.finish_run(current_user.id, run_id, body.reactions_ms)
    except MiniGameRunError as error:
        raise _finish_api_error(error) from error
    return MiniGameRunFinishResponse.from_result(result)


def _start_api_error(error: MiniGameStartError) -> ApiError:
    assert error.reason is MiniGameStartRefusal.ALREADY_OPEN
    return ApiError(
        409, "MINI_GAME_RUN_ALREADY_OPEN", "finish or wait out the open run first"
    )


def _finish_api_error(error: MiniGameRunError) -> ApiError:
    # NOT_OWNER reads as NOT_FOUND on purpose: a run id does not reveal
    # whether it belongs to someone else.
    if error.reason in (MiniGameRunRefusal.NOT_FOUND, MiniGameRunRefusal.NOT_OWNER):
        return ApiError(404, "NOT_FOUND", "unknown run")
    if error.reason is MiniGameRunRefusal.ALREADY_FINISHED:
        return ApiError(409, "MINI_GAME_RUN_ALREADY_FINISHED", "run already finished")
    if error.reason is MiniGameRunRefusal.EXPIRED:
        return ApiError(409, "MINI_GAME_RUN_EXPIRED", "run expired before finishing")
    return ApiError(
        422,
        "MINI_GAME_ROUND_COUNT_MISMATCH",
        "reactions_ms must have one entry per issued round",
    )
