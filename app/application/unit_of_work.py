"""Ports for use cases that must change several tables in ONE transaction.

Each repository below is bound to the unit of work's single database
transaction. Nothing is persisted until ``commit()``; leaving the ``async
with`` block without committing (including by raising) rolls everything
back. Code claim, passport entries, ledger entry and wallet balance
therefore succeed or fail together.
"""

from dataclasses import dataclass
from datetime import date, datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.domain.achievements import Achievement, AchievementFact
from app.domain.audit import NewAuditEntry
from app.domain.challenges import Challenge, ChallengeKind
from app.domain.ledger import NewLedgerEntry
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.reward_rules import RewardRule
from app.domain.teams import TeamMembership


@dataclass(frozen=True, slots=True)
class ClaimedCode:
    """A code this transaction has just marked as redeemed."""

    code_id: UUID
    city: CityCode
    coins_per_code: int


@dataclass(frozen=True, slots=True)
class CodeLookup:
    """Current state of a code that could not be claimed."""

    code_id: UUID
    city: CityCode
    redeemed_by_user_id: UUID | None
    batch_active: bool


class RedemptionCodesInTransaction(Protocol):
    async def claim(
        self, code_hash: str, user_id: UUID, now: datetime
    ) -> ClaimedCode | None:
        """Atomically mark an unredeemed code of an active batch as redeemed.

        Returns ``None`` when no such code exists. Concurrent claims of the
        same code are serialized by the row lock; exactly one wins.
        """
        ...

    async def lookup(self, code_hash: str) -> CodeLookup | None: ...

    async def count_redeemed_since(self, user_id: UUID, since: datetime) -> int: ...


class PassportsInTransaction(Protocol):
    async def add_entries(
        self, user_id: UUID, campaign: Campaign, amount: int, now: datetime
    ) -> PassportProgress: ...

    async def get(
        self, user_id: UUID, campaign: Campaign
    ) -> PassportProgress | None: ...


class InsufficientCoinsError(Exception):
    """A debit would take the wallet below zero."""


class LedgerInTransaction(Protocol):
    async def lock_wallet(self, user_id: UUID, now: datetime) -> int:
        """Create the wallet if needed, lock its row and return the balance.

        Locking the wallet first serializes all coin-changing transactions of
        one user, which is what makes per-user limits (daily caps) safe under
        concurrency.
        """
        ...

    async def record(self, entry: NewLedgerEntry) -> int:
        """Insert the entry and apply it to the wallet; return the new balance.

        Raises ``InsufficientCoinsError`` for a debit larger than the balance.
        """
        ...

    async def amount_for_key(self, idempotency_key: str) -> int | None: ...


class AuditInTransaction(Protocol):
    async def record(self, entry: NewAuditEntry) -> None:
        """Insert an audit row in the same transaction as the write it covers."""
        ...


class RewardRulesInTransaction(Protocol):
    async def get(self, key: str) -> RewardRule | None:
        """The current rule for ``key``, or ``None`` if nobody has set one.

        ``None`` is the normal case for most keys (ADR 0010): it means "use
        the calling service's configured default", not an error.
        """
        ...


class TeamsInTransaction(Protocol):
    """Flavor team history (app/domain/teams.py), inside the unit of work.

    ``count_codes`` counts a user's LIFETIME redemptions of one flavor (the
    unlock rule, 2026-10-15), not since any particular date.
    """

    async def current(self, user_id: UUID) -> TeamMembership | None:
        """The player's current membership (highest ``switch_no``), or
        ``None`` before any team has ever been joined."""
        ...

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        """Lifetime count of this user's redeemed codes of one flavor."""
        ...

    async def add(self, membership: TeamMembership) -> None:
        """Insert one membership row. UNIQUE (user_id, switch_no) is the
        race guard; the caller locks the user's wallet row first so this
        should not actually conflict in normal operation."""
        ...


class ChallengesInTransaction(Protocol):
    """Challenge catalogue + claims (app/domain/challenges.py, C1), inside
    the unit of work: a claim's own progress check and its ledger write
    must see the same transaction."""

    async def get(self, challenge_id: str) -> Challenge | None:
        """An active challenge by id, or ``None`` if unknown/inactive."""
        ...

    async def get_by_kind(self, kind: ChallengeKind) -> Challenge | None:
        """The active challenge of this kind, if any (assumed singleton
        per kind for the MVP)."""
        ...

    async def distinct_flavors_since(self, user_id: UUID, since: datetime) -> int:
        """Distinct flavors this user has redeemed a code of since ``since``."""
        ...

    async def checkin_days(self, challenge_id: str, user_id: UUID) -> set[date]:
        """Every Tehran calendar date this user has claimed ``challenge_id``
        (a ``DAILY_CHECKIN`` challenge) on -- the raw data a streak is
        computed from (``app.domain.periods.current_streak``)."""
        ...

    async def has_claimed(
        self, challenge_id: str, user_id: UUID, period_key: str
    ) -> bool: ...

    async def claim(
        self, challenge_id: str, user_id: UUID, period_key: str, now: datetime
    ) -> None:
        """Insert the claim row. UNIQUE (challenge_id, user_id, period_key)
        is the race guard; the caller locks the user's wallet row first."""
        ...


class AchievementsInTransaction(Protocol):
    """Achievement catalogue + unlocks (app/domain/achievements.py, AC1),
    inside the unit of work: the fact check and its ledger write must see
    the same transaction as the triggering claim."""

    async def list_active_by_fact(self, fact: AchievementFact) -> list[Achievement]:
        """Active achievements checked against this fact (assumed few per
        fact for the MVP; iterated in full on every triggering claim)."""
        ...

    async def already_unlocked(self, achievement_id: str, user_id: UUID) -> bool: ...

    async def unlock(self, achievement_id: str, user_id: UUID, now: datetime) -> None:
        """Insert the unlock row. UNIQUE (achievement_id, user_id) is the
        only-once guard; the caller locks the user's wallet row first."""
        ...


class UnitOfWork(Protocol):
    # Read-only properties so implementations may expose concrete subtypes.
    @property
    def codes(self) -> RedemptionCodesInTransaction: ...

    @property
    def passports(self) -> PassportsInTransaction: ...

    @property
    def ledger(self) -> LedgerInTransaction: ...

    @property
    def audit(self) -> AuditInTransaction: ...

    @property
    def rules(self) -> RewardRulesInTransaction: ...

    @property
    def teams(self) -> TeamsInTransaction: ...

    @property
    def challenges(self) -> ChallengesInTransaction: ...

    @property
    def achievements(self) -> AchievementsInTransaction: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
