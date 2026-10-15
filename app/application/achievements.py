"""Achievements (AC1 MVP slice): ``GET /me/achievements``.

Plain read, no wallet lock -- unlocking (and paying) happens inside the
triggering write's own transaction (``app/application/challenges.py``'s
``ChallengeService.claim`` for a ``DAILY_CHECKIN`` claim today). This
service only lists what a player has already unlocked.
"""

from typing import Protocol
from uuid import UUID

from app.domain.achievements import UnlockedAchievement


class AchievementsReader(Protocol):
    """Implemented by ``PostgreSQLAchievementsReader``."""

    async def list_unlocked(self, user_id: UUID) -> list[UnlockedAchievement]: ...


class AchievementService:
    def __init__(self, reader: AchievementsReader) -> None:
        self._reader = reader

    async def list_unlocked(self, user_id: UUID) -> list[UnlockedAchievement]:
        return await self._reader.list_unlocked(user_id)
