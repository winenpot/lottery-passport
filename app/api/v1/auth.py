from typing import Annotated

from fastapi import APIRouter, Depends, Response, Security, status

from app.api.deps import (
    get_authentication_service,
    get_terms_required,
    session_cookie,
)
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import (
    AuthenticationRequest,
    AuthenticationRequested,
    AuthenticationVerification,
    UserResponse,
)
from app.application.authentication import (
    AuthenticationError,
    AuthenticationService,
    DailyLimitError,
    PhoneInvalidError,
    ResendCooldownError,
)
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/request",
    response_model=AuthenticationRequested,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a sign-in code",
    description=(
        "Accepts Persian or Latin digits, spaces, +98/0098/98 or a leading 0. "
        "The response is the same shape for a new and a known number."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "PHONE_INVALID"},
        429: {
            "model": ErrorResponse,
            "description": "OTP_COOLDOWN or OTP_DAILY_LIMIT",
        },
        503: {"model": ErrorResponse, "description": "SMS delivery is unavailable"},
    },
)
async def request_authentication(
    payload: AuthenticationRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AuthenticationRequested:
    try:
        result = await service.request_challenge(payload.identifier)
    except PhoneInvalidError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "PHONE_INVALID",
            "not an Iranian mobile number",
        ) from error
    except ResendCooldownError as error:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "OTP_COOLDOWN",
            "a code was already sent recently",
            retry_after_seconds=error.retry_after_seconds,
        ) from error
    except DailyLimitError as error:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "OTP_DAILY_LIMIT",
            "too many codes requested for this number today",
        ) from error
    except AuthenticationError as error:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            "could not send the verification code",
        ) from error
    return AuthenticationRequested(
        resend_after_seconds=result.resend_after_seconds,
        expires_in_seconds=result.expires_in_seconds,
        code_length=result.code_length,
        test_code=result.test_code,
    )


@router.post(
    "/verify",
    response_model=UserResponse,
    summary="Verify a sign-in code",
    description=(
        "The first successful verify creates the account. Sets the session "
        "cookie on success (see docs/API_CONTRACT.md#hosts-cors-and-cookies)."
    ),
    responses={401: {"model": ErrorResponse, "description": "OTP_INVALID"}},
)
async def verify_authentication(
    payload: AuthenticationVerification,
    response: Response,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    terms_required: Annotated[bool, Depends(get_terms_required)],
) -> UserResponse:
    try:
        result = await service.verify_challenge(payload.identifier, payload.code)
    except AuthenticationError as error:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "OTP_INVALID",
            "wrong, expired or already-used code, or too many attempts",
        ) from error
    response.set_cookie(
        key=settings.session_cookie_name,
        value=result.session_token,
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=settings.secure_session_cookies,
        samesite=settings.session_cookie_samesite,
    )
    return UserResponse.from_domain(result.user, terms_required=terms_required)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session",
    description="Clears the session cookie; always 204, even with no session.",
)
async def logout(
    response: Response,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Security(session_cookie)] = None,
) -> None:
    await service.logout(session_token)
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.secure_session_cookies,
        samesite=settings.session_cookie_samesite,
    )
