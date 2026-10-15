"""Challenges (C1, B17): automatic rewards computed from what a player did.

A ``challenge`` row (admin-tunable, like avatars/venues/reward_rules — the
table starts empty, filled in ``/admin``) says WHAT must be true (``kind``,
``target``) and HOW MUCH it pays (``reward_coins``) on what cadence
(``period``). This module is the closed set of ``kind`` values this
backend knows how to check progress for: adding a row with an unknown kind
is a mistake, not a new feature (the engine has no plugin mechanism).

Shipped now (2026-10-15, both backed by data that already exists):

* ``TEAM_CHOICE`` -- once: the player has ever joined a flavor team
  (``team_memberships``, P1). Sheet: "choose team" 30 coins once.
* ``DISTINCT_FLAVORS`` -- period: distinct flavors redeemed in the period
  (``redemption_codes``). Sheet: "discover 3 flavors" 100 coins monthly.

NOT shipped yet, deliberately left out of this enum rather than wired to a
data source that does not exist (see docs/vault/Decisions.md 2026-10-15):

* "first game" / "Tap Reflex" -- blocked on G1 (no game-run data exists).
* "5-day login" / "5-day activity" -- needs a real tracking mechanism for
  "which calendar days did this player use the app", which does not exist
  today (a long-lived session cookie means a login event does not happen
  every day a player opens the app). Needs a product decision (where to
  record a "day used" signal) before it can be built, not just more code.

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
