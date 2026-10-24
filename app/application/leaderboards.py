"""``GET /leaderboards/mini-games/{mini_game_id}?period=today|week|all`` (L1),
finalizing the shape ``docs/API_CONTRACT.md`` already sketched as planned.

Each player's single best run in the period; ties go to whoever set it
first -- the SQL reader (``app.infrastructure.postgres.repositories
.PostgreSQLLeaderboardReader``) does the ranking and the tie-break in one
round trip, this module only shapes the result and owns the cache. Top 50
plus the caller's own rank/score (``me``) even outside the top 50, the same
"show mine even if not in the headline list" shape achievements/challenges
already use.

The top-N list is cached in-process for up to 60 seconds
(``docs/ARCHITECTURE.md``'s "Cached for 30-60 seconds... leaderboards": a
correct answer up to a minute stale, not live-recomputed, is fine for a
lounge TV screen and keeps a burst of concurrent reads to one real query).
``me`` is never cached: it is specific to the caller, one more indexed
query is cheap, and serving a stale ``me`` to the wrong player would not be
a cost worth avoiding a query for.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.domain.leaderboards import MINI_GAME_BOARDS, MiniGameBoard
from app.domain.mini_games import MiniGameId
from app.domain.periods import tehran_day_start, tehran_week_start

__all__ = [
    "Leaderboard",
    "LeaderboardEntry",
    "LeaderboardPeriod",
    "LeaderboardReader",
    "LeaderboardRow",
    "LeaderboardSelf",
    "LeaderboardService",
    "TOP_N",
    "UnknownMiniGameBoard",
]

TOP_N = 50
_CACHE_TTL_SECONDS = 60.0


class LeaderboardPeriod(StrEnum):
    TODAY = "today"
    WEEK = "week"
    ALL = "all"


class UnknownMiniGameBoard(Exception):
    """Raised for a ``mini_game_id`` with no ``app.domain.leaderboards``
    entry (L1 404) -- not reachable today (``MiniGameId`` has exactly one
    member, with exactly one board), but a future mini-game could ship its
    runs endpoint before its board definition, same as a route existing
    ahead of its feature flag elsewhere in this codebase."""


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    """One ranked player, straight off the reader -- the same shape
    ``top()`` and ``rank_of()`` agree on."""

    rank: int
    user_id: UUID
    nickname: str | None
    avatar_id: str | None
    score: float


class LeaderboardReader(Protocol):
    async def top(
        self, board: MiniGameBoard, since: datetime | None, limit: int
    ) -> list[LeaderboardRow]:
        """Each player's best run in the window, best-first, ties broken by
        whoever set it first."""
        ...

    async def rank_of(
        self, board: MiniGameBoard, since: datetime | None, user_id: UUID
    ) -> tuple[int, float] | None:
        """``(rank, score)`` of ``user_id``'s best run in the window,
        computed over the same ranking ``top()`` uses, so a player's
        reported rank always matches where they would land in the full
        list. ``None`` if they have no qualifying run yet."""
        ...


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    rank: int
    user_id: UUID
    nickname: str | None
    avatar_id: str | None
    score: float


@dataclass(frozen=True, slots=True)
class LeaderboardSelf:
    rank: int | None
    score: float | None


@dataclass(frozen=True, slots=True)
class Leaderboard:
    mini_game_id: MiniGameId
    period: LeaderboardPeriod
    resets_at: datetime | None
    updated_at: datetime
    entries: list[LeaderboardEntry]
    me: LeaderboardSelf


@dataclass(frozen=True, slots=True)
class _CachedTop:
    entries: list[LeaderboardEntry]
    updated_at: datetime
    expires_at: float  # a time.monotonic() instant, never wall-clock time


class LeaderboardService:
    def __init__(
        self,
        reader: LeaderboardReader,
        clock: Clock,
        zone: ZoneInfo,
        top_n: int = TOP_N,
    ) -> None:
        self._reader = reader
        self._clock = clock
        self._zone = zone
        self._top_n = top_n
        self._cache: dict[tuple[MiniGameId, LeaderboardPeriod], _CachedTop] = {}

    async def get(
        self, mini_game_id: MiniGameId, period: LeaderboardPeriod, user_id: UUID
    ) -> Leaderboard:
        board = MINI_GAME_BOARDS.get(mini_game_id)
        if board is None:
            raise UnknownMiniGameBoard(mini_game_id.value)
        now = self._clock.now()
        since = self._window_start(period, now)
        cached = await self._cached_top(board, period, since, now)
        me = await self._me(board, since, user_id)
        return Leaderboard(
            mini_game_id=mini_game_id,
            period=period,
            resets_at=self._resets_at(period, now),
            updated_at=cached.updated_at,
            entries=cached.entries,
            me=me,
        )

    def _window_start(
        self, period: LeaderboardPeriod, now: datetime
    ) -> datetime | None:
        if period is LeaderboardPeriod.TODAY:
            return tehran_day_start(now, self._zone)
        if period is LeaderboardPeriod.WEEK:
            return tehran_week_start(now, self._zone)
        return None

    def _resets_at(self, period: LeaderboardPeriod, now: datetime) -> datetime | None:
        if period is LeaderboardPeriod.TODAY:
            return tehran_day_start(now, self._zone) + timedelta(days=1)
        if period is LeaderboardPeriod.WEEK:
            return tehran_week_start(now, self._zone) + timedelta(days=7)
        return None

    async def _cached_top(
        self,
        board: MiniGameBoard,
        period: LeaderboardPeriod,
        since: datetime | None,
        now: datetime,
    ) -> _CachedTop:
        key = (board.mini_game_id, period)
        cached = self._cache.get(key)
        monotonic_now = time.monotonic()
        if cached is not None and monotonic_now < cached.expires_at:
            return cached
        rows = await self._reader.top(board, since, self._top_n)
        fresh = _CachedTop(
            entries=[
                LeaderboardEntry(
                    rank=row.rank,
                    user_id=row.user_id,
                    nickname=row.nickname,
                    avatar_id=row.avatar_id,
                    score=row.score,
                )
                for row in rows
            ],
            updated_at=now,
            expires_at=monotonic_now + _CACHE_TTL_SECONDS,
        )
        self._cache[key] = fresh
        return fresh

    async def _me(
        self, board: MiniGameBoard, since: datetime | None, user_id: UUID
    ) -> LeaderboardSelf:
        found = await self._reader.rank_of(board, since, user_id)
        if found is None:
            return LeaderboardSelf(rank=None, score=None)
        rank, score = found
        return LeaderboardSelf(rank=rank, score=score)
