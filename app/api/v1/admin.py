import base64
import binascii
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_admin_user_service, get_terms_required, require_admin
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.schemas import UserPageResponse, UserResponse
from app.application.admin_users import AdminUserService, UserCursor
from app.domain.users import User

router = APIRouter(prefix="/admin", tags=["admin"])

_ADMIN_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "AUTH_REQUIRED"},
    403: {"model": ErrorResponse, "description": "ADMIN_REQUIRED"},
}


def encode_cursor(cursor: UserCursor) -> str:
    raw = f"{cursor.created_at.isoformat()}|{cursor.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str) -> UserCursor:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        created_at, user_id = raw.split("|")
        return UserCursor(datetime.fromisoformat(created_at), UUID(user_id))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ApiError(400, "CURSOR_INVALID", "cursor is not valid") from error


@router.get(
    "/users",
    response_model=UserPageResponse,
    summary="List users (admin)",
    description=(
        "Newest first, keyset-paginated. Pass the previous response's "
        "``next_cursor`` as ``cursor``; ``next_cursor`` is null on the last page."
    ),
    responses={
        **_ADMIN_ERRORS,
        400: {"model": ErrorResponse, "description": "CURSOR_INVALID"},
    },
)
async def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    service: Annotated[AdminUserService, Depends(get_admin_user_service)],
    terms_required: Annotated[bool, Depends(get_terms_required)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> UserPageResponse:
    after = decode_cursor(cursor) if cursor else None
    page = await service.list_users(limit, after)
    return UserPageResponse(
        items=[
            UserResponse.from_domain(user, terms_required=terms_required)
            for user in page.items
        ],
        next_cursor=encode_cursor(page.next_cursor) if page.next_cursor else None,
    )
