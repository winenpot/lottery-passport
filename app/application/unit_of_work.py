"""Ports for use cases that must change several tables in ONE transaction.

Each repository below is bound to the unit of work's single database
transaction. Nothing is persisted until ``commit()``; leaving the ``async
with`` block without committing (including by raising) rolls everything
back. Code claim, passport entries, ledger entry and wallet balance
therefore succeed or fail together.
"""

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.domain.audit import NewAuditEntry
from app.domain.ledger import NewLedgerEntry
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.reward_rules import RewardRule


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
