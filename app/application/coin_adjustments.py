"""Admin-initiated coin changes: the ``/admin`` "Adjust coins" page.

One transaction writes the ledger entry, the wallet balance and the audit
row together (CLAUDE.md: multi-table writes go through the unit of work
port), so a coin adjustment can never show up in the ledger without its
audit trail, or the other way round.

Not idempotent the way code redemption is: there is no natural dedupe key
for a deliberate manual action, so a resubmitted form applies twice. The
admin page guards against an accidental double submit (disabled button
after click); a true server-side guard (a one-time token on the form) is a
follow-up, not done here.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from app.application.authentication import Clock
from app.application.unit_of_work import InsufficientCoinsError, UnitOfWorkFactory
from app.domain.audit import AuditAction, NewAuditEntry
from app.domain.ledger import LedgerReason, NewLedgerEntry
from app.domain.phone import PhoneNumberError, normalize_iranian_mobile
from app.domain.users import User

__all__ = [
    "CoinAdjustmentResult",
    "CoinAdjustmentService",
    "InsufficientCoinsError",
    "PhoneNumberError",
    "UserLookup",
    "UserNotFoundError",
]


class UserNotFoundError(Exception):
    """No player with this phone number."""


class UserLookup(Protocol):
    async def get_by_identifier(self, identifier: str) -> User | None: ...


@dataclass(frozen=True, slots=True)
class CoinAdjustmentResult:
    user_id: UUID
    new_balance: int


class CoinAdjustmentService:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        users: UserLookup,
        clock: Clock,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._users = users
        self._clock = clock

    async def adjust(
        self,
        *,
        actor_id: UUID,
        target_identifier: str,
        amount: int,
        note: str,
        ip: str | None,
    ) -> CoinAdjustmentResult:
        """Give (``amount`` > 0) or take (``amount`` < 0) coins, with a reason.

        Raises ``PhoneNumberError`` (bad phone), ``UserNotFoundError``,
        ``ValueError`` (zero amount or empty note), or
        ``InsufficientCoinsError`` (a debit larger than the balance).
        """
        if amount == 0:
            raise ValueError("amount must not be zero")
        note = note.strip()
        if not note:
            raise ValueError("note must not be empty")
        phone = normalize_iranian_mobile(target_identifier)
        target = await self._users.get_by_identifier(phone)
        if target is None:
            raise UserNotFoundError(phone)

        now = self._clock.now()
        async with self._unit_of_work() as uow:
            await uow.ledger.lock_wallet(target.id, now)
            new_balance = await uow.ledger.record(
                NewLedgerEntry(
                    user_id=target.id,
                    amount=amount,
                    reason=LedgerReason.ADMIN_ADJUSTMENT,
                    idempotency_key=(
                        f"{LedgerReason.ADMIN_ADJUSTMENT.value}:{uuid4()}"
                    ),
                    created_at=now,
                    actor_id=actor_id,
                    note=note,
                )
            )
            # entity_id names the affected player, not the new ledger row's
            # own id (uow.ledger.record does not hand that back; the player
            # is the more useful key to search the audit log by).
            await uow.audit.record(
                NewAuditEntry(
                    actor_user_id=actor_id,
                    action=AuditAction.CREATE,
                    entity="coin_ledger_entry",
                    entity_id=str(target.id),
                    created_at=now,
                    changes={
                        "amount": amount,
                        "note": note,
                        "target_phone": phone,
                    },
                    ip=ip,
                )
            )
            await uow.commit()
        return CoinAdjustmentResult(user_id=target.id, new_balance=new_balance)
