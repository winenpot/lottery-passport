from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie

from app.application.authentication import AuthenticationError, AuthenticationService
from app.application.ports import ReadinessChecker
from app.domain.users import User

session_cookie = APIKeyCookie(
    name="lottery_passport_session",
    scheme_name="Session Cookie",
    auto_error=False,
)


def get_readiness_checker(request: Request) -> ReadinessChecker:
    return cast(ReadinessChecker, request.app.state.readiness_checker)


def get_authentication_service(request: Request) -> AuthenticationService:
    return cast(AuthenticationService, request.app.state.authentication_service)


async def get_current_user(
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    session_token: Annotated[str | None, Security(session_cookie)] = None,
) -> User:
    try:
        return await service.get_current_user(session_token)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        ) from error
