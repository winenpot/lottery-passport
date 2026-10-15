"""``GET /me/achievements`` (AC1 MVP slice): this player's unlocked
achievements. There is no claim endpoint -- unlocking happens automatically
inside the triggering write (today, a ``DAILY_CHECKIN`` claim) and pays in
the same transaction. See app/domain/achievements.py."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_achievement_service, get_current_user
from app.api.errors import ErrorResponse
from app.api.v1.schemas import UnlockedAchievementResponse
from app.application.achievements import AchievementService
from app.domain.users import User

router = APIRouter(tags=["achievements"])

_AUTH_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in"}
}


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
