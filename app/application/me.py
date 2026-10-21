"""Composes the ``GET/PATCH /me`` response from several read ports (P1.6).

Thin on purpose: no business rule lives here, just gathering ``team`` and
``last_scanned_flavor`` next to the ``User`` the route already has.

``GET /me/stats`` (B48) follows the same shape: everything except the
check-in streak is one indexed-per-user SQL query (``StatsReader``, no
views -- see its docstring in ``app.infrastructure.postgres.repositories``
for why). The streak itself reuses ``ChallengesReader.checkin_days`` and
``app.domain.periods.current_streak`` rather than recomputing it, the same
primitives ``ChallengeService`` already uses for ``GET /challenges``.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.application.challenges import ChallengesReader
from app.application.teams import TeamsReader
from app.domain.challenges import ChallengeKind
from app.domain.passports import CityCode
from app.domain.periods import current_streak, tehran_date


class LastScanReader(Protocol):
    async def last_scanned_flavor(self, user_id: UUID) -> CityCode | None:
        """The flavor of the user's most recently redeemed code, or ``None``."""
        ...


@dataclass(frozen=True, slots=True)
class MeExtras:
    team: CityCode | None
    last_scanned_flavor: CityCode | None


@dataclass(frozen=True, slots=True)
class RawStats:
    """One row, straight off ``StatsReader.get_user_stats`` -- everything
    except the check-in streak, which needs ``ChallengesReader`` too."""

    scans_total: int
    flavors_discovered: int
    challenges_completed: int
    achievements_unlocked: int
    mini_game_runs_accepted: int
    mini_game_best_reaction_ms: float | None


@dataclass(frozen=True, slots=True)
class UserStats:
    scans_total: int
    flavors_discovered: int
    challenges_completed: int
    achievements_unlocked: int
    checkin_streak_days: int
    mini_game_runs_accepted: int
    mini_game_best_reaction_ms: float | None


class StatsReader(Protocol):
    async def get_user_stats(self, user_id: UUID) -> RawStats: ...


class MeService:
    def __init__(
        self,
        teams: TeamsReader,
        last_scans: LastScanReader,
        stats: StatsReader,
        challenges: ChallengesReader,
        clock: Clock,
        zone: ZoneInfo,
    ) -> None:
        self._teams = teams
        self._last_scans = last_scans
        self._stats = stats
        self._challenges = challenges
        self._clock = clock
        self._zone = zone

    async def extras(self, user_id: UUID) -> MeExtras:
        current = await self._teams.current(user_id)
        last = await self._last_scans.last_scanned_flavor(user_id)
        return MeExtras(
            team=current.flavor if current is not None else None,
            last_scanned_flavor=last,
        )

    async def stats(self, user_id: UUID) -> UserStats:
        raw = await self._stats.get_user_stats(user_id)
        streak = await self._checkin_streak_days(user_id)
        return UserStats(
            scans_total=raw.scans_total,
            flavors_discovered=raw.flavors_discovered,
            challenges_completed=raw.challenges_completed,
            achievements_unlocked=raw.achievements_unlocked,
            checkin_streak_days=streak,
            mini_game_runs_accepted=raw.mini_game_runs_accepted,
            mini_game_best_reaction_ms=raw.mini_game_best_reaction_ms,
        )

    async def _checkin_streak_days(self, user_id: UUID) -> int:
        daily_checkin = next(
            (
                challenge
                for challenge in await self._challenges.list_active()
                if challenge.kind is ChallengeKind.DAILY_CHECKIN
            ),
            None,
        )
        if daily_checkin is None:
            return 0
        dates = await self._challenges.checkin_days(daily_checkin.id, user_id)
        return current_streak(dates, tehran_date(self._clock.now(), self._zone))
