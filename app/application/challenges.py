"""Challenges (C1, B17): ``GET /challenges``, ``POST /challenges/<id>/claim``.

Progress is computed from existing data (no counter columns to keep in
sync): ``TEAM_CHOICE`` reads ``uow.teams``/the plain team reader,
``DISTINCT_FLAVORS`` reads ``redemption_codes`` since the period start,
``DAILY_CHECKIN`` is always completed (the claim itself is the data).
``claim`` locks the player's wallet row first, the same per-user
serialization ``RedemptionService`` and ``TeamService`` use, so the
progress check and the ledger write it is based on cannot race against
another claim or a redemption from the same player.

A ``DAILY_CHECKIN`` claim additionally computes the player's current
streak (``app.domain.periods.current_streak``, fed by its own claim
history) and, in the SAME transaction, unlocks any ``checkin_streak``
achievement whose threshold it has just crossed -- paying through the
ledger if the achievement carries a coin reward. See
``app/domain/achievements.py`` for why this is a one-time-per-player
unlock, not a repeatable one (breaking and rebuilding a streak cannot
re-earn an already-unlocked milestone).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.application.teams import TeamsReader
from app.application.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.domain.achievements import AchievementFact
from app.domain.challenges import (
    ONCE_PERIOD_KEY,
    Challenge,
    ChallengeClaimError,
    ChallengeClaimRefusal,
    ChallengeKind,
    ChallengePeriod,
)
from app.domain.ledger import LedgerReason, NewLedgerEntry
from app.domain.periods import (
    current_streak,
    tehran_date,
    tehran_day_key,
    tehran_day_start,
    tehran_month_key,
    tehran_month_start,
    tehran_week_key,
    tehran_week_start,
)


class ChallengesReader(Protocol):
    """Plain read side (no wallet lock): implemented by
    ``PostgreSQLChallengesReader``, shares its queries with the unit of
    work's ``challenges`` port."""

    async def list_active(self) -> list[Challenge]: ...

    async def distinct_flavors_since(self, user_id: UUID, since: datetime) -> int: ...

    async def checkin_days(self, challenge_id: str, user_id: UUID) -> set[date]: ...

    async def has_claimed(
        self, challenge_id: str, user_id: UUID, period_key: str
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ChallengeProgress:
    id: str
    kind: ChallengeKind
    period: ChallengePeriod
    target: int
    have: int
    reward_coins: int
    completed: bool
    claimed: bool
    streak: int | None = None  # DAILY_CHECKIN only; None for every other kind


@dataclass(frozen=True, slots=True)
class AchievementUnlock:
    id: str
    reward_coins: int


@dataclass(frozen=True, slots=True)
class ChallengeClaimResult:
    id: str
    coins_awarded: int
    coin_balance: int
    streak: int | None = None
    achievements_unlocked: Sequence[AchievementUnlock] = field(default_factory=list)


def _period_key_and_start(
    period: ChallengePeriod, now: datetime, zone: ZoneInfo
) -> tuple[str, datetime | None]:
    if period is ChallengePeriod.ONCE:
        return ONCE_PERIOD_KEY, None
    if period is ChallengePeriod.DAY:
        return tehran_day_key(now, zone), tehran_day_start(now, zone)
    if period is ChallengePeriod.WEEK:
        return tehran_week_key(now, zone), tehran_week_start(now, zone)
    return tehran_month_key(now, zone), tehran_month_start(now, zone)


class ChallengeService:
    def __init__(
        self,
        reader: ChallengesReader,
        teams: TeamsReader,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        zone: ZoneInfo,
    ) -> None:
        self._reader = reader
        self._teams = teams
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._zone = zone

    async def _progress(
        self, challenge: Challenge, user_id: UUID, period_start: datetime | None
    ) -> int:
        if challenge.kind is ChallengeKind.TEAM_CHOICE:
            return 1 if await self._teams.current(user_id) is not None else 0
        if challenge.kind is ChallengeKind.DAILY_CHECKIN:
            return 1
        assert period_start is not None  # every other kind has a period start
        return await self._reader.distinct_flavors_since(user_id, period_start)

    async def claim(self, user_id: UUID, challenge_id: str) -> ChallengeClaimResult:
        """Raises ``ChallengeClaimError``."""
        now = self._clock.now()
        async with self._unit_of_work() as uow:
            balance = await uow.ledger.lock_wallet(user_id, now)
            challenge = await uow.challenges.get(challenge_id)
            if challenge is None:
                raise ChallengeClaimError(ChallengeClaimRefusal.UNKNOWN)
            period_key, period_start = _period_key_and_start(
                challenge.period, now, self._zone
            )
            if await uow.challenges.has_claimed(challenge.id, user_id, period_key):
                raise ChallengeClaimError(ChallengeClaimRefusal.ALREADY_CLAIMED)
            have = await self._progress_in_transaction(
                uow, challenge, user_id, period_start
            )
            if have < challenge.target:
                raise ChallengeClaimError(
                    ChallengeClaimRefusal.NOT_UNLOCKED,
                    required=challenge.target,
                    have=have,
                )
            await uow.challenges.claim(challenge.id, user_id, period_key, now)
            if challenge.reward_coins > 0:
                balance = await uow.ledger.record(
                    NewLedgerEntry(
                        user_id=user_id,
                        amount=challenge.reward_coins,
                        reason=LedgerReason.CHALLENGE_REWARD,
                        idempotency_key=f"challenge:{challenge.id}:{period_key}:{user_id}",
                        created_at=now,
                        source_id=challenge.id,
                    )
                )
            streak = None
            unlocked: Sequence[AchievementUnlock] = []
            if challenge.kind is ChallengeKind.DAILY_CHECKIN:
                streak = await self._streak_in_transaction(
                    uow, challenge.id, user_id, now
                )
                balance, unlocked = await self._unlock_streak_achievements(
                    uow, user_id, streak, now, balance
                )
            await uow.commit()
        return ChallengeClaimResult(
            id=challenge.id,
            coins_awarded=challenge.reward_coins,
            coin_balance=balance,
            streak=streak,
            achievements_unlocked=unlocked,
        )

    async def _progress_in_transaction(
        self,
        uow: UnitOfWork,
        challenge: Challenge,
        user_id: UUID,
        period_start: datetime | None,
    ) -> int:
        if challenge.kind is ChallengeKind.TEAM_CHOICE:
            return 1 if await uow.teams.current(user_id) is not None else 0
        if challenge.kind is ChallengeKind.DAILY_CHECKIN:
            return 1
        assert period_start is not None
        return await uow.challenges.distinct_flavors_since(user_id, period_start)

    async def _streak_in_transaction(
        self, uow: UnitOfWork, challenge_id: str, user_id: UUID, now: datetime
    ) -> int:
        """Called AFTER ``uow.challenges.claim`` for this same transaction,
        so today's just-inserted claim is already included."""
        dates = await uow.challenges.checkin_days(challenge_id, user_id)
        return current_streak(dates, tehran_date(now, self._zone))

    async def _unlock_streak_achievements(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        streak: int,
        now: datetime,
        balance: int,
    ) -> tuple[int, Sequence[AchievementUnlock]]:
        unlocked: list[AchievementUnlock] = []
        achievements = await uow.achievements.list_active_by_fact(
            AchievementFact.CHECKIN_STREAK
        )
        for achievement in achievements:
            if streak < achievement.threshold:
                continue
            if await uow.achievements.already_unlocked(achievement.id, user_id):
                continue  # one-time per player -- a rebuilt streak cannot re-pay
            await uow.achievements.unlock(achievement.id, user_id, now)
            if achievement.reward_coins > 0:
                balance = await uow.ledger.record(
                    NewLedgerEntry(
                        user_id=user_id,
                        amount=achievement.reward_coins,
                        reason=LedgerReason.ACHIEVEMENT_REWARD,
                        idempotency_key=f"achievement:{achievement.id}:{user_id}",
                        created_at=now,
                        source_id=achievement.id,
                    )
                )
            unlocked.append(
                AchievementUnlock(
                    id=achievement.id, reward_coins=achievement.reward_coins
                )
            )
        return balance, unlocked

    async def list(self, user_id: UUID) -> list[ChallengeProgress]:
        """Defined last in this class -- a bare ``list[...]`` annotation in
        any method defined AFTER this one would resolve to this method
        itself, not the builtin, since Python binds ``list`` as a class
        attribute the moment this ``async def`` executes."""
        now = self._clock.now()
        progress = []
        for challenge in await self._reader.list_active():
            period_key, period_start = _period_key_and_start(
                challenge.period, now, self._zone
            )
            have = await self._progress(challenge, user_id, period_start)
            claimed = await self._reader.has_claimed(challenge.id, user_id, period_key)
            streak = None
            if challenge.kind is ChallengeKind.DAILY_CHECKIN:
                dates = await self._reader.checkin_days(challenge.id, user_id)
                streak = current_streak(dates, tehran_date(now, self._zone))
            progress.append(
                ChallengeProgress(
                    id=challenge.id,
                    kind=challenge.kind,
                    period=challenge.period,
                    target=challenge.target,
                    have=have,
                    reward_coins=challenge.reward_coins,
                    completed=have >= challenge.target,
                    claimed=claimed,
                    streak=streak,
                )
            )
        return progress
