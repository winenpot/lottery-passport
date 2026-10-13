"""Redemption against real PostgreSQL: atomicity, concurrency, constraints.

These are the tests that prove the invariants in docs/ARCHITECTURE.md:
one code -> at most one award, ledger rows are immutable, balances never go
negative, and the daily cap holds when requests arrive at the same time.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.app import create_app
from app.application.redemption_codes import (
    RedemptionError,
    RedemptionErrorCode,
    RedemptionResult,
    RedemptionService,
)
from app.application.unit_of_work import InsufficientCoinsError, UnitOfWork
from app.core.config import Settings
from app.domain.code_batches import BatchStatus
from app.domain.codes import generate_code
from app.domain.ledger import LedgerReason, NewLedgerEntry
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    CodeBatchModel,
    CoinLedgerEntryModel,
    PassportProgressModel,
    RedemptionCodeModel,
    WalletModel,
)
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.sms import ConsoleSmsSender
from scripts.code_batches import set_status
from scripts.generate_codes import insert_codes

PEPPER = "integration-test-pepper"
TEHRAN = ZoneInfo("Asia/Tehran")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


def make_service(
    database: PostgreSQLAdapter, daily_limit: int = 20
) -> RedemptionService:
    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory)

    return RedemptionService(
        unit_of_work=unit_of_work,
        clock=SystemClock(),
        pepper=PEPPER,
        daily_limit=daily_limit,
        campaign_zone=TEHRAN,
    )


async def create_user(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"it-{uuid4().hex}@example.com", datetime.now(UTC))
    return user.id


async def create_batch(
    database: PostgreSQLAdapter,
    city: CityCode = CityCode.TOKYO,
    *,
    status: BatchStatus = BatchStatus.ACTIVE,
    coins: int = 10,
    count: int = 1,
) -> tuple[UUID, list[str]]:
    batch_id = uuid4()
    now = datetime.now(UTC)
    async with database.session_factory() as session, session.begin():
        session.add(
            CodeBatchModel(
                id=batch_id,
                city=city.value,
                label="integration test",
                quantity=count,
                coins_per_code=coins,
                status=status.value,
                created_at=now,
            )
        )
    codes = [generate_code(city) for _ in range(count)]
    inserted = await insert_codes(
        database.session_factory, batch_id, city, codes, PEPPER, now
    )
    assert len(inserted) == count
    return batch_id, codes


async def scalar(database: PostgreSQLAdapter, statement: Any) -> Any:
    async with database.session_factory() as session:
        return await session.scalar(statement)


async def ledger_rows_for(database: PostgreSQLAdapter, user_id: UUID) -> int:
    count = await scalar(
        database,
        select(func.count()).where(CoinLedgerEntryModel.user_id == user_id),
    )
    return int(count)


async def wallet_balance(database: PostgreSQLAdapter, user_id: UUID) -> int:
    balance = await scalar(
        database, select(WalletModel.balance).where(WalletModel.user_id == user_id)
    )
    return int(balance or 0)


async def test_redeem_commits_claim_entry_ledger_and_wallet_together(
    database: PostgreSQLAdapter,
) -> None:
    user = await create_user(database)
    _, (code,) = await create_batch(database, CityCode.MOSCOW, coins=25)

    result = await make_service(database).redeem(user, code)

    assert (result.city, result.city_entries, result.coin_balance) == (
        CityCode.MOSCOW,
        1,
        25,
    )
    redeemer = await scalar(
        database,
        select(RedemptionCodeModel.redeemed_by_user_id).where(
            RedemptionCodeModel.redeemed_by_user_id == user
        ),
    )
    points = await scalar(
        database,
        select(PassportProgressModel.points).where(
            PassportProgressModel.user_id == user
        ),
    )
    assert redeemer == user
    assert points == 1
    assert await ledger_rows_for(database, user) == 1
    assert await wallet_balance(database, user) == 25


async def test_many_users_racing_for_one_code_award_it_exactly_once(
    database: PostgreSQLAdapter,
) -> None:
    service = make_service(database)
    users = [await create_user(database) for _ in range(12)]
    _, (code,) = await create_batch(database, coins=10)

    outcomes = await asyncio.gather(
        *(service.redeem(user, code) for user in users), return_exceptions=True
    )

    winners = [o for o in outcomes if isinstance(o, RedemptionResult)]
    losers = [o for o in outcomes if isinstance(o, RedemptionError)]
    assert len(winners) == 1
    assert len(losers) == 11
    assert {e.code for e in losers} == {RedemptionErrorCode.ALREADY_REDEEMED}
    balances = [await wallet_balance(database, user) for user in users]
    assert sorted(balances) == [0] * 11 + [10]


class GatedCommitUnitOfWork(SqlAlchemyUnitOfWork):
    """Holds its transaction open (row locks included) until ``gate`` is set."""

    def __init__(self, database: PostgreSQLAdapter, gate: asyncio.Event) -> None:
        super().__init__(database.session_factory)
        self._gate = gate

    async def commit(self) -> None:
        await self._gate.wait()
        await super().commit()


async def wait_for_lock_waiters(database: PostgreSQLAdapter, expected: int) -> None:
    query = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
    )
    for _ in range(200):
        async with database.session_factory() as session:
            if (await session.scalar(query) or 0) >= expected:
                return
        await asyncio.sleep(0.02)
    raise AssertionError("the rival transaction never blocked on the row lock")


async def test_a_rival_blocked_on_the_row_lock_loses_after_the_winner_commits(
    database: PostgreSQLAdapter,
) -> None:
    # Deterministic version of the race: the winner has claimed the code and
    # is about to commit; the rival's UPDATE must block on the row lock, then
    # re-check "redeemed_at IS NULL" and find nothing to claim.
    gate = asyncio.Event()
    winner_user, rival_user = await create_user(database), await create_user(database)
    _, (code,) = await create_batch(database, coins=10)
    winner_service = RedemptionService(
        unit_of_work=lambda: GatedCommitUnitOfWork(database, gate),
        clock=SystemClock(),
        pepper=PEPPER,
        daily_limit=20,
        campaign_zone=TEHRAN,
    )

    winner = asyncio.create_task(winner_service.redeem(winner_user, code))
    await asyncio.sleep(0.2)  # the winner now holds the code row lock
    rival = asyncio.create_task(make_service(database).redeem(rival_user, code))
    await wait_for_lock_waiters(database, expected=1)
    gate.set()

    assert (await winner).replayed is False
    with pytest.raises(RedemptionError) as lost:
        await rival
    assert lost.value.code is RedemptionErrorCode.ALREADY_REDEEMED
    assert await wallet_balance(database, rival_user) == 0


async def test_double_submit_by_the_same_user_is_idempotent(
    database: PostgreSQLAdapter,
) -> None:
    service = make_service(database)
    user = await create_user(database)
    _, (code,) = await create_batch(database, coins=10)

    outcomes = await asyncio.gather(*(service.redeem(user, code) for _ in range(6)))

    assert sum(1 for o in outcomes if not o.replayed) == 1
    assert all(o.coin_balance == 10 for o in outcomes)
    assert await ledger_rows_for(database, user) == 1
    assert await wallet_balance(database, user) == 10


async def test_daily_limit_holds_under_concurrent_requests(
    database: PostgreSQLAdapter,
) -> None:
    service = make_service(database, daily_limit=3)
    user = await create_user(database)
    _, codes = await create_batch(database, coins=5, count=8)

    outcomes = await asyncio.gather(
        *(service.redeem(user, code) for code in codes), return_exceptions=True
    )

    accepted = [o for o in outcomes if isinstance(o, RedemptionResult)]
    refused = [o for o in outcomes if isinstance(o, RedemptionError)]
    assert len(accepted) == 3
    assert {e.code for e in refused} == {RedemptionErrorCode.DAILY_LIMIT}
    assert len(refused) == 5
    assert await wallet_balance(database, user) == 15
    redeemed = await scalar(
        database,
        select(func.count()).where(RedemptionCodeModel.redeemed_by_user_id == user),
    )
    assert redeemed == 3  # refused claims were rolled back


async def test_codes_work_only_while_their_batch_is_active(
    database: PostgreSQLAdapter,
) -> None:
    service = make_service(database)
    user = await create_user(database)
    batch_id, (code, spare) = await create_batch(
        database, status=BatchStatus.GENERATED, count=2
    )

    with pytest.raises(RedemptionError) as not_yet:
        await service.redeem(user, code)
    assert not_yet.value.code is RedemptionErrorCode.INVALID

    assert await set_status(database.session_factory, batch_id, BatchStatus.ACTIVE)
    assert (await service.redeem(user, code)).replayed is False

    assert await set_status(database.session_factory, batch_id, BatchStatus.VOID)
    with pytest.raises(RedemptionError) as voided:
        await service.redeem(user, spare)
    assert voided.value.code is RedemptionErrorCode.INVALID
    # A code redeemed before the void stays redeemed for its owner.
    assert (await service.redeem(user, code)).replayed is True


async def test_void_batch_cannot_be_reactivated(database: PostgreSQLAdapter) -> None:
    batch_id, _ = await create_batch(database, status=BatchStatus.VOID)

    assert not await set_status(database.session_factory, batch_id, BatchStatus.ACTIVE)


async def test_ledger_rows_cannot_be_updated_or_deleted(
    database: PostgreSQLAdapter,
) -> None:
    user = await create_user(database)
    _, (code,) = await create_batch(database)
    await make_service(database).redeem(user, code)

    for statement in (
        "UPDATE coin_ledger_entries SET amount = 1000 WHERE user_id = :user",
        "DELETE FROM coin_ledger_entries WHERE user_id = :user",
    ):
        async with database.session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(text(statement), {"user": user})


async def test_idempotency_key_is_enforced_by_the_database(
    database: PostgreSQLAdapter,
) -> None:
    user = await create_user(database)
    entry = NewLedgerEntry(
        user_id=user,
        amount=50,
        reason=LedgerReason.ADMIN_ADJUSTMENT,
        idempotency_key=f"test:{uuid4()}",
        created_at=datetime.now(UTC),
    )
    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        await uow.ledger.lock_wallet(user, entry.created_at)
        await uow.ledger.record(entry)
        await uow.commit()

    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
            await uow.ledger.lock_wallet(user, entry.created_at)
            await uow.ledger.record(entry)
            await uow.commit()
    assert await wallet_balance(database, user) == 50


async def test_spending_more_than_the_balance_is_refused_and_rolled_back(
    database: PostgreSQLAdapter,
) -> None:
    user = await create_user(database)
    now = datetime.now(UTC)

    with pytest.raises(InsufficientCoinsError):
        async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
            await uow.ledger.lock_wallet(user, now)
            await uow.ledger.record(
                NewLedgerEntry(
                    user_id=user,
                    amount=-1,
                    reason=LedgerReason.STORE_PURCHASE,
                    idempotency_key=f"test:{uuid4()}",
                    created_at=now,
                )
            )
            await uow.commit()

    assert await ledger_rows_for(database, user) == 0


async def test_redemption_api_end_to_end(test_database_url: str) -> None:
    settings = Settings(
        database_url=test_database_url,
        redemption_code_pepper=PEPPER,
        cors_origins="*",
        _env_file=None,
    )
    database = PostgreSQLAdapter(settings)
    try:
        _, (code,) = await create_batch(database, CityCode.TOKYO, coins=10)
    finally:
        await database.dispose()
    application = create_app(settings)
    identifier = f"+989{uuid4().int % 10**9:09d}"

    with TestClient(application, headers={"X-Requested-With": "test"}) as client:
        client.post("/api/v1/auth/request", json={"identifier": identifier})
        sender = application.state.sms_sender
        assert isinstance(sender, ConsoleSmsSender)
        client.post(
            "/api/v1/auth/verify",
            json={"identifier": identifier, "code": sender.last_code},
        )

        too_early = client.post("/api/v1/redemptions", json={"code": code})
        profile = client.patch(
            "/api/v1/me",
            json={
                "nickname": f"T{uuid4().hex[:10]}",
                "accept_terms_version": settings.terms_version,
            },
        )

        first = client.post("/api/v1/redemptions", json={"code": code.lower()})
        replay = client.post("/api/v1/redemptions", json={"code": code})
        garbage = client.post("/api/v1/redemptions", json={"code": "hello"})
        wallet = client.get("/api/v1/me/wallet")
        passports = client.get("/api/v1/me/passports")

    assert too_early.status_code == 403
    assert too_early.json()["error"]["code"] == "TERMS_NOT_ACCEPTED"
    assert profile.status_code == 200
    assert first.status_code == 200
    assert first.json() == {
        "city": "tokyo",
        "entries_added": 1,
        "city_entries": 1,
        "coins_awarded": 10,
        "coin_balance": 10,
        "replayed": False,
    }
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert garbage.status_code == 400
    assert garbage.json()["error"]["code"] == "CODE_MALFORMED"
    assert wallet.json()["balance"] == 10
    assert wallet.json()["recent"][0]["reason"] == "code_redemption"
    assert passports.json()[0]["campaign"] == "tokyo"
    assert passports.json()[0]["points"] == 1


def test_redemption_requires_a_session() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.post("/api/v1/redemptions", json={"code": "x"})

    assert response.status_code == 401
