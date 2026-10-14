"""CoinAdjustmentService rules, against an in-memory unit of work.

The fake applies changes to a copy of the store and only publishes them on
commit, so these tests also prove that a rejected adjustment (insufficient
balance) leaves nothing behind -- same technique as
``tests/unit/test_redemption_service.py``. Real constraints (the append-only
trigger, the foreign key) are covered by
``tests/integration/test_coin_adjustments_db.py``.
"""

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest

from app.application.coin_adjustments import CoinAdjustmentService, UserNotFoundError
from app.application.unit_of_work import InsufficientCoinsError
from app.domain.audit import AuditAction, NewAuditEntry
from app.domain.ledger import LedgerReason, NewLedgerEntry
from app.domain.phone import PhoneNumberError
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus

ADMIN_ID = uuid4()
PLAYER_PHONE = "+989121112233"


def _player(user_id: UUID, phone: str) -> User:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    return User(
        id=user_id,
        identifier=phone,
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=UserRole.PLAYER,
        created_at=now,
        updated_at=now,
    )


@dataclass
class Store:
    users: dict[str, User] = field(default_factory=dict)
    ledger: list[NewLedgerEntry] = field(default_factory=list)
    wallets: dict[UUID, int] = field(default_factory=dict)
    audit: list[NewAuditEntry] = field(default_factory=list)


class FakeUsers:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def get_by_identifier(self, identifier: str) -> User | None:
        return self.store.users.get(identifier)


class FakeLedger:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def lock_wallet(self, user_id: UUID, now: datetime) -> int:
        return self.store.wallets.setdefault(user_id, 0)

    async def record(self, entry: NewLedgerEntry) -> int:
        if any(e.idempotency_key == entry.idempotency_key for e in self.store.ledger):
            raise AssertionError("duplicate idempotency key")  # the DB would reject
        new_balance = self.store.wallets.get(entry.user_id, 0) + entry.amount
        if new_balance < 0:
            raise InsufficientCoinsError(str(entry.user_id))
        self.store.ledger.append(entry)
        self.store.wallets[entry.user_id] = new_balance
        return new_balance


class FakeAudit:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def record(self, entry: NewAuditEntry) -> None:
        self.store.audit.append(entry)


class FakeUnitOfWork:
    def __init__(self, committed: Store) -> None:
        self._committed = committed
        self.working = Store()

    @property
    def ledger(self) -> FakeLedger:
        return FakeLedger(self.working)

    @property
    def audit(self) -> FakeAudit:
        return FakeAudit(self.working)

    async def __aenter__(self) -> Self:
        self.working = copy.deepcopy(self._committed)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self._committed.__dict__.update(copy.deepcopy(self.working).__dict__)


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


def build(store: Store | None = None) -> tuple[CoinAdjustmentService, Store]:
    store = store if store is not None else Store()
    clock = FakeClock(datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
    service = CoinAdjustmentService(
        unit_of_work=lambda: FakeUnitOfWork(store),
        users=FakeUsers(store),
        clock=clock,
    )
    return service, store


@pytest.mark.asyncio
async def test_giving_coins_records_ledger_wallet_and_audit_together() -> None:
    player_id = uuid4()
    store = Store(users={PLAYER_PHONE: _player(player_id, PLAYER_PHONE)})
    service, store = build(store)

    result = await service.adjust(
        actor_id=ADMIN_ID,
        target_identifier="0912 111 2233",
        amount=500,
        note="goodwill credit",
        ip="10.0.0.1",
    )

    assert (result.user_id, result.new_balance) == (player_id, 500)
    assert store.wallets[player_id] == 500
    assert len(store.ledger) == 1
    entry = store.ledger[0]
    assert entry.amount == 500
    assert entry.reason is LedgerReason.ADMIN_ADJUSTMENT
    assert entry.actor_id == ADMIN_ID
    assert entry.note == "goodwill credit"
    assert len(store.audit) == 1
    audit_entry = store.audit[0]
    assert audit_entry.actor_user_id == ADMIN_ID
    assert audit_entry.action is AuditAction.CREATE
    assert audit_entry.entity == "coin_ledger_entry"
    assert audit_entry.entity_id == str(player_id)
    assert audit_entry.changes == {
        "amount": 500,
        "note": "goodwill credit",
        "target_phone": PLAYER_PHONE,
    }
    assert audit_entry.ip == "10.0.0.1"


@pytest.mark.asyncio
async def test_taking_coins_away_lowers_the_balance() -> None:
    player_id = uuid4()
    store = Store(
        users={PLAYER_PHONE: _player(player_id, PLAYER_PHONE)},
        wallets={player_id: 1000},
    )
    service, store = build(store)

    result = await service.adjust(
        actor_id=ADMIN_ID,
        target_identifier=PLAYER_PHONE,
        amount=-300,
        note="chargeback",
        ip=None,
    )

    assert result.new_balance == 700
    assert store.wallets[player_id] == 700


@pytest.mark.asyncio
async def test_a_debit_past_zero_is_rejected_and_nothing_is_recorded() -> None:
    player_id = uuid4()
    store = Store(
        users={PLAYER_PHONE: _player(player_id, PLAYER_PHONE)},
        wallets={player_id: 100},
    )
    service, store = build(store)

    with pytest.raises(InsufficientCoinsError):
        await service.adjust(
            actor_id=ADMIN_ID,
            target_identifier=PLAYER_PHONE,
            amount=-200,
            note="too much",
            ip=None,
        )

    assert store.wallets[player_id] == 100
    assert store.ledger == []
    assert store.audit == []


@pytest.mark.asyncio
async def test_an_unknown_phone_number_is_refused() -> None:
    service, _ = build()

    with pytest.raises(UserNotFoundError):
        await service.adjust(
            actor_id=ADMIN_ID,
            target_identifier=PLAYER_PHONE,
            amount=100,
            note="typo'd number",
            ip=None,
        )


@pytest.mark.asyncio
async def test_a_malformed_phone_number_is_refused() -> None:
    service, _ = build()

    with pytest.raises(PhoneNumberError):
        await service.adjust(
            actor_id=ADMIN_ID,
            target_identifier="not a phone",
            amount=100,
            note="typo'd number",
            ip=None,
        )


@pytest.mark.asyncio
async def test_a_zero_amount_is_refused() -> None:
    player_id = uuid4()
    store = Store(users={PLAYER_PHONE: _player(player_id, PLAYER_PHONE)})
    service, _ = build(store)

    with pytest.raises(ValueError, match="zero"):
        await service.adjust(
            actor_id=ADMIN_ID,
            target_identifier=PLAYER_PHONE,
            amount=0,
            note="no-op",
            ip=None,
        )


@pytest.mark.asyncio
async def test_an_empty_note_is_refused() -> None:
    player_id = uuid4()
    store = Store(users={PLAYER_PHONE: _player(player_id, PLAYER_PHONE)})
    service, _ = build(store)

    with pytest.raises(ValueError, match="note"):
        await service.adjust(
            actor_id=ADMIN_ID,
            target_identifier=PLAYER_PHONE,
            amount=50,
            note="   ",
            ip=None,
        )


@pytest.mark.asyncio
async def test_two_submissions_are_not_deduplicated() -> None:
    """Documents the known gap: unlike redemption, there is no natural
    idempotency key for a manual admin action, so calling ``adjust`` twice
    (for example a resubmitted form) applies twice."""
    player_id = uuid4()
    store = Store(users={PLAYER_PHONE: _player(player_id, PLAYER_PHONE)})
    service, store = build(store)

    await service.adjust(
        actor_id=ADMIN_ID,
        target_identifier=PLAYER_PHONE,
        amount=100,
        note="bonus",
        ip=None,
    )
    await service.adjust(
        actor_id=ADMIN_ID,
        target_identifier=PLAYER_PHONE,
        amount=100,
        note="bonus",
        ip=None,
    )

    assert store.wallets[player_id] == 200
    assert len(store.ledger) == 2
    assert store.ledger[0].idempotency_key != store.ledger[1].idempotency_key
