"""Referrals (RF1) against real PostgreSQL: migration 0019's constraints,
``SqlReferrals`` directly, and ``ReferralService`` end to end (bind, settle,
idempotent replay). Mirrors ``test_mini_games_uow_db.py``'s shape.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from random import Random
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.application.referrals import (
    ReferralBindError,
    ReferralBindRefusal,
    ReferralService,
)
from app.core.config import Settings
from app.domain.mini_games import MiniGameId, MiniGameRunStatus, open_run
from app.domain.nickname import parse_nickname
from app.domain.passports import CityCode
from app.domain.referrals import FIRST_CODE_BONUS_COINS, LATER_CODE_BONUS_COINS
from app.domain.teams import TeamMembership
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import RedemptionCodeModel, ReferralModel
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


async def new_user_id(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(
        f"it-referral-{uuid4().hex}@example.com", datetime.now(UTC)
    )
    return user.id


async def insert_redeemed_code(
    database: PostgreSQLAdapter, user_id: UUID, redeemed_at: datetime
) -> UUID:
    code_id = uuid4()
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(RedemptionCodeModel).values(
                id=code_id,
                city="TO",
                code_hash=uuid4().hex,
                created_at=redeemed_at,
                redeemed_at=redeemed_at,
                redeemed_by_user_id=user_id,
                batch_id=None,
            )
        )
    return code_id


async def complete_mission(
    database: PostgreSQLAdapter, user_id: UUID, now: datetime
) -> None:
    """Nickname + terms accepted + a team + one accepted mini-game run --
    everything ``ReferralInviteeStatus`` checks."""
    users = PostgreSQLUserRepository(database.session_factory)
    await users.update_profile(
        user_id,
        now,
        nickname=parse_nickname("NightOwl" + uuid4().hex[:4]),
        terms_version="2026-10-01",
    )
    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        await uow.teams.add(
            TeamMembership(
                user_id=user_id,
                flavor=CityCode.TOKYO,
                switch_no=0,
                joined_at=now,
            )
        )
        run = open_run(user_id, MiniGameId.TAP_REFLEX, now, Random(1))
        await uow.mini_games.open(run)
        await uow.mini_games.finish(run.id, MiniGameRunStatus.ACCEPTED, now, 300.0)
        await uow.commit()


def _service(database: PostgreSQLAdapter, now: datetime) -> ReferralService:
    return ReferralService(
        code_store=PostgreSQLUserRepository(database.session_factory),
        unit_of_work=lambda: SqlAlchemyUnitOfWork(database.session_factory),
        clock=FixedClock(now),
        terms_required=True,
    )


# --- migration 0019 --------------------------------------------------------


async def test_referral_code_is_unique(database: PostgreSQLAdapter) -> None:
    users = PostgreSQLUserRepository(database.session_factory)
    a, b = await new_user_id(database), await new_user_id(database)
    candidate = uuid4().hex[:8].upper()
    assert await users.ensure_referral_code(a, lambda: candidate) == candidate
    with pytest.raises(RuntimeError):
        # every candidate collides -- proves the DB unique constraint holds,
        # not just the application's own check.
        await users.ensure_referral_code(b, lambda: candidate)


async def test_referrals_rejects_self_referral_at_the_database(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    with pytest.raises(IntegrityError, match="ck_referrals_no_self"):
        async with database.session_factory() as session, session.begin():
            await session.execute(
                insert(ReferralModel).values(
                    invitee_user_id=user_id,
                    inviter_user_id=user_id,
                    bound_at=datetime.now(UTC),
                )
            )


async def test_a_second_bind_for_the_same_invitee_is_rejected_at_the_database(
    database: PostgreSQLAdapter,
) -> None:
    invitee = await new_user_id(database)
    first_inviter, second_inviter = (
        await new_user_id(database),
        await new_user_id(database),
    )
    now = datetime.now(UTC)
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(ReferralModel).values(
                invitee_user_id=invitee, inviter_user_id=first_inviter, bound_at=now
            )
        )
    with pytest.raises(IntegrityError):
        async with database.session_factory() as session, session.begin():
            await session.execute(
                insert(ReferralModel).values(
                    invitee_user_id=invitee,
                    inviter_user_id=second_inviter,
                    bound_at=now,
                )
            )


# --- ReferralService.bind ---------------------------------------------------


async def test_bind_creates_a_referral(database: PostgreSQLAdapter) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter = await new_user_id(database)
    invitee = await new_user_id(database)
    code = await service.ensure_code(inviter)

    await service.bind(invitee, code)

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        binding = await uow.referrals.get_by_invitee(invitee)
    assert binding is not None
    assert binding.inviter_user_id == inviter


async def test_bind_rejects_self_referral(database: PostgreSQLAdapter) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    user_id = await new_user_id(database)
    code = await service.ensure_code(user_id)

    with pytest.raises(ReferralBindError) as excinfo:
        await service.bind(user_id, code)
    assert excinfo.value.reason is ReferralBindRefusal.SELF


async def test_bind_rejects_an_unknown_code(database: PostgreSQLAdapter) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    invitee = await new_user_id(database)

    with pytest.raises(ReferralBindError) as excinfo:
        await service.bind(invitee, "NOPE0000")
    assert excinfo.value.reason is ReferralBindRefusal.CODE_UNKNOWN


async def test_bind_rejects_a_second_bind(database: PostgreSQLAdapter) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter_a, inviter_b = (
        await new_user_id(database),
        await new_user_id(database),
    )
    invitee = await new_user_id(database)
    code_a, code_b = (
        await service.ensure_code(inviter_a),
        await service.ensure_code(inviter_b),
    )
    await service.bind(invitee, code_a)

    with pytest.raises(ReferralBindError) as excinfo:
        await service.bind(invitee, code_b)
    assert excinfo.value.reason is ReferralBindRefusal.ALREADY_BOUND


async def test_bind_rejects_after_a_code_was_already_redeemed(
    database: PostgreSQLAdapter,
) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter = await new_user_id(database)
    invitee = await new_user_id(database)
    code = await service.ensure_code(inviter)
    await insert_redeemed_code(database, invitee, now)

    with pytest.raises(ReferralBindError) as excinfo:
        await service.bind(invitee, code)
    assert excinfo.value.reason is ReferralBindRefusal.TOO_LATE


# --- ReferralService.settle --------------------------------------------------


async def test_settle_pays_nothing_while_the_mission_is_incomplete(
    database: PostgreSQLAdapter,
) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter = await new_user_id(database)
    invitee = await new_user_id(database)
    await service.bind(invitee, await service.ensure_code(inviter))
    await insert_redeemed_code(database, invitee, now)

    await service.settle(invitee)

    status = await service.status(inviter)
    assert status.coins_earned == 0
    assert status.pending_count == 1
    assert status.qualified_count == 0


async def test_settle_pays_first_and_later_codes_once_mission_completes(
    database: PostgreSQLAdapter,
) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter = await new_user_id(database)
    invitee = await new_user_id(database)
    await service.bind(invitee, await service.ensure_code(inviter))
    await insert_redeemed_code(database, invitee, now)
    await insert_redeemed_code(database, invitee, now + timedelta(days=1))
    await complete_mission(database, invitee, now + timedelta(days=1))

    await service.settle(invitee)

    status = await service.status(inviter)
    assert status.coins_earned == FIRST_CODE_BONUS_COINS + LATER_CODE_BONUS_COINS
    assert status.qualified_count == 1
    assert status.pending_count == 0


async def test_settle_is_idempotent_on_replay(database: PostgreSQLAdapter) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter = await new_user_id(database)
    invitee = await new_user_id(database)
    await service.bind(invitee, await service.ensure_code(inviter))
    await insert_redeemed_code(database, invitee, now)
    await complete_mission(database, invitee, now)

    await service.settle(invitee)
    await service.settle(invitee)
    await service.settle(invitee)

    status = await service.status(inviter)
    assert status.coins_earned == FIRST_CODE_BONUS_COINS


async def test_settle_pays_a_newly_qualifying_later_code_without_double_paying(
    database: PostgreSQLAdapter,
) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter = await new_user_id(database)
    invitee = await new_user_id(database)
    await service.bind(invitee, await service.ensure_code(inviter))
    await insert_redeemed_code(database, invitee, now)
    await complete_mission(database, invitee, now)
    await service.settle(invitee)

    await insert_redeemed_code(database, invitee, now + timedelta(days=2))
    await service.settle(invitee)

    status = await service.status(inviter)
    assert status.coins_earned == FIRST_CODE_BONUS_COINS + LATER_CODE_BONUS_COINS


async def test_a_code_outside_the_window_is_never_paid(
    database: PostgreSQLAdapter,
) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    inviter = await new_user_id(database)
    invitee = await new_user_id(database)
    await service.bind(invitee, await service.ensure_code(inviter))
    await insert_redeemed_code(database, invitee, now)
    await insert_redeemed_code(database, invitee, now + timedelta(days=200))
    await complete_mission(database, invitee, now)

    await service.settle(invitee)

    status = await service.status(inviter)
    assert status.coins_earned == FIRST_CODE_BONUS_COINS


async def test_settle_is_a_no_op_for_an_unreferred_user(
    database: PostgreSQLAdapter,
) -> None:
    now = datetime.now(UTC)
    service = _service(database, now)
    invitee = await new_user_id(database)
    await insert_redeemed_code(database, invitee, now)

    await service.settle(invitee)  # must not raise
