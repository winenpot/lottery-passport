"""Flavor teams with Fibonacci switching (vault Decisions 2026-10-14 evening).

A team is a TorshX flavor (``CityCode``), not a place. Membership is
exclusive: a player is on at most one team at a time.

* The first join is automatic, on the redemption that brings one flavor to
  ``JOIN_THRESHOLD`` (5) codes.
* After that a switch is the player's choice and needs the next Fibonacci
  number of codes of the TARGET flavor: 8 for the first switch, 13 for the
  second, then 21, 34, ...
* Codes count since the last team change, so each switch is harder than the
  one before (lifetime counts would make later switches free).

``switch_no`` numbers the memberships of one player: 0 is the first join,
1 the first switch, and so on. The current team is the highest number.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.passports import CityCode

JOIN_THRESHOLD = 5
_FIRST_SWITCH_THRESHOLD = 8


def switch_threshold(switch_no: int) -> int:
    """Codes of one flavor needed to take membership number ``switch_no``.

    0 -> 5 (join), 1 -> 8, 2 -> 13, 3 -> 21, ...
    """
    if switch_no < 0:
        raise ValueError(f"switch_no must be >= 0, got {switch_no}")
    current, following = JOIN_THRESHOLD, _FIRST_SWITCH_THRESHOLD
    for _ in range(switch_no):
        current, following = following, current + following
    return current


@dataclass(frozen=True, slots=True)
class TeamMembership:
    user_id: UUID
    flavor: CityCode
    switch_no: int
    joined_at: datetime


def next_required(current: TeamMembership | None) -> int:
    """Codes of the target flavor the player's next team change needs."""
    return switch_threshold(0 if current is None else current.switch_no + 1)


def should_auto_join(current: TeamMembership | None, flavor_codes: int) -> bool:
    """True when a player without a team has reached the join threshold.

    Only the first join is automatic; a player already on a team never
    changes team by redeeming.
    """
    return current is None and flavor_codes >= JOIN_THRESHOLD


class SwitchRefusal(StrEnum):
    NOT_JOINED = "not_joined"
    SAME_TEAM = "same_team"
    THRESHOLD_NOT_MET = "threshold_not_met"


class TeamSwitchError(Exception):
    def __init__(self, reason: SwitchRefusal, required: int, have: int) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.required = required
        self.have = have


def switch_team(
    current: TeamMembership | None,
    target: CityCode,
    target_codes_since_change: int,
    now: datetime,
) -> TeamMembership:
    """The membership a requested switch creates, or ``TeamSwitchError``.

    ``target_codes_since_change`` counts the target flavor's codes redeemed
    after ``current.joined_at``.
    """
    required = next_required(current)
    if current is None:
        # The first team is never picked: it comes from the 5th code.
        raise TeamSwitchError(
            SwitchRefusal.NOT_JOINED, required, target_codes_since_change
        )
    if current.flavor is target:
        raise TeamSwitchError(
            SwitchRefusal.SAME_TEAM, required, target_codes_since_change
        )
    if target_codes_since_change < required:
        raise TeamSwitchError(
            SwitchRefusal.THRESHOLD_NOT_MET, required, target_codes_since_change
        )
    return TeamMembership(
        user_id=current.user_id,
        flavor=target,
        switch_no=current.switch_no + 1,
        joined_at=now,
    )
