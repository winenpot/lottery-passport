"""Achievements (AC1 MVP slice): ``GET /me/achievements`` (unlocked only)
and ``GET /achievements`` (every active row + progress, B44/W13).

Plain reads, no wallet lock -- unlocking (and paying) happens inside the
triggering write's own transaction (``app/application/challenges.py``'s
``ChallengeService.claim`` for a ``DAILY_CHECKIN`` claim today). This
service only reads what has already happened; ``list_progress`` reuses
the exact same streak primitive ``ChallengeService``/``MeService`` do
(``ChallengesReader.checkin_days`` + ``app.domain.periods.current_streak``)
rather than recomputing it a third way.
"""

from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.application.challenges import ChallengesReader
from app.domain.achievements import (
    Achievement,
    AchievementFact,
    AchievementProgress,
    UnlockedAchievement,
)
from app.domain.challenges import ChallengeKind
from app.domain.periods import current_streak, tehran_date


class AchievementsReader(Protocol):
    """Implemented by ``PostgreSQLAchievementsReader``."""

    async def list_active(self) -> list[Achievement]: ...

    async def list_unlocked(self, user_id: UUID) -> list[UnlockedAchievement]: ...


class AchievementService:
    def __init__(
        self,
        reader: AchievementsReader,
        challenges: ChallengesReader,
        clock: Clock,
        zone: ZoneInfo,
    ) -> None:
        self._reader = reader
        self._challenges = challenges
        self._clock = clock
        self._zone = zone

    async def list_unlocked(self, user_id: UUID) -> list[UnlockedAchievement]:
        return await self._reader.list_unlocked(user_id)

    async def list_progress(self, user_id: UUID) -> list[AchievementProgress]:
        active = await self._reader.list_active()
        unlocked_at_by_id = {
            u.id: u.unlocked_at for u in await self._reader.list_unlocked(user_id)
        }
        streak: int | None = None  # computed at most once, only if needed
        progress = []
        for achievement in active:
            have = 0
            if achievement.fact is AchievementFact.CHECKIN_STREAK:
                if streak is None:
                    streak = await self._checkin_streak_days(user_id)
                have = streak
            progress.append(
                AchievementProgress(
                    id=achievement.id,
                    fact=achievement.fact,
                    threshold=achievement.threshold,
                    reward_coins=achievement.reward_coins,
                    have=have,
                    unlocked=achievement.id in unlocked_at_by_id,
                    unlocked_at=unlocked_at_by_id.get(achievement.id),
                )
            )
        return progress

    async def _checkin_streak_days(self, user_id: UUID) -> int:
        """Same primitive as ``MeService._checkin_streak_days`` -- not
        shared through a port since both are a handful of lines reading
        the same two already-shared functions."""
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
