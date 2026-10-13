from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_current_user,
    get_redemption_service,
    get_wallet_service,
    require_complete_profile,
)
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import RedeemCodeRequest, RedemptionResponse, WalletResponse
from app.application.redemption_codes import (
    RedemptionError,
    RedemptionErrorCode,
    RedemptionService,
)
from app.application.wallets import WalletService
from app.domain.users import User

router = APIRouter(tags=["redemptions"])

_ERRORS: dict[RedemptionErrorCode, tuple[int, str]] = {
    RedemptionErrorCode.NOT_CONFIGURED: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Code redemption is temporarily unavailable.",
    ),
    RedemptionErrorCode.MALFORMED: (
        status.HTTP_400_BAD_REQUEST,
        "This is not a product code.",
    ),
    RedemptionErrorCode.MISTYPED: (
        status.HTTP_400_BAD_REQUEST,
        "One character looks mistyped; check the code on the package.",
    ),
    RedemptionErrorCode.INVALID: (
        status.HTTP_404_NOT_FOUND,
        "This code is not valid.",
    ),
    RedemptionErrorCode.ALREADY_REDEEMED: (
        status.HTTP_409_CONFLICT,
        "This code has already been used by another account.",
    ),
    RedemptionErrorCode.DAILY_LIMIT: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Daily redemption limit reached; try again tomorrow.",
    ),
    RedemptionErrorCode.ATTEMPTS_LIMITED: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many failed attempts; try again later.",
    ),
}


@router.post(
    "/redemptions",
    response_model=RedemptionResponse,
    summary="Redeem a printed code",
    description=(
        "Redeem a printed code. Needs a complete profile (terms accepted and "
        "a nickname). Safe to retry: a repeat by the same user returns "
        "``replayed: true`` instead of an error."
    ),
    responses={
        400: {
            "model": ErrorResponse,
            "description": "CODE_MALFORMED or CODE_MISTYPED",
        },
        401: {"model": ErrorResponse, "description": "Not signed in"},
        403: {
            "model": ErrorResponse,
            "description": "TERMS_NOT_ACCEPTED or PROFILE_INCOMPLETE",
        },
        404: {"model": ErrorResponse, "description": "CODE_INVALID"},
        409: {"model": ErrorResponse, "description": "CODE_ALREADY_REDEEMED"},
        429: {
            "model": ErrorResponse,
            "description": "REDEMPTION_DAILY_LIMIT or CODE_ATTEMPTS_LIMITED",
        },
    },
)
async def redeem_code(
    payload: RedeemCodeRequest,
    current_user: Annotated[User, Depends(require_complete_profile)],
    service: Annotated[RedemptionService, Depends(get_redemption_service)],
) -> RedemptionResponse:
    try:
        result = await service.redeem(current_user.id, payload.code)
    except RedemptionError as error:
        status_code, message = _ERRORS[error.code]
        raise ApiError(
            status_code,
            error.code.value,
            message,
            retry_after_seconds=error.retry_after,
        ) from error
    return RedemptionResponse.from_result(result)


@router.get(
    "/me/wallet",
    response_model=WalletResponse,
    summary="Coin balance and recent ledger entries",
    responses={401: {"model": ErrorResponse, "description": "Not signed in"}},
)
async def get_my_wallet(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WalletService, Depends(get_wallet_service)],
) -> WalletResponse:
    return WalletResponse.from_view(await service.view(current_user.id))
