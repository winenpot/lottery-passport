"""require_admin gates staff-only routes; player accounts are rejected."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus


def make_user(role: UserRole) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        identifier="staff@example.com",
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=role,
        created_at=now,
        updated_at=now,
    )


async def test_an_admin_passes_through() -> None:
    admin = make_user(UserRole.ADMIN)

    assert await require_admin(admin) is admin


async def test_a_player_is_rejected() -> None:
    player = make_user(UserRole.PLAYER)

    with pytest.raises(ApiError) as excinfo:
        await require_admin(player)

    assert excinfo.value.status_code == 403
    assert excinfo.value.code == "ADMIN_REQUIRED"


def test_user_response_carries_the_role() -> None:
    from app.api.v1.schemas import UserResponse

    response = UserResponse.from_domain(make_user(UserRole.ADMIN), terms_required=True)

    assert response.role == "admin"
