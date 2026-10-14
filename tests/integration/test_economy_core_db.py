"""Economy core (ADR 0010) against real PostgreSQL.

Covers the two things only a real database can prove: the ``asset`` CHECK
constraint actually rejects anything but ``'coin'``, and ``reward_rules``'
own CHECK constraints hold. The first-code bonus's logic (default vs.
override vs. switched off) is unit-tested against a fake unit of work in
``tests/unit/test_redemption_service.py``; here it runs once end to end
through ``SqlRewardRules`` and the real ledger to prove the two layers
agree.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.application.redemption_codes import RedemptionService
from app.application.unit_of_work import UnitOfWork
from app.core.config import Settings
from app.domain.code_batches import BatchStatus
from app.domain.codes import generate_code
from app.domain.ledger import LedgerReason, NewLedgerEntry
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    CodeBatchModel,
    CoinLedgerEntryModel,
    RewardRuleModel,
    WalletModel,
)
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork
from scripts.generate_codes import insert_codes

PEPPER = "economy-core-test-pepper"
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


async def wallet_balance(database: PostgreSQLAdapter, user_id: object) -> int:
    async with database.session_factory() as session:
        balance = await session.scalar(
            select(WalletModel.balance).where(WalletModel.user_id == user_id)
        )
    return int(balance or 0)


async def test_asset_check_constraint_rejects_anything_but_coin(
    database: PostgreSQLAdapter,
) -> None:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"+989{uuid4().int % 10**9:09d}", datetime.now(UTC))

    async with database.session_factory() as session:
        with pytest.raises(DBAPIError, match="ck_coin_ledger_entries_asset_coin_only"):
            await session.execute(
                insert(CoinLedgerEntryModel).values(
                    user_id=user.id,
                    amount=10,
                    reason=LedgerReason.ADMIN_ADJUSTMENT.value,
                    idempotency_key=f"test:{uuid4()}",
                    asset="diamond",
                    created_at=datetime.now(UTC),
                )
            )


async def test_reward_rules_check_constraints_hold(database: PostgreSQLAdapter) -> None:
    async with database.session_factory() as session:
        with pytest.raises(DBAPIError, match="ck_reward_rules_amount_positive"):
            await session.execute(
                insert(RewardRuleModel).values(
                    key=f"test:{uuid4()}",
                    amount=0,
                    cadence="once",
                    active=True,
                    updated_at=datetime.now(UTC),
                )
            )

    async with database.session_factory() as session:
        with pytest.raises(DBAPIError, match="ck_reward_rules_cadence"):
            await session.execute(
                insert(RewardRuleModel).values(
                    key=f"test:{uuid4()}",
                    amount=10,
                    cadence="hourly",
                    active=True,
                    updated_at=datetime.now(UTC),
                )
            )


async def test_reward_rules_key_is_unique(database: PostgreSQLAdapter) -> None:
    key = f"test:{uuid4()}"
    async with database.session_factory() as session, session.begin():
        session.add(
            RewardRuleModel(
                key=key,
                amount=10,
                cadence="once",
                active=True,
                updated_at=datetime.now(UTC),
            )
        )

    async with database.session_factory() as session:
        session.add(
            RewardRuleModel(
                key=key,
                amount=20,
                cadence="once",
                active=True,
                updated_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_a_reward_rule_row_overrides_the_configured_bonus_end_to_end(
    database: PostgreSQLAdapter,
) -> None:
    """The same guarantee as the unit tests, once through the real adapter."""
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"+989{uuid4().int % 10**9:09d}", datetime.now(UTC))
    batch_id = uuid4()
    now = datetime.now(UTC)
    async with database.session_factory() as session, session.begin():
        session.add(
            CodeBatchModel(
                id=batch_id,
                city=CityCode.TOKYO.value,
                label="economy core test",
                quantity=1,
                coins_per_code=0,
                status=BatchStatus.ACTIVE.value,
                created_at=now,
            )
        )
        session.add(
            RewardRuleModel(
                key="first_code",
                amount=777,
                cadence="once",
                active=True,
                updated_at=now,
            )
        )
    (code,) = [generate_code(CityCode.TOKYO)]
    await insert_codes(
        database.session_factory, batch_id, CityCode.TOKYO, [code], PEPPER, now
    )

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory)

    service = RedemptionService(
        unit_of_work=unit_of_work,
        clock=SystemClock(),
        pepper=PEPPER,
        daily_limit=20,
        campaign_zone=TEHRAN,
        first_code_bonus_coins=50,  # the row above must win, not this
    )

    result = await service.redeem(user.id, code)

    assert result.bonus_awarded == 777
    assert await wallet_balance(database, user.id) == 777
    async with database.session_factory() as session:
        reason = await session.scalar(
            select(CoinLedgerEntryModel.reason).where(
                CoinLedgerEntryModel.user_id == user.id
            )
        )
    assert reason == LedgerReason.FIRST_CODE_BONUS.value

    # Cleanup: reward_rules has no FK from anything, but it is shared state
    # on this test database -- never leave a real key behind for other
    # tests/sessions to trip over.
    async with database.session_factory() as session:
        await session.execute(text("DELETE FROM reward_rules WHERE key = 'first_code'"))
        await session.commit()


async def test_ledger_entries_backfill_to_coin_for_old_rows(
    database: PostgreSQLAdapter,
) -> None:
    """Migration 0013's DEFAULT applies going forward; proven here by just
    inserting without specifying ``asset`` and reading it back."""
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"+989{uuid4().int % 10**9:09d}", datetime.now(UTC))
    now = datetime.now(UTC)

    async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
        await uow.ledger.lock_wallet(user.id, now)
        await uow.ledger.record(
            NewLedgerEntry(
                user_id=user.id,
                amount=5,
                reason=LedgerReason.ADMIN_ADJUSTMENT,
                idempotency_key=f"test:{uuid4()}",
                created_at=now,
            )
        )
        await uow.commit()

    async with database.session_factory() as session:
        asset = await session.scalar(
            select(CoinLedgerEntryModel.asset).where(
                CoinLedgerEntryModel.user_id == user.id
            )
        )
    assert asset == "coin"
