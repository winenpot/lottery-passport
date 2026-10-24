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
from app.domain.mini_games import (
    MiniGameId,
    MiniGameRun,
    MiniGameRunStatus,
    NewMiniGameRun,
)
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.reward_rules import RewardRule
from app.domain.teams import TeamMembership


@dataclass(frozen=True, slots=True)
class ClaimedCode:
    """A code this transaction has just marked as redeemed."""

    code_id: UUID
    city: CityCode
    coins_per_code: int
    batch_id: UUID


@dataclass(frozen=True, slots=True)
class CodeLookup:
    """Current state of a code that could not be claimed."""

    code_id: UUID
    city: CityCode
    redeemed_by_user_id: UUID | None
    batch_active: bool
    batch_id: UUID | None


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

    async def list_redeemed(self, user_id: UUID) -> list[tuple[UUID, datetime]]:
        """Every code this user has redeemed, ``(code_id, redeemed_at)``,
        ascending by ``redeemed_at``. Referrals (RF1) is the only caller
        today -- it needs stable per-code ids for idempotency keys, which a
        plain count cannot give."""
        ...


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

    async def accepted_mini_game_runs_total(self, user_id: UUID) -> int:
        """Lifetime count of this user's ACCEPTED ``mini_game_runs`` rows,
        any mini-game id (``FIRST_MINI_GAME``)."""
        ...

    async def fast_tap_reflex_runs_since(
        self, user_id: UUID, since: datetime, max_average_ms: float
    ) -> int:
        """Count of this user's ACCEPTED ``tap_reflex`` runs finished since
        ``since`` with ``average_reaction_ms < max_average_ms``
        (``TAP_REFLEX_FAST``)."""
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


@dataclass(frozen=True, slots=True)
class ReferralBinding:
    invitee_user_id: UUID
    inviter_user_id: UUID
    bound_at: datetime


@dataclass(frozen=True, slots=True)
class ReferralInviteeStatus:
    """What ``settle_payouts`` (app/domain/referrals.py) needs to decide if
    the invitee's mission is complete. Raw fields, not a pre-computed
    ``profile_complete`` bool: whether terms acceptance is REQUIRED is a
    ``Settings`` value the application layer knows, not this port."""

    nickname_set: bool
    terms_accepted: bool
    has_team: bool
    has_accepted_mini_game_run: bool


@dataclass(frozen=True, slots=True)
class ReferralSummary:
    invited_count: int
    qualified_count: int
    pending_count: int
    coins_earned: int


class ReferralsInTransaction(Protocol):
    """Referrals (RF1, app/domain/referrals.py), inside the unit of work:
    binding and settling both share the wallet lock's per-user
    serialization with every other coin-moving use case here."""

    async def get_by_invitee(self, invitee_id: UUID) -> ReferralBinding | None: ...

    async def resolve_code(self, referral_code: str) -> UUID | None:
        """The inviter's user id for a referral code, or ``None`` if the
        code matches no user."""
        ...

    async def bind(self, invitee_id: UUID, inviter_id: UUID, now: datetime) -> None:
        """Insert the binding row. The primary key on ``invitee_user_id``
        is the one-inviter-ever guard; the caller checks
        ``get_by_invitee`` first for a clean 409 before even attempting
        the insert."""
        ...

    async def invitee_status(self, invitee_id: UUID) -> ReferralInviteeStatus: ...

    async def summary(self, inviter_user_id: UUID) -> ReferralSummary: ...


class MiniGamesInTransaction(Protocol):
    """Server-verified mini-game runs (app/domain/mini_games.py, G1), inside
    the unit of work: opening/finishing a run shares its transaction with
    the wallet lock, same per-user serialization as teams/challenges."""

    async def open(self, run: NewMiniGameRun) -> None:
        """Insert the run row as OPEN. The partial unique index
        ``uq_mini_game_runs_user_open`` is the database's own "one open
        run per user" guard; ``get_open`` below lets the caller refuse
        with a clean 409 before even attempting the insert."""
        ...

    async def get_open(
        self, user_id: UUID, mini_game_id: MiniGameId
    ) -> MiniGameRun | None:
        """This user's currently open run of this mini-game, if any."""
        ...

    async def get(self, run_id: UUID) -> MiniGameRun | None: ...

    async def finish(
        self,
        run_id: UUID,
        status: MiniGameRunStatus,
        finished_at: datetime,
        average_reaction_ms: float | None,
    ) -> None:
        """Move a run from OPEN to ACCEPTED, REJECTED or EXPIRED.
        ``average_reaction_ms`` is None for EXPIRED (never played to the
        end): a run closed by a newer start, or finished after its TTL."""
        ...

    async def count_rejected_since(self, user_id: UUID, since: datetime) -> int:
        """How many of this user's runs were REJECTED since ``since`` --
        feeds the service-layer 3/day admin-review flag."""
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

    @property
    def mini_games(self) -> MiniGamesInTransaction: ...

    @property
    def referrals(self) -> ReferralsInTransaction: ...

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
