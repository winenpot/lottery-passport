from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, Security, status

from app.api.deps import get_authentication_service, session_cookie
from app.api.v1.schemas import (
    AuthenticationRequest,
    AuthenticationRequested,
    AuthenticationVerification,
    UserResponse,
)
from app.application.authentication import AuthenticationError, AuthenticationService
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/request",
    response_model=AuthenticationRequested,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_authentication(
    payload: AuthenticationRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AuthenticationRequested:
    try:
        await service.request_challenge(payload.identifier)
    except AuthenticationError:
        pass
    return AuthenticationRequested(
        message=(
            "If the identifier can be used, verification instructions have been sent."
        )
    )


@router.post("/verify", response_model=UserResponse)
async def verify_authentication(
    payload: AuthenticationVerification,
    response: Response,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    try:
        result = await service.verify_challenge(payload.identifier, payload.code)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication challenge",
        ) from error
    response.set_cookie(
        key=settings.session_cookie_name,
        value=result.session_token,
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=settings.secure_session_cookies,
        samesite="lax",
    )
    return UserResponse.from_domain(result.user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Security(session_cookie)] = None,
) -> None:
    await service.logout(session_token)
    response.delete_cookie(settings.session_cookie_name)
