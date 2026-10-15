"""Migration 0017 (mini_game_runs) against real PostgreSQL.

Proves what only the database can: the ``mini_game_id``/``status`` CHECKs hold,
and the partial unique index makes a second OPEN run for the same user
fail -- the "one open run per user" guarantee does not rely solely on the
application's own check-before-insert.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import Settings
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import MiniGameRunModel
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


def random_phone() -> str:
    while True:
        phone = f"+989{uuid4().int % 10**9:09d}"
        if not phone.startswith("+98969"):
            return phone


async def new_user_id(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    return (await users.create(random_phone(), datetime.now(UTC))).id


async def add_run(
    database: PostgreSQLAdapter,
    user_id: UUID,
    *,
    mini_game_id: str = "tap_reflex",
    status: str = "open",
) -> None:
    now = datetime.now(UTC)
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(MiniGameRunModel).values(
                id=uuid4(),
                user_id=user_id,
                mini_game_id=mini_game_id,
                round_delays_ms=[1000, 1500, 2000],
                issued_at=now,
                expires_at=now + timedelta(minutes=2),
                status=status,
            )
        )


async def set_status(database: PostgreSQLAdapter, user_id: UUID, status: str) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(MiniGameRunModel)
            .where(MiniGameRunModel.user_id == user_id)
            .values(status=status)
        )


async def test_mini_game_id_check_rejects_an_unknown_mini_game(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    with pytest.raises(DBAPIError, match="ck_mini_game_runs_mini_game_id"):
        await add_run(database, user_id, mini_game_id="spin_the_wheel")


async def test_status_check_rejects_an_unknown_status(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    with pytest.raises(DBAPIError, match="ck_mini_game_runs_status"):
        await add_run(database, user_id, status="cancelled")


async def test_a_second_open_run_for_the_same_user_is_refused(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    await add_run(database, user_id, status="open")

    with pytest.raises(IntegrityError, match="uq_mini_game_runs_user_open"):
        await add_run(database, user_id, status="open")

    # A second run is fine once the first is no longer open.
    await set_status(database, user_id, "accepted")
    await add_run(database, user_id, status="open")
