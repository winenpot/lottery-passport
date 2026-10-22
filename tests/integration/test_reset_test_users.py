"""scripts.reset_test_users against a real database: the launch-day reset.

Every safety check must fire BEFORE any row is touched (proven by re-reading
the table afterwards), and the happy path must delete exactly the users not
in the keep-list while leaving redemption_codes/code_batches untouched.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import delete, insert, select, update

from app.core.config import Settings
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    CoinLedgerEntryModel,
    RedemptionCodeModel,
    UserModel,
    WalletModel,
)
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from scripts.generate_codes import generate_batch
from scripts.reset_test_users import ResetRefused, reset

PEPPER = "reset-test-users-pepper"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _asyncpg_dsn(sqlalchemy_url: str, *, dbname: str) -> str:
    url = sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


@pytest.fixture(scope="module")
def _scratch_database_url() -> Iterator[str]:
    """A throwaway database dedicated to this module.

    ``check_safe_to_reset`` reads GLOBAL counts across the whole database
    (any redeemed code, any ledger/wallet/audit row) -- unlike every other
    test in this suite, which only ever reads rows scoped to its own data.
    The CI job runs every integration test module against one shared
    Postgres instance with no per-module cleanup, and two of those global
    counts (``coin_ledger_entries``, ``audit_log``) can never be cleared
    once written: a database trigger permanently rejects UPDATE/DELETE on
    them, the same append-only guarantee production relies on. So this
    module provisions its own database, migrated with the real alembic
    chain (so the triggers are genuinely present), and drops it afterwards.

    Reads ``TEST_DATABASE_URL`` directly rather than depending on
    ``conftest.py``'s ``test_database_url`` fixture: that fixture is
    function-scoped (it calls ``pytest.skip``, which must happen per test),
    and a module-scoped fixture cannot depend on a function-scoped one.
    """
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        if os.getenv("CI"):
            pytest.fail("TEST_DATABASE_URL is required in CI")
        pytest.skip("TEST_DATABASE_URL is required for the PostgreSQL integration test")

    db_name = f"lp_reset_test_{uuid4().hex[:12]}"
    admin_dsn = _asyncpg_dsn(base_url, dbname="postgres")
    new_url = base_url.rsplit("/", 1)[0] + f"/{db_name}"

    async def create() -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
        finally:
            await conn.close()

    async def drop() -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                db_name,
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        finally:
            await conn.close()

    asyncio.run(create())
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT),
        env={**os.environ, "DATABASE_URL": new_url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        asyncio.run(drop())
        raise RuntimeError(
            f"alembic upgrade head failed for the scratch database {db_name!r}:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    try:
        yield new_url
    finally:
        asyncio.run(drop())


@pytest.fixture
async def database(_scratch_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=_scratch_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


@pytest.fixture(autouse=True)
async def _reset_between_tests(database: PostgreSQLAdapter) -> None:
    """Clear only what's safe to clear between tests in this module.

    ``wallets`` and ``redemption_codes.redeemed_at`` have no append-only
    trigger, so each test starts from a known-empty state regardless of
    execution order. ``coin_ledger_entries``/``audit_log`` are never
    touched here -- they cannot be, by design -- so the two tests that
    write to them (wallet test, then ledger test) rely on running in that
    order, which is this file's normal top-to-bottom order; no test
    reorder plugin is installed in this project.
    """
    async with database.session_factory() as session:
        await session.execute(update(RedemptionCodeModel).values(redeemed_at=None))
        await session.execute(delete(WalletModel))
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
