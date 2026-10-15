"""Challenges (C1, B17): automatic rewards computed from what a player did.

A ``challenge`` row (admin-tunable, like avatars/venues/reward_rules — the
table starts empty, filled in ``/admin``) says WHAT must be true (``kind``,
``target``) and HOW MUCH it pays (``reward_coins``) on what cadence
(``period``). This module is the closed set of ``kind`` values this
backend knows how to check progress for: adding a row with an unknown kind
is a mistake, not a new feature (the engine has no plugin mechanism).

Shipped (both backed by data that already exists, no passive tracking):

* ``TEAM_CHOICE`` -- once: the player has ever joined a flavor team
  (``team_memberships``, P1). Sheet: "choose team" 30 coins once.
* ``DISTINCT_FLAVORS`` -- period: distinct flavors redeemed in the period
  (``redemption_codes``). Sheet: "discover 3 flavors" 100 coins monthly.
* ``DAILY_CHECKIN`` -- day, always completed once signed in: the claim
  itself IS the "player used the app today" signal, recorded as any other
  claim in ``challenge_claims``. Superseded sheet items "5-day login" /
  "5-day activity" (vault Decisions 2026-10-15): instead of detecting a
  passive login, the player taps a daily check-in, which doubles as the
  data a streak is computed from (``app.domain.periods.current_streak``)
  -- see ``app/application/challenges.py`` for the streak + achievement
  unlock that runs on a ``DAILY_CHECKIN`` claim.

NOT shipped yet, deliberately left out of this enum rather than wired to a
data source that does not exist:

* "first game" / "Tap Reflex" -- blocked on G1 (no game-run data exists).

Claims live in ``challenge_claims`` (one row per user per challenge per
period; the UNIQUE constraint is the idempotent-claim guard, the same
shape as ``team_memberships``' ``switch_no`` guard) and pay through the
existing coin ledger with key ``challenge:<id>:<period_key>:<user>``
(``docs/ARCHITECTURE.md`` data dictionary).
"""

from dataclasses import dataclass
from enum import StrEnum


class ChallengeKind(StrEnum):
    TEAM_CHOICE = "team_choice"
    DISTINCT_FLAVORS = "distinct_flavors"
    DAILY_CHECKIN = "daily_checkin"


class ChallengePeriod(StrEnum):
    ONCE = "once"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


ONCE_PERIOD_KEY = "ONCE"


@dataclass(frozen=True, slots=True)
class Challenge:
    id: str
    kind: ChallengeKind
    period: ChallengePeriod
    target: int
    reward_coins: int
    active: bool


class ChallengeClaimRefusal(StrEnum):
    UNKNOWN = "unknown"  # no such id, or not active
    NOT_UNLOCKED = "not_unlocked"  # progress below target
    ALREADY_CLAIMED = "already_claimed"


class ChallengeClaimError(Exception):
    def __init__(
        self,
        reason: ChallengeClaimRefusal,
        *,
        required: int | None = None,
        have: int | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.required = required
        self.have = have
