"""MiniGameService (G1.4) against real PostgreSQL: start/finish end to end.

Codes/runs never pay coins directly (rewards flow only through C1
challenges), so there is nothing to assert about the wallet balance here
-- this proves the plumbing itself: one open run per user is a real
database guarantee, an expired run is refused, and finishing twice is
refused (not silently re-scored).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.application.mini_games import (
    MiniGameRunError,
    MiniGameRunRefusal,
    MiniGameService,
    MiniGameStartError,
    MiniGameStartRefusal,
)
from app.application.unit_of_work import UnitOfWork
from app.core.config import Settings
from app.domain.mini_games import RUN_TTL, MiniGameId
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork

TEHRAN = ZoneInfo("Asia/Tehran")


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


def make_service(database: PostgreSQLAdapter, now: datetime) -> MiniGameService:
    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory)

    return MiniGameService(
        unit_of_work=unit_of_work, clock=FixedClock(now), zone=TEHRAN
    )


async def create_user(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"+989{uuid4().int % 10**9:09d}", datetime.now(UTC))
    return user.id


async def test_a_second_run_cannot_open_while_one_is_open(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await create_user(database)
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    service = make_service(database, now)

    await service.start_run(user_id, MiniGameId.TAP_REFLEX)

    with pytest.raises(MiniGameStartError) as caught:
        await service.start_run(user_id, MiniGameId.TAP_REFLEX)
    assert caught.value.reason is MiniGameStartRefusal.ALREADY_OPEN


async def test_a_plausible_finish_is_accepted_end_to_end(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await create_user(database)
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    started = await make_service(database, now).start_run(
        user_id, MiniGameId.TAP_REFLEX
    )

    reactions = [250, 300, 275, 260, 280]
    assert len(reactions) == len(started.round_delays_ms)
    finished_at = now + timedelta(
        milliseconds=sum(started.round_delays_ms) + sum(reactions) + 100
    )

    result = await make_service(database, finished_at).finish_run(
        user_id, started.run_id, reactions
    )

    assert result.accepted is True
    assert result.reason is None


async def test_finishing_after_expiry_is_refused(database: PostgreSQLAdapter) -> None:
    user_id = await create_user(database)
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    started = await make_service(database, now).start_run(
        user_id, MiniGameId.TAP_REFLEX
    )

    too_late = now + RUN_TTL + timedelta(seconds=1)
    with pytest.raises(MiniGameRunError) as caught:
        await make_service(database, too_late).finish_run(
            user_id, started.run_id, [250] * len(started.round_delays_ms)
        )
    assert caught.value.reason is MiniGameRunRefusal.EXPIRED


async def test_finishing_twice_is_refused_not_rescored(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await create_user(database)
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    started = await make_service(database, now).start_run(
        user_id, MiniGameId.TAP_REFLEX
    )
    reactions = [250, 300, 275, 260, 280]
    finished_at = now + timedelta(
        milliseconds=sum(started.round_delays_ms) + sum(reactions) + 100
    )
    await make_service(database, finished_at).finish_run(
        user_id, started.run_id, reactions
    )

    with pytest.raises(MiniGameRunError) as caught:
        await make_service(database, finished_at).finish_run(
            user_id, started.run_id, reactions
        )
    assert caught.value.reason is MiniGameRunRefusal.ALREADY_FINISHED


async def test_someone_elses_run_cannot_be_finished(
    database: PostgreSQLAdapter,
) -> None:
    owner_id = await create_user(database)
    stranger_id = await create_user(database)
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    started = await make_service(database, now).start_run(
        owner_id, MiniGameId.TAP_REFLEX
    )

    with pytest.raises(MiniGameRunError) as caught:
        await make_service(database, now).finish_run(
            stranger_id, started.run_id, [250] * len(started.round_delays_ms)
        )
    assert caught.value.reason is MiniGameRunRefusal.NOT_OWNER
