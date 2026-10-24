"""LeaderboardService (L1): period math, caching and the "me" shape --
against a fake reader. The ranking/tie-break SQL itself is tested in
tests/integration/test_leaderboards_db.py (it is the part a fake cannot
honestly stand in for).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.application.leaderboards import (
    LeaderboardPeriod,
    LeaderboardRow,
    LeaderboardService,
    UnknownMiniGameBoard,
)
from app.domain.leaderboards import MiniGameBoard
from app.domain.mini_games import MiniGameId
from app.domain.periods import tehran_day_start, tehran_week_start

ZONE = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)  # a Thursday


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


@dataclass
class FakeReader:
    rows: list[LeaderboardRow] = field(default_factory=list)
    rank_by_user: dict[UUID, tuple[int, float]] = field(default_factory=dict)
    top_calls: int = 0
    rank_of_calls: int = 0

    async def top(
        self, board: MiniGameBoard, since: datetime | None, limit: int
    ) -> list[LeaderboardRow]:
        self.top_calls += 1
        return self.rows[:limit]

    async def rank_of(
        self, board: MiniGameBoard, since: datetime | None, user_id: UUID
    ) -> tuple[int, float] | None:
        self.rank_of_calls += 1
        return self.rank_by_user.get(user_id)


def build(
    reader: FakeReader | None = None, now: datetime | None = None
) -> tuple[LeaderboardService, FakeReader, FakeClock]:
    reader = reader if reader is not None else FakeReader()
    clock = FakeClock(now or NOW)
    service = LeaderboardService(reader=reader, clock=clock, zone=ZONE)
    return service, reader, clock


async def test_unknown_mini_game_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # MiniGameId has exactly one member today, so there is no real unknown
    # id to construct; this simulates the only way the registry and the
    # enum could ever drift -- a MiniGameId shipped ahead of its board.
    monkeypatch.setattr("app.application.leaderboards.MINI_GAME_BOARDS", {})
    service, _, _ = build()

    with pytest.raises(UnknownMiniGameBoard):
        await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, uuid4())


async def test_week_period_windows_the_tehran_campaign_week() -> None:
    user = uuid4()
    service, _, _ = build()

    board = await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)

    assert board.resets_at == tehran_week_start(NOW, ZONE) + timedelta(days=7)


async def test_today_period_resets_at_next_tehran_midnight() -> None:
    user = uuid4()
    service, _, _ = build()

    board = await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.TODAY, user)

    assert board.resets_at == tehran_day_start(NOW, ZONE) + timedelta(days=1)


async def test_all_time_period_never_resets() -> None:
    user = uuid4()
    service, _, _ = build()

    board = await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.ALL, user)

    assert board.resets_at is None


async def test_entries_come_straight_off_the_reader() -> None:
    user = uuid4()
    other = uuid4()
    reader = FakeReader(
        rows=[
            LeaderboardRow(
                rank=1,
                user_id=other,
                nickname="NEXUS",
                avatar_id="avatar-2",
                score=182.0,
            )
        ]
    )
    service, _, _ = build(reader)

    board = await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)

    assert len(board.entries) == 1
    assert board.entries[0].user_id == other
    assert board.entries[0].nickname == "NEXUS"
    assert board.entries[0].score == 182.0


async def test_me_is_none_without_a_qualifying_run() -> None:
    user = uuid4()
    service, _, _ = build()

    board = await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)

    assert board.me.rank is None
    assert board.me.score is None


async def test_me_reflects_the_readers_rank_of() -> None:
    user = uuid4()
    reader = FakeReader(rank_by_user={user: (6, 214.0)})
    service, _, _ = build(reader)

    board = await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)

    assert board.me.rank == 6
    assert board.me.score == 214.0


async def test_top_is_cached_but_me_is_recomputed_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic = [1000.0]
    monkeypatch.setattr(
        "app.application.leaderboards.time.monotonic", lambda: monotonic[0]
    )
    reader = FakeReader()
    service, reader, _ = build(reader)
    user = uuid4()

    await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)
    await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)

    assert reader.top_calls == 1  # second call served from cache
    assert reader.rank_of_calls == 2  # me is never cached

    monotonic[0] += 61.0  # past the 60s TTL
    await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)

    assert reader.top_calls == 2  # cache expired, recomputed


async def test_cache_is_keyed_per_period_not_shared() -> None:
    reader = FakeReader()
    service, reader, _ = build(reader)
    user = uuid4()

    await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.WEEK, user)
    await service.get(MiniGameId.TAP_REFLEX, LeaderboardPeriod.TODAY, user)

    assert reader.top_calls == 2  # different windows, each computed once
