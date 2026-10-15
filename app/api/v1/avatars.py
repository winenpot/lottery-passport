from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_avatar_service
from app.api.v1.schemas import AvatarResponse
from app.application.avatars import AvatarService

router = APIRouter(tags=["avatars"])


@router.get(
    "/avatars",
    response_model=list[AvatarResponse],
    summary="Avatar catalogue",
    description=(
        "No sign-in needed. Includes locked avatars (so the frontend can show "
        "them as 'coming later'); only unlocked ones can be picked with "
        "``PATCH /me avatar_id``."
    ),
)
async def list_avatars(
    service: Annotated[AvatarService, Depends(get_avatar_service)],
) -> list[AvatarResponse]:
    return [AvatarResponse.from_domain(avatar) for avatar in await service.list()]
