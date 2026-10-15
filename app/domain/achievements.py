"""Achievements (AC1 MVP slice): auto-unlock on a fact crossing a threshold.

An ``achievement`` row (admin-tunable, starts empty, same pattern as
``challenges``/avatars/reward_rules) says WHAT fact must cross WHAT
threshold and HOW MUCH it pays the first time it does. Unlocking is
automatic: there is no claim step. The unlock itself is the reward, paid
in the same transaction as the triggering write, same principle as the
first-code bonus and ``flavor_unlocked`` -- "easily claimable" by never
needing a claim at all.

``fact`` is a closed set, same discipline as ``app.domain.challenges``'s
``ChallengeKind``:

* ``CHECKIN_STREAK`` -- the player's current consecutive daily-check-in
  streak (``app.domain.periods.current_streak``, fed by the
  ``DAILY_CHECKIN`` challenge's own claims). Shipped now.

Not shipped: a full generic ``FactPublisher`` port with other fact sources
(a game high score, a lounge-visit count...) -- AC1's own spec pass (8-12
achievements, Ashkan's badge art, Mehdi's approved list) has not happened
yet, so this ships the unlock-and-pay MECHANISM only, wired to the one
fact that already exists. No badge/image catalogue yet either; an
unlocked achievement is ``{id, unlocked_at}`` with no artwork until AC1's
spec pass supplies one -- same "shape now, assets later" pattern as
avatars' ``locked``/``unlock_rule`` columns.

``user_achievements`` is UNIQUE (achievement_id, user_id): the only-once
guard, the same shape as ``challenge_claims``.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AchievementFact(StrEnum):
    CHECKIN_STREAK = "checkin_streak"


@dataclass(frozen=True, slots=True)
class Achievement:
    id: str
    fact: AchievementFact
    threshold: int
    reward_coins: int
    active: bool


@dataclass(frozen=True, slots=True)
class UnlockedAchievement:
    id: str
    threshold: int
    reward_coins: int
    unlocked_at: datetime
