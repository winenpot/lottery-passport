"""``SqlGames`` (G1.3) against real PostgreSQL: the unit-of-work adapter,
exercised directly (no ``GameService`` exists yet -- G1.4). Each test opens
its own run inside one unit of work and commits, same shape as
``test_economy_core_db.py``'s direct-adapter tests.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from random import Random
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.domain.games import GameId, GameRunStatus, open_run
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork


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
    phone = f"+989{uuid4().int % 10**9:09d}"
    return (await users.create(phone, datetime.now(UTC))).id


async def test_open_run_is_readable_as_the_users_open_run(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    now = datetime.now(UTC)
    new_run = open_run(user_id, GameId.TAP_REFLEX, now, Random(1))

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        await uow.games.open(new_run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        found = await uow.games.get_open(user_id, GameId.TAP_REFLEX)
        by_id = await uow.games.get(new_run.id)
    assert found is not None
    assert found.id == new_run.id
    assert found.round_delays_ms == new_run.round_delays_ms
    assert found.status is GameRunStatus.OPEN
    assert by_id == found


async def test_finishing_a_run_clears_it_from_get_open(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    now = datetime.now(UTC)
    new_run = open_run(user_id, GameId.TAP_REFLEX, now, Random(2))

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        await uow.games.open(new_run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        await uow.games.finish(
            new_run.id, GameRunStatus.ACCEPTED, now + timedelta(seconds=30), 275.0
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        assert await uow.games.get_open(user_id, GameId.TAP_REFLEX) is None
        finished = await uow.games.get(new_run.id)
    assert finished is not None
    assert finished.status is GameRunStatus.ACCEPTED


async def test_count_rejected_since_counts_only_rejected_runs_in_the_window(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    now = datetime.now(UTC)
    since = now - timedelta(hours=1)

    async def run_with_outcome(status: GameRunStatus, finished_at: datetime) -> None:
        new_run = open_run(user_id, GameId.TAP_REFLEX, now, Random())
        async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
            await uow.games.open(new_run)
            await uow.commit()
        async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
            await uow.games.finish(new_run.id, status, finished_at, 300.0)
            await uow.commit()

    await run_with_outcome(GameRunStatus.REJECTED, now)
    await run_with_outcome(GameRunStatus.REJECTED, now)
    await run_with_outcome(GameRunStatus.ACCEPTED, now)  # not rejected
    # outside the window -- too old to count
    await run_with_outcome(GameRunStatus.REJECTED, since - timedelta(hours=1))

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        count = await uow.games.count_rejected_since(user_id, since)
    assert count == 2
