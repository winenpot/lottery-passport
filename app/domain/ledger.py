"""Coins: an append-only ledger plus a cached balance per user.

The ledger is the source of truth. ``wallets.balance`` is a derived value
kept in the same transaction as every ledger insert, guarded by a
``CHECK (balance >= 0)`` constraint, and reconciled by
``SELECT user_id, SUM(amount) ...`` when in doubt. Corrections are new
compensating entries, never edits: the database rejects UPDATE and DELETE on
``coin_ledger_entries``.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class LedgerReason(StrEnum):
    CODE_REDEMPTION = "code_redemption"
    FIRST_CODE_BONUS = "first_code_bonus"
    CHALLENGE_REWARD = "challenge_reward"
    ACHIEVEMENT_REWARD = "achievement_reward"
    TOURNAMENT_PRIZE = "tournament_prize"
    SOCIAL_POST_REWARD = "social_post_reward"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    STORE_PURCHASE = "store_purchase"


class Asset(StrEnum):
    """What a ledger entry moves. Only ``coin`` exists; ``asset`` is added
    now (ADR 0010) so a future diamond currency widens a CHECK constraint
    instead of needing another migration to the ledger's shape."""

    COIN = "coin"


@dataclass(frozen=True, slots=True)
class NewLedgerEntry:
    """A coin movement to record. ``amount`` is negative for spending.

    ``idempotency_key`` is unique in the database: the same logical award
    (for example ``code_redemption:<code id>``) can never be recorded twice,
    whatever the application does.
    """

    user_id: UUID
    amount: int
    reason: LedgerReason
    idempotency_key: str
    created_at: datetime
    source_id: str | None = None
    actor_id: UUID | None = None
    note: str | None = None
    asset: Asset = Asset.COIN


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: int
    user_id: UUID
    amount: int
    reason: LedgerReason
    source_id: str | None
    created_at: datetime
    asset: Asset = Asset.COIN


@dataclass(frozen=True, slots=True)
class Wallet:
    user_id: UUID
    balance: int
    lifetime_earned: int
    updated_at: datetime
