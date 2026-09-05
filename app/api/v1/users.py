from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_authentication_service, get_current_user
from app.api.v1.schemas import UserResponse, UserUpdate
from app.application.authentication import AuthenticationService
from app.domain.users import User

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.from_domain(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> UserResponse:
    user = await service.update_display_name(current_user.id, payload.display_name)
    return UserResponse.from_domain(user)
