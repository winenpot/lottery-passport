"""TeamService (P1.5) against real PostgreSQL: unlock, lock, switch.

Codes are inserted directly into ``redemption_codes`` (unclaimed codes with
no batch) rather than run through the full redemption flow: all
``TeamsInTransaction``/``TeamsReader`` need is the lifetime count per
flavor, which is exactly what ``RedemptionService`` itself also reads
(app/application/redemption_codes.py).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.application.teams import TeamService
from app.application.unit_of_work import UnitOfWork
from app.core.config import Settings
from app.domain.passports import CityCode
from app.domain.teams import (
    TEAM_LOCK,
    TeamChangeError,
    TeamChangeRefusal,
    TeamMembership,
)
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import RedemptionCodeModel
from app.infrastructure.postgres.repositories import (
    PostgreSQLTeamsReader,
    PostgreSQLUserRepository,
)
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


def make_service(database: PostgreSQLAdapter, now: datetime) -> TeamService:
    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory)

    return TeamService(
        reader=PostgreSQLTeamsReader(database.session_factory),
        unit_of_work=unit_of_work,
        clock=FixedClock(now),
    )


async def create_user(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"+989{uuid4().int % 10**9:09d}", datetime.now(UTC))
    return user.id


async def add_redeemed_codes(
    database: PostgreSQLAdapter, user_id: UUID, flavor: CityCode, count: int
) -> None:
    async with database.session_factory() as session, session.begin():
        for _ in range(count):
            await session.execute(
                insert(RedemptionCodeModel).values(
                    id=uuid4(),
                    city=flavor.value,
                    code_hash=f"it-team-{uuid4().hex}",
                    created_at=datetime.now(UTC),
                    redeemed_at=datetime.now(UTC),
                    redeemed_by_user_id=user_id,
                )
            )


async def test_four_codes_refuse_the_join_five_succeed(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await create_user(database)
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    service = make_service(database, now)
    await add_redeemed_codes(database, user_id, CityCode.TOKYO, 4)

    with pytest.raises(TeamChangeError) as caught:
        await service.change(user_id, CityCode.TOKYO)
    assert caught.value.reason is TeamChangeRefusal.FLAVOR_NOT_UNLOCKED
    assert (caught.value.required, caught.value.have) == (5, 4)

    await add_redeemed_codes(database, user_id, CityCode.TOKYO, 1)
    membership = await service.change(user_id, CityCode.TOKYO)

    assert (membership.flavor, membership.switch_no) == (CityCode.TOKYO, 0)
    status = await service.status(user_id)
    assert status.team is not None and status.team.flavor is CityCode.TOKYO


async def test_switch_is_locked_then_opens_after_thirty_days(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await create_user(database)
    joined_at = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    await add_redeemed_codes(database, user_id, CityCode.TOKYO, 5)
    await add_redeemed_codes(database, user_id, CityCode.MOSCOW, 10)
    await make_service(database, joined_at).change(user_id, CityCode.TOKYO)

    almost_there = joined_at + TEAM_LOCK - timedelta(days=1)
    with pytest.raises(TeamChangeError) as caught:
        await make_service(database, almost_there).change(user_id, CityCode.MOSCOW)
    assert caught.value.reason is TeamChangeRefusal.TEAM_LOCKED
    assert caught.value.allowed_at == joined_at + TEAM_LOCK

    unlocked = joined_at + TEAM_LOCK
    switched = await make_service(database, unlocked).change(user_id, CityCode.MOSCOW)
    assert (switched.flavor, switched.switch_no) == (CityCode.MOSCOW, 1)


async def test_the_unique_switch_number_rejects_a_duplicate_join(
    database: PostgreSQLAdapter,
) -> None:
    """Defense in depth (the wallet lock is the real guard): the race guard
    constraint itself refuses two switch_no=0 rows for one user."""
    user_id = await create_user(database)
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        await uow.ledger.lock_wallet(user_id, now)
        await uow.teams.add(TeamMembership(user_id, CityCode.TOKYO, 0, now))
        await uow.commit()

    with pytest.raises(IntegrityError, match="uq_team_memberships_user_switch"):
        async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
            await uow.ledger.lock_wallet(user_id, now)
            await uow.teams.add(TeamMembership(user_id, CityCode.MOSCOW, 0, now))
            await uow.commit()
