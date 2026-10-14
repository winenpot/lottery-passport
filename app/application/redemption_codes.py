"""Redeeming a printed code: one lottery entry for its city plus coins.

The whole use case runs in one database transaction (see
``app.application.unit_of_work``):

1. lock the user's wallet row (serializes this user's redemptions)
2. claim the code with a conditional UPDATE (serializes rival users)
3. enforce the per-user daily cap, counted in the campaign time zone
4. add the city entry, record the coin award, update the balance
5. commit

Re-submitting a code you already redeemed returns the original result with
``replayed=True`` instead of an error, so clients can retry after a timeout
without double-crediting (the ledger's unique idempotency key guarantees it
even if this code had a bug).
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.application.failure_throttle import FailureThrottle, ThrottleSettings
from app.application.unit_of_work import ClaimedCode, UnitOfWork, UnitOfWorkFactory
from app.domain.codes import CodeFormatError, CodeProblem, parse_code
from app.domain.ledger import LedgerReason, NewLedgerEntry
from app.domain.passports import CAMPAIGN_BY_CITY, ENTRIES_PER_CODE, CityCode

FIRST_CODE_BONUS_KEY = "first_code"


class RedemptionErrorCode(StrEnum):
    """Stable error codes the frontend maps to user-facing copy."""

    NOT_CONFIGURED = "REDEMPTION_NOT_CONFIGURED"
    MALFORMED = "CODE_MALFORMED"
    MISTYPED = "CODE_MISTYPED"
    INVALID = "CODE_INVALID"
    ALREADY_REDEEMED = "CODE_ALREADY_REDEEMED"
    DAILY_LIMIT = "REDEMPTION_DAILY_LIMIT"
    ATTEMPTS_LIMITED = "CODE_ATTEMPTS_LIMITED"


class RedemptionError(Exception):
    def __init__(
        self, code: RedemptionErrorCode, retry_after: int | None = None
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class RedemptionResult:
    city: CityCode
    entries_added: int
    city_entries: int
    coins_awarded: int
    coin_balance: int
    replayed: bool
    bonus_awarded: int = 0


def hash_redemption_code(code: str, pepper: str) -> str:
    """Keyed hash of a canonical code; the pepper never lives in the database.

    A plain SHA-256 would let anyone holding a database dump enumerate the
    whole code space offline. With HMAC they also need the pepper.
    """
    return hmac.new(
        pepper.encode("utf-8"), code.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def redemption_idempotency_key(code_id: UUID) -> str:
    return f"{LedgerReason.CODE_REDEMPTION.value}:{code_id}"


def first_code_bonus_idempotency_key(user_id: UUID) -> str:
    return f"{FIRST_CODE_BONUS_KEY}:{user_id}"


def start_of_local_day(moment: datetime, zone: ZoneInfo) -> datetime:
    """UTC-aware instant of the most recent local midnight in ``zone``."""
    local = moment.astimezone(zone)
    return datetime.combine(local.date(), time.min, tzinfo=zone)


class RedemptionService:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        pepper: str | None,
        daily_limit: int,
        campaign_zone: ZoneInfo,
        throttle: FailureThrottle | None = None,
        throttle_settings: ThrottleSettings | None = None,
        first_code_bonus_coins: int = 0,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._pepper = pepper
        self._daily_limit = daily_limit
        self._campaign_zone = campaign_zone
        self._throttle = throttle
        self._throttle_settings = throttle_settings or ThrottleSettings()
        # Default when no `reward_rules` row overrides it (ADR 0010); the
        # sheet's number lives in Settings, not hardcoded here.
        self._first_code_bonus_coins = first_code_bonus_coins

    async def redeem(self, user_id: UUID, raw_code: str) -> RedemptionResult:
        if self._pepper is None:
            raise RedemptionError(RedemptionErrorCode.NOT_CONFIGURED)
        try:
            parsed = parse_code(raw_code)
        except CodeFormatError as error:
            code = (
                RedemptionErrorCode.MISTYPED
                if error.problem is CodeProblem.MISTYPED
                else RedemptionErrorCode.MALFORMED
            )
            raise RedemptionError(code) from error

        now = self._clock.now()

        # Per-account invalid-code throttle: reject before touching the store.
        if self._throttle is not None:
            window_start = now - timedelta(
                seconds=self._throttle_settings.window_seconds
            )
            failures = await self._throttle.count_in_window(user_id, window_start)
            if failures >= self._throttle_settings.max_attempts:
                raise RedemptionError(
                    RedemptionErrorCode.ATTEMPTS_LIMITED,
                    retry_after=self._throttle_settings.window_seconds,
                )

        code_hash = hash_redemption_code(parsed.canonical, self._pepper)
        try:
            async with self._unit_of_work() as uow:
                balance = await uow.ledger.lock_wallet(user_id, now)
                claimed = await uow.codes.claim(code_hash, user_id, now)
                if claimed is None:
                    return await self._resolve_unclaimed(
                        uow, code_hash, user_id, balance
                    )
                result = await self._apply_claim(uow, claimed, user_id, balance, now)
                await uow.commit()
                return result
        except RedemptionError as error:
            if error.code is RedemptionErrorCode.INVALID and self._throttle is not None:
                await self._throttle.record(user_id, now)
            raise

    async def _apply_claim(
        self,
        uow: UnitOfWork,
        claimed: ClaimedCode,
        user_id: UUID,
        balance: int,
        now: datetime,
    ) -> RedemptionResult:
        since = start_of_local_day(now, self._campaign_zone)
        if await uow.codes.count_redeemed_since(user_id, since) > self._daily_limit:
            # Raising before commit rolls the claim back: the code stays usable.
            raise RedemptionError(RedemptionErrorCode.DAILY_LIMIT)

        progress = await uow.passports.add_entries(
            user_id, CAMPAIGN_BY_CITY[claimed.city], ENTRIES_PER_CODE, now
        )
        if claimed.coins_per_code > 0:
            balance = await uow.ledger.record(
                NewLedgerEntry(
                    user_id=user_id,
                    amount=claimed.coins_per_code,
                    reason=LedgerReason.CODE_REDEMPTION,
                    idempotency_key=redemption_idempotency_key(claimed.code_id),
                    created_at=now,
                    source_id=str(claimed.code_id),
                )
            )
        balance, bonus = await self._award_first_code_bonus(uow, user_id, balance, now)
        return RedemptionResult(
            city=claimed.city,
            entries_added=ENTRIES_PER_CODE,
            city_entries=progress.points,
            coins_awarded=claimed.coins_per_code,
            coin_balance=balance,
            replayed=False,
            bonus_awarded=bonus,
        )

    async def _award_first_code_bonus(
        self, uow: UnitOfWork, user_id: UUID, balance: int, now: datetime
    ) -> tuple[int, int]:
        """Pay the welcome bonus at most once per user (ADR 0010).

        A ``reward_rules`` row for ``first_code`` overrides the amount or
        turns it off (``active=false``); no row means "use the configured
        default". Checked on every redemption rather than only the first,
        since nothing marks a user as "first redemption done" ahead of the
        ledger itself — the idempotency key is what actually prevents a
        second payout.
        """
        rule = await uow.rules.get(FIRST_CODE_BONUS_KEY)
        amount = rule.amount if rule is not None else self._first_code_bonus_coins
        active = rule.active if rule is not None else True
        if not active or amount <= 0:
            return balance, 0
        key = first_code_bonus_idempotency_key(user_id)
        if await uow.ledger.amount_for_key(key) is not None:
            return balance, 0
        balance = await uow.ledger.record(
            NewLedgerEntry(
                user_id=user_id,
                amount=amount,
                reason=LedgerReason.FIRST_CODE_BONUS,
                idempotency_key=key,
                created_at=now,
            )
        )
        return balance, amount

    async def _resolve_unclaimed(
        self, uow: UnitOfWork, code_hash: str, user_id: UUID, balance: int
    ) -> RedemptionResult:
        found = await uow.codes.lookup(code_hash)
        if found is None or found.redeemed_by_user_id is None:
            # Unknown code, or a code whose batch is not active (not yet
            # released, or voided). Deliberately indistinguishable.
            raise RedemptionError(RedemptionErrorCode.INVALID)
        if found.redeemed_by_user_id != user_id:
            raise RedemptionError(RedemptionErrorCode.ALREADY_REDEEMED)

        progress = await uow.passports.get(user_id, CAMPAIGN_BY_CITY[found.city])
        coins = await uow.ledger.amount_for_key(
            redemption_idempotency_key(found.code_id)
        )
        return RedemptionResult(
            city=found.city,
            entries_added=ENTRIES_PER_CODE,
            city_entries=progress.points if progress else 0,
            coins_awarded=coins or 0,
            coin_balance=balance,
            replayed=True,
        )
