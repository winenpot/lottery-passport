"""Reward rules: admin-tunable amounts for rewards the backend pays.

A ``reward_rules`` row lets Mehdi override or switch off a reward's amount
from ``/admin`` without a deploy. No row for a key means "use the
service's configured default" — the table starts empty (like venues: no
seeded business data), so a missing row is normal, not an error.
"""

from dataclasses import dataclass
from enum import StrEnum


class Cadence(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass(frozen=True, slots=True)
class RewardRule:
    key: str
    amount: int
    cadence: Cadence
    active: bool
    note: str | None = None
