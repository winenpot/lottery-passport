"""``GET /me/achievements`` (unlocked only) and ``GET /achievements``
(every active row + progress, B44/W13) -- see app/domain/achievements.py.

There is no claim endpoint -- unlocking happens automatically inside the
triggering write (today, a ``DAILY_CHECKIN`` claim) and pays in the same
transaction.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_achievement_service, get_current_user
from app.api.errors import ErrorResponse
from app.api.v1.schemas import AchievementProgressResponse, UnlockedAchievementResponse
from app.application.achievements import AchievementService
from app.domain.users import User

router = APIRouter(tags=["achievements"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


@router.get(
    "/achievements",
    response_model=list[AchievementProgressResponse],
    summary="Every active achievement and this player's progress",
    responses=_AUTH_REQUIRED,
)
async def list_achievements(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AchievementService, Depends(get_achievement_service)],
) -> list[AchievementProgressResponse]:
    progress = await service.list_progress(current_user.id)
    return [AchievementProgressResponse.from_domain(p) for p in progress]


@router.get(
    "/me/achievements",
    response_model=list[UnlockedAchievementResponse],
    summary="This player's unlocked achievements",
    responses=_AUTH_REQUIRED,
)
async def list_my_achievements(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AchievementService, Depends(get_achievement_service)],
) -> list[UnlockedAchievementResponse]:
    unlocked = await service.list_unlocked(current_user.id)
    return [UnlockedAchievementResponse.from_domain(a) for a in unlocked]
