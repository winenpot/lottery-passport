"""``GET /leaderboards/mini-games/{mini_game_id}`` (L1) -- see
app/application/leaderboards.py for the ranking/tie-break/cache rules and
docs/API_CONTRACT.md's mini-games leaderboard section for the response
shape. The weekly coins leaderboard (``GET /leaderboards/weekly``, B21) is a
separate, not-yet-built feature -- do not assume it exists from this file.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user, get_leaderboard_service
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import LeaderboardResponse
from app.application.leaderboards import (
    LeaderboardPeriod,
    LeaderboardService,
    UnknownMiniGameBoard,
)
from app.domain.mini_games import MiniGameId
from app.domain.users import User

router = APIRouter(tags=["leaderboards"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


@router.get(
    "/leaderboards/mini-games/{mini_game_id}",
    response_model=LeaderboardResponse,
    summary="This mini-game's best-score board for a period",
    description=(
        "Each player's best run in the period; ties go to whoever set it "
        "first. Top 50 plus `me` (the caller's own rank and score, even "
        "outside the top 50). Cached up to 60 seconds -- see `updated_at`."
    ),
    responses={
        **_AUTH_REQUIRED,
        404: {"model": ErrorResponse, "description": "Unknown mini_game_id"},
    },
)
async def get_mini_game_leaderboard(
    mini_game_id: MiniGameId,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LeaderboardService, Depends(get_leaderboard_service)],
    period: Annotated[
        LeaderboardPeriod, Query(description="today | week | all")
    ] = LeaderboardPeriod.WEEK,
) -> LeaderboardResponse:
    try:
        board = await service.get(mini_game_id, period, current_user.id)
    except UnknownMiniGameBoard as error:
        raise ApiError(404, "NOT_FOUND", "unknown mini_game_id") from error
    return LeaderboardResponse.from_domain(board, current_user_id=current_user.id)
