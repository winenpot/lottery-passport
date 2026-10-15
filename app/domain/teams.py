"""Flavor teams: unlock by scanning, choose, then a monthly switch lock.

Rule (vault Decisions 2026-10-15, Mehdi + Ashkan; replaces the Fibonacci
rule of 2026-10-14 evening):

* A team is a TorshX flavor (``CityCode``), not a place. Membership is
  exclusive: a player is on at most one team at a time.
* Redeeming ``UNLOCK_THRESHOLD`` (5) codes of a flavor unlocks it for good
  (lifetime count). The unlock earns that flavor's badge (AC1).
* The player CHOOSES a team among the unlocked flavors; nothing joins
  automatically.
* Joining locks the player in for ``TEAM_LOCK`` (30 days from joining).
  After that they may switch to any other unlocked flavor, including one
  they left earlier, which starts a new lock.

``switch_no`` numbers the memberships of one player: 0 is the first join,
1 the first switch, and so on. The current team is the highest number.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.domain.passports import CityCode

UNLOCK_THRESHOLD = 5
TEAM_LOCK = timedelta(days=30)


def is_unlocked(flavor_codes: int) -> bool:
    """Whether a lifetime count of one flavor's codes unlocks its team."""
    return flavor_codes >= UNLOCK_THRESHOLD


def unlocks_now(flavor_codes_after: int) -> bool:
    """True on the redemption that brings a flavor to exactly the threshold.

    A user's redemptions are serialized (wallet row lock) and each adds one
    code, so the count passes through the threshold exactly once.
    """
    return flavor_codes_after == UNLOCK_THRESHOLD


@dataclass(frozen=True, slots=True)
class TeamMembership:
    user_id: UUID
    flavor: CityCode
    switch_no: int
    joined_at: datetime

    def switch_allowed_at(self, lock: timedelta = TEAM_LOCK) -> datetime:
        return self.joined_at + lock


class TeamChangeRefusal(StrEnum):
    SAME_TEAM = "same_team"
    FLAVOR_NOT_UNLOCKED = "flavor_not_unlocked"
    TEAM_LOCKED = "team_locked"


class TeamChangeError(Exception):
    def __init__(
        self,
        reason: TeamChangeRefusal,
        *,
        required: int | None = None,
        have: int | None = None,
        allowed_at: datetime | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.required = required
        self.have = have
        self.allowed_at = allowed_at


def change_team(
    user_id: UUID,
    current: TeamMembership | None,
    target: CityCode,
    target_codes: int,
    now: datetime,
    lock: timedelta = TEAM_LOCK,
) -> TeamMembership:
    """The membership a join or switch creates, or ``TeamChangeError``.

    ``target_codes`` is the lifetime count of the target flavor's codes.
    """
    if current is not None and current.flavor is target:
        raise TeamChangeError(TeamChangeRefusal.SAME_TEAM)
    if not is_unlocked(target_codes):
        raise TeamChangeError(
            TeamChangeRefusal.FLAVOR_NOT_UNLOCKED,
            required=UNLOCK_THRESHOLD,
            have=target_codes,
        )
    if current is not None and now < current.switch_allowed_at(lock):
        raise TeamChangeError(
            TeamChangeRefusal.TEAM_LOCKED, allowed_at=current.switch_allowed_at(lock)
        )
    return TeamMembership(
        user_id=user_id,
        flavor=target,
        switch_no=0 if current is None else current.switch_no + 1,
        joined_at=now,
    )
