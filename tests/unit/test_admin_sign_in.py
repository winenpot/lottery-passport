"""Admin panel sign-in (ADR-0008 as amended): admins only, no player session."""

import pytest

from app.application.authentication import AuthenticationError
from app.domain.users import AccountStatus, UserRole
from tests.unit.test_authentication import build_service

ADMIN = "+989121112233"
PLAYER = "+989124445566"


async def _with_users() -> tuple:
    service, clock, sms, users = build_service()
    admin = await users.create(ADMIN, clock.now())
    admin.role = UserRole.ADMIN
    player = await users.create(PLAYER, clock.now())
    return service, sms, users, admin, player


@pytest.mark.asyncio
async def test_an_admin_gets_a_code_and_signs_in_without_a_player_session() -> None:
    service, sms, _, admin, _ = await _with_users()

    await service.request_admin_challenge("0912 111 2233")
    user = await service.verify_admin_challenge(ADMIN, sms.code or "")

    assert sms.send_count == 1
    assert user.id == admin.id
    assert service._sessions.items == {}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_player_or_unknown_number_gets_no_sms_and_the_same_answer() -> None:
    service, sms, users, _, _ = await _with_users()

    for number in (PLAYER, "+989127778899"):
        result = await service.request_admin_challenge(number)
        assert (result.code_length, result.test_code) == (6, None)

    assert sms.send_count == 0
    # The unknown number was not turned into an account either.
    assert await users.get_by_identifier("+989127778899") is None


@pytest.mark.asyncio
async def test_a_player_code_from_the_app_does_not_open_the_panel() -> None:
    service, sms, _, _, _ = await _with_users()
    await service.request_challenge(PLAYER)

    with pytest.raises(AuthenticationError):
        await service.verify_admin_challenge(PLAYER, sms.code or "")


@pytest.mark.asyncio
async def test_a_wrong_code_is_refused() -> None:
    service, _, _, _, _ = await _with_users()
    await service.request_admin_challenge(ADMIN)

    with pytest.raises(AuthenticationError):
        await service.verify_admin_challenge(ADMIN, "000000")


@pytest.mark.asyncio
async def test_demotion_or_deactivation_ends_admin_access_at_once() -> None:
    service, _, _, admin, player = await _with_users()

    assert await service.get_active_admin(admin.id) == admin
    assert await service.get_active_admin(player.id) is None

    admin.account_status = AccountStatus.INACTIVE
    assert await service.get_active_admin(admin.id) is None
    admin.account_status = AccountStatus.ACTIVE
    admin.role = UserRole.PLAYER
    assert await service.get_active_admin(admin.id) is None
