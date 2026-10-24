"""PostgreSQLLeaderboardReader (L1) against real PostgreSQL: the part a
fake reader cannot honestly stand in for -- the ranking and the
"ties go to whoever set it first" tie-break, both done in SQL.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, update

from app.core.config import Settings
from app.domain.leaderboards import BestScore, MiniGameBoard
from app.domain.mini_games import MiniGameId
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import MiniGameRunModel, UserModel
from app.infrastructure.postgres.repositories import (
    PostgreSQLLeaderboardReader,
    PostgreSQLUserRepository,
)

BOARD = MiniGameBoard(mini_game_id=MiniGameId.TAP_REFLEX, best=BestScore.LOWEST)


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


@pytest.fixture(autouse=True)
async def _clear_mini_game_runs(database: PostgreSQLAdapter) -> None:
    # This module ranks ALL accepted runs for a mini-game -- unlike most
    # integration tests here, it cannot filter down to "this test's own
    # user_id" and ignore the rest, so leftover rows from an earlier test
    # in this file would silently inflate everyone's rank. Other
    # fixtures/tables are left alone (users accumulate harmlessly: each
    # gets its own random phone number).
    async with database.session_factory() as session, session.begin():
        await session.execute(delete(MiniGameRunModel))


def random_phone() -> str:
    while True:
        phone = f"+989{uuid4().int % 10**9:09d}"
        if not phone.startswith("+98969"):
            return phone


async def new_player(
    database: PostgreSQLAdapter, nickname: str, avatar_id: str | None = None
) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(random_phone(), datetime.now(UTC))
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(nickname=nickname, avatar_id=avatar_id)
        )
    return user.id


async def add_run(
    database: PostgreSQLAdapter,
    user_id: UUID,
    *,
    average_reaction_ms: float,
    finished_at: datetime,
    status: str = "accepted",
    mini_game_id: str = "tap_reflex",
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(MiniGameRunModel).values(
                id=uuid4(),
                user_id=user_id,
                mini_game_id=mini_game_id,
                round_delays_ms=[1000, 1500, 2000],
                issued_at=finished_at - timedelta(seconds=5),
                expires_at=finished_at + timedelta(minutes=2),
                finished_at=finished_at,
                status=status,
                average_reaction_ms=average_reaction_ms,
            )
        )


async def test_top_orders_lowest_first_one_row_per_player(
    database: PostgreSQLAdapter,
) -> None:
    reader = PostgreSQLLeaderboardReader(database.session_factory)
    now = datetime.now(UTC)
    fast = await new_player(database, "FAST")
    slow = await new_player(database, "SLOW")
    # fast's SECOND (worse) run must not create a second entry or win a tie.
    await add_run(database, fast, average_reaction_ms=300.0, finished_at=now)
    await add_run(
        database, fast, average_reaction_ms=250.0, finished_at=now - timedelta(hours=1)
    )
    await add_run(database, slow, average_reaction_ms=400.0, finished_at=now)

    top = await reader.top(BOARD, since=None, limit=50)

    assert [(row.user_id, row.score) for row in top] == [(fast, 250.0), (slow, 400.0)]
    assert [row.rank for row in top] == [1, 2]
    assert top[0].nickname == "FAST"


async def test_ties_go_to_whoever_set_the_score_first(
    database: PostgreSQLAdapter,
) -> None:
    reader = PostgreSQLLeaderboardReader(database.session_factory)
    now = datetime.now(UTC)
    earlier = await new_player(database, "EARLIER")
    later = await new_player(database, "LATER")
    await add_run(
        database,
        later,
        average_reaction_ms=250.0,
        finished_at=now - timedelta(minutes=5),
    )
    await add_run(
        database,
        earlier,
        average_reaction_ms=250.0,
        finished_at=now - timedelta(minutes=10),
    )

    top = await reader.top(BOARD, since=None, limit=50)

    assert [row.user_id for row in top] == [earlier, later]


async def test_rejected_and_other_mini_games_runs_do_not_count(
    database: PostgreSQLAdapter,
) -> None:
    reader = PostgreSQLLeaderboardReader(database.session_factory)
    now = datetime.now(UTC)
    player = await new_player(database, "SOLO")
    await add_run(
        database, player, average_reaction_ms=100.0, finished_at=now, status="rejected"
    )
    await add_run(database, player, average_reaction_ms=500.0, finished_at=now)

    top = await reader.top(BOARD, since=None, limit=50)

    assert [row.score for row in top] == [500.0]


async def test_since_excludes_runs_before_the_window(
    database: PostgreSQLAdapter,
) -> None:
    reader = PostgreSQLLeaderboardReader(database.session_factory)
    now = datetime.now(UTC)
    player = await new_player(database, "WINDOWED")
    await add_run(
        database, player, average_reaction_ms=200.0, finished_at=now - timedelta(days=2)
    )

    assert await reader.top(BOARD, since=now - timedelta(hours=1), limit=50) == []
    assert len(await reader.top(BOARD, since=None, limit=50)) == 1


async def test_rank_of_matches_where_top_would_place_them(
    database: PostgreSQLAdapter,
) -> None:
    reader = PostgreSQLLeaderboardReader(database.session_factory)
    now = datetime.now(UTC)
    first = await new_player(database, "FIRST")
    second = await new_player(database, "SECOND")
    third = await new_player(database, "THIRD")
    await add_run(database, first, average_reaction_ms=100.0, finished_at=now)
    await add_run(database, second, average_reaction_ms=200.0, finished_at=now)
    await add_run(database, third, average_reaction_ms=300.0, finished_at=now)

    assert await reader.rank_of(BOARD, since=None, user_id=second) == (2, 200.0)
    assert await reader.rank_of(BOARD, since=None, user_id=third) == (3, 300.0)


async def test_rank_of_is_none_without_a_qualifying_run(
    database: PostgreSQLAdapter,
) -> None:
    reader = PostgreSQLLeaderboardReader(database.session_factory)
    player = await new_player(database, "NOBODY")

    assert await reader.rank_of(BOARD, since=None, user_id=player) is None
