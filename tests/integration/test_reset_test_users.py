"""scripts.reset_test_users against a real database: the launch-day reset.

Every safety check must fire BEFORE any row is touched (proven by re-reading
the table afterwards), and the happy path must delete exactly the users not
in the keep-list while leaving redemption_codes/code_batches untouched.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, update

from app.core.config import Settings
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    AuditLogModel,
    CoinLedgerEntryModel,
    RedemptionCodeModel,
    UserModel,
    WalletModel,
)
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from scripts.generate_codes import generate_batch
from scripts.reset_test_users import ResetRefused, reset

PEPPER = "reset-test-users-pepper"


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


@pytest.fixture(autouse=True)
async def _isolated_reset_state(database: PostgreSQLAdapter) -> None:
    """Scrub exactly the state ``check_safe_to_reset`` looks at.

    The integration suite shares one real Postgres instance across every
    module in a CI run, with no per-module cleanup (none of the other
    integration tests isolate themselves either). ``check_safe_to_reset``
    is unlike every other test in this suite: it reads GLOBAL counts
    (any redeemed code, any ledger/wallet/audit row), not rows scoped to
    one test's own data. Without this, a code redeemed by an unrelated
    module (for example ``test_redemption_flow.py``) makes every
    refusal test in this file observe the wrong count and fail on the
    "already redeemed" branch instead of the one it is asserting on.
    """
    async with database.session_factory() as session:
        await session.execute(update(RedemptionCodeModel).values(redeemed_at=None))
        await session.execute(delete(CoinLedgerEntryModel))
        await session.execute(delete(WalletModel))
        await session.execute(delete(AuditLogModel))
        await session.commit()


async def make_user(database: PostgreSQLAdapter, last4: str) -> str:
    identifier = f"+9891{uuid4().hex[:6]}{last4}"
    users = PostgreSQLUserRepository(database.session_factory)
    await users.create(identifier, datetime.now(UTC))
    return identifier


async def test_deletes_everyone_except_the_kept_suffixes(
    database: PostgreSQLAdapter,
) -> None:
    keep_a = await make_user(database, "9098")
    keep_b = await make_user(database, "4789")
    await make_user(database, "5804")
    await make_user(database, "3990")

    kept, deleted = await reset(database.session_factory, ["9098", "4789"])

    assert deleted == 2
    assert set(kept.values()) == {keep_a, keep_b}
    async with database.session_factory() as session:
        remaining = (
            (await session.execute(select(UserModel.identifier))).scalars().all()
        )
    assert set(remaining) == {keep_a, keep_b}


async def test_a_suffix_matching_no_one_is_refused_before_any_delete(
    database: PostgreSQLAdapter,
) -> None:
    kept = await make_user(database, "9098")

    with pytest.raises(ResetRefused, match="0 user"):
        await reset(database.session_factory, ["0000"])

    async with database.session_factory() as session:
        remaining = (
            (await session.execute(select(UserModel.identifier))).scalars().all()
        )
    assert remaining == [kept]


async def test_a_suffix_matching_two_users_is_refused(
    database: PostgreSQLAdapter,
) -> None:
    await make_user(database, "9098")
    await make_user(database, "9098")

    with pytest.raises(ResetRefused, match="2 user"):
        await reset(database.session_factory, ["9098"])


async def test_refuses_when_a_code_is_already_redeemed(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    await make_user(database, "9098")
    batch_id = await generate_batch(
        database.session_factory,
        city=CityCode.PARIS,
        quantity=1,
        coins_per_code=5,
        label="reset test batch",
        base_url="https://play.example.ir",
        output=tmp_path / "codes.csv",
        pepper=PEPPER,
    )
    async with database.session_factory() as session:
        # Scoped to this test's own batch: an unscoped UPDATE here would mark
        # every redemption_codes row in the shared CI database as redeemed,
        # corrupting every other integration test that runs in the same job.
        await session.execute(
            update(RedemptionCodeModel)
            .where(RedemptionCodeModel.batch_id == batch_id)
            .values(redeemed_at=datetime.now(UTC))
        )
        await session.commit()

    with pytest.raises(ResetRefused, match="redeemed"):
        await reset(database.session_factory, ["9098"])


async def test_refuses_when_a_wallet_exists(database: PostgreSQLAdapter) -> None:
    identifier = await make_user(database, "9098")
    async with database.session_factory() as session:
        user_id = await session.scalar(
            select(UserModel.id).where(UserModel.identifier == identifier)
        )
        await session.execute(
            insert(WalletModel).values(
                user_id=user_id,
                balance=0,
                lifetime_earned=0,
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    with pytest.raises(ResetRefused, match="wallets"):
        await reset(database.session_factory, ["9098"])


async def test_refuses_when_a_ledger_entry_exists(database: PostgreSQLAdapter) -> None:
    identifier = await make_user(database, "9098")
    async with database.session_factory() as session:
        user_id = await session.scalar(
            select(UserModel.id).where(UserModel.identifier == identifier)
        )
        await session.execute(
            insert(CoinLedgerEntryModel).values(
                user_id=user_id,
                amount=5,
                reason="code_redeemed",
                source_id="reset-test",
                idempotency_key=f"reset-test-{uuid4().hex}",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    with pytest.raises(ResetRefused, match="coin_ledger_entries"):
        await reset(database.session_factory, ["9098"])
