"""Referral program (RF1): invite a friend, earn coins when they qualify.

Rule (Mehdi's rewards sheet, tab «ریفرال»; vault Decisions 2026-10-19 R13,
`.hermes/plans/2026-10-19_1830-referral-and-legal.md` RF0-RF1.6):

* One inviter per user, bound once, only while the invitee has redeemed 0
  codes (``check_can_bind``) -- binding later would let a player backdate a
  referral onto redemptions nobody actually referred.
* The inviter earns ``FIRST_CODE_BONUS_COINS`` once the invitee's mission is
  complete: at least one redeemed code, a finished profile, a chosen team,
  and at least one accepted mini-game run. Until then the payout stays
  PENDING (the sheet's own word) -- nothing pays, not even for later codes.
* Once the mission is complete, every one of the invitee's codes redeemed
  within ``LATER_CODE_WINDOW`` of their FIRST redeemed code earns the
  inviter ``LATER_CODE_BONUS_COINS`` each. The first code is excluded by id
  (it already earned the bigger bonus), never by date, so it can never be
  paid twice under either name.

Nothing here moves money or touches a database: this module is the pure
part only. ``app/application/referrals.py``'s ``ReferralService`` reads the
database, calls :func:`settle_payouts`, and pays what it returns through
the existing append-only ledger (idempotency keys make every entry here
safe to compute more than once).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from random import Random
from uuid import UUID

from app.domain.codes import CROCKFORD_BASE32

REFERRAL_CODE_LENGTH = 8
FIRST_CODE_BONUS_COINS = 15
LATER_CODE_BONUS_COINS = 5
LATER_CODE_WINDOW = timedelta(days=180)

FIRST_CODE_REASON_KEY = "referral:first"
LATER_CODE_REASON_KEY = "referral:code"


def generate_referral_code(rng: Random) -> str:
    """8 random Crockford Base32 characters -- the same alphabet as printed
    product codes (``app/domain/codes.py``), so the app has one "safe to
    read aloud / type" alphabet, not two."""
    return "".join(rng.choice(CROCKFORD_BASE32) for _ in range(REFERRAL_CODE_LENGTH))


def first_code_bonus_key(invitee_id: UUID) -> str:
    return f"{FIRST_CODE_REASON_KEY}:{invitee_id}"


def later_code_bonus_key(redemption_code_id: UUID) -> str:
    return f"{LATER_CODE_REASON_KEY}:{redemption_code_id}"


class ReferralBindRefusal(StrEnum):
    SELF = "self"
    CODE_UNKNOWN = "code_unknown"
    ALREADY_BOUND = "already_bound"
    TOO_LATE = "too_late"


class ReferralBindError(Exception):
    def __init__(self, reason: ReferralBindRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


def check_can_bind(
    invitee_id: UUID,
    inviter_id: UUID | None,
    *,
    already_bound: bool,
    invitee_redeemed_codes: int,
) -> None:
    """Raises ``ReferralBindError``. ``inviter_id`` is ``None`` when the
    submitted referral code matches no user (CODE_UNKNOWN)."""
    if inviter_id is None:
        raise ReferralBindError(ReferralBindRefusal.CODE_UNKNOWN)
    if inviter_id == invitee_id:
        raise ReferralBindError(ReferralBindRefusal.SELF)
    if already_bound:
        raise ReferralBindError(ReferralBindRefusal.ALREADY_BOUND)
    if invitee_redeemed_codes > 0:
        raise ReferralBindError(ReferralBindRefusal.TOO_LATE)


@dataclass(frozen=True, slots=True)
class ReferralPayout:
    amount: int
    idempotency_key: str


def settle_payouts(
    invitee_id: UUID,
    *,
    mission_complete: bool,
    redeemed_codes: list[tuple[UUID, datetime]],
    window: timedelta = LATER_CODE_WINDOW,
) -> list[ReferralPayout]:
    """What the inviter is OWED right now, computed fresh every call.

    ``redeemed_codes`` is every code this invitee has ever redeemed,
    ``(code_id, redeemed_at)``, ordered ascending by ``redeemed_at`` --
    the shape ``RedemptionCodesInTransaction.list_redeemed`` returns.
    Idempotency keys make calling this (and paying its result) more than
    once for the same state harmless: the ledger already holds whichever
    entries were paid before, so the caller's "already paid?" check before
    each insert is what actually prevents a double payout, not this
    function. Returns nothing while ``mission_complete`` is false, even if
    codes already exist -- the sheet's own "pending until mission done"
    rule, not just the first code's bonus.
    """
    if not mission_complete or not redeemed_codes:
        return []
    first_id, first_at = redeemed_codes[0]
    payouts = [ReferralPayout(FIRST_CODE_BONUS_COINS, first_code_bonus_key(invitee_id))]
    window_end = first_at + window
    for code_id, redeemed_at in redeemed_codes[1:]:
        if redeemed_at > window_end:
            break  # ascending order: every later code is also out of window
        payouts.append(
            ReferralPayout(LATER_CODE_BONUS_COINS, later_code_bonus_key(code_id))
        )
    return payouts
