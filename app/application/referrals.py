"""Referral program (RF1): ``PATCH /me`` ``referrer_code``, ``GET /me/referrals``.

Settling is NOT wired into ``RedemptionService``/``TeamService``/
``MiniGameService``/``ProfileService`` directly (RF1.4's original plan):
widening those four already-shipped services' constructors to take a
``ReferralService`` risked every existing fake/test built for them at once
for a feature none of them otherwise need to know about. Instead
``settle`` is idempotent and cheap (a no-op the moment there is no
binding), and is called from ``GET /me`` -- which every one of the four
trigger actions (redeem, profile update, team join, mini-game finish) is
normally followed by in the client to show fresh state. This trades a
small delay (the payout lands on the invitee's NEXT ``/me`` read, not
inside the SAME transaction as the triggering action) for not touching
four unrelated services; record it if that delay ever matters, since the
original plan called for same-transaction settlement.
"""

from collections.abc import Callable
from dataclasses import dataclass
from random import Random
from typing import Protocol
from uuid import UUID

from app.application.authentication import Clock
from app.application.unit_of_work import UnitOfWorkFactory
from app.domain.ledger import LedgerReason, NewLedgerEntry
from app.domain.referrals import (
    ReferralBindError,
    ReferralBindRefusal,
    check_can_bind,
    generate_referral_code,
    settle_payouts,
)

__all__ = [
    "ReferralBindError",
    "ReferralBindRefusal",
    "ReferralCodeStore",
    "ReferralService",
    "ReferralStatus",
]


class ReferralCodeStore(Protocol):
    async def ensure_referral_code(
        self, user_id: UUID, candidate_generator: Callable[[], str]
    ) -> str: ...

    async def get_by_referral_code(self, referral_code: str) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class ReferralStatus:
    referral_code: str
    invited_count: int
    qualified_count: int
    pending_count: int
    coins_earned: int


def _reason_for_key(idempotency_key: str) -> LedgerReason:
    return (
        LedgerReason.REFERRAL_FIRST_CODE
        if idempotency_key.startswith("referral:first:")
        else LedgerReason.REFERRAL_LATER_CODE
    )


class ReferralService:
    def __init__(
        self,
        code_store: ReferralCodeStore,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        terms_required: bool,
        rng: Random | None = None,
    ) -> None:
        self._code_store = code_store
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._terms_required = terms_required
        self._rng = rng or Random()

    async def ensure_code(self, user_id: UUID) -> str:
        return await self._code_store.ensure_referral_code(
            user_id, lambda: generate_referral_code(self._rng)
        )

    async def bind(self, invitee_id: UUID, referral_code: str) -> None:
        """Raises ``ReferralBindError``."""
        now = self._clock.now()
        async with self._unit_of_work() as uow:
            await uow.ledger.lock_wallet(invitee_id, now)
            inviter_id = await uow.referrals.resolve_code(referral_code)
            existing = await uow.referrals.get_by_invitee(invitee_id)
            redeemed_count = len(await uow.codes.list_redeemed(invitee_id))
            check_can_bind(
                invitee_id,
                inviter_id,
                already_bound=existing is not None,
                invitee_redeemed_codes=redeemed_count,
            )
            assert inviter_id is not None  # check_can_bind raised otherwise
            await uow.referrals.bind(invitee_id, inviter_id, now)
            await uow.commit()

    async def settle(self, invitee_id: UUID) -> None:
        """A no-op unless ``invitee_id`` was referred by someone. See the
        module docstring for why this runs on its own, outside the
        transaction of whatever action the invitee just took."""
        now = self._clock.now()
        async with self._unit_of_work() as uow:
            binding = await uow.referrals.get_by_invitee(invitee_id)
            if binding is None:
                return
            status = await uow.referrals.invitee_status(invitee_id)
            mission_complete = (
                status.nickname_set
                and (status.terms_accepted or not self._terms_required)
                and status.has_team
                and status.has_accepted_mini_game_run
            )
            redeemed_codes = await uow.codes.list_redeemed(invitee_id)
            payouts = settle_payouts(
                invitee_id,
                mission_complete=mission_complete,
                redeemed_codes=redeemed_codes,
            )
            if not payouts:
                return
            await uow.ledger.lock_wallet(binding.inviter_user_id, now)
            for payout in payouts:
                if await uow.ledger.amount_for_key(payout.idempotency_key) is not None:
                    continue
                await uow.ledger.record(
                    NewLedgerEntry(
                        user_id=binding.inviter_user_id,
                        amount=payout.amount,
                        reason=_reason_for_key(payout.idempotency_key),
                        idempotency_key=payout.idempotency_key,
                        created_at=now,
                        source_id=str(invitee_id),
                    )
                )
            await uow.commit()

    async def status(self, user_id: UUID) -> ReferralStatus:
        code = await self.ensure_code(user_id)
        async with self._unit_of_work() as uow:
            summary = await uow.referrals.summary(user_id)
        return ReferralStatus(
            referral_code=code,
            invited_count=summary.invited_count,
            qualified_count=summary.qualified_count,
            pending_count=summary.pending_count,
            coins_earned=summary.coins_earned,
        )
