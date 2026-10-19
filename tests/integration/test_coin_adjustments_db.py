"""The admin "Adjust coins" page against real PostgreSQL.

Proves B20 step 3: a coin adjustment writes the ledger entry, the wallet
balance and the audit row in ONE transaction, and that audit_log really is
append-only (migration 0012), the same guarantee as coin_ledger_entries.
"""

import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.app import create_app
from app.core.config import Settings
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    AuditLogModel,
    CoinLedgerEntryModel,
    WalletModel,
)
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository
from app.infrastructure.sms import ConsoleSmsSender


def random_phone() -> str:
    """A fresh Iranian-shaped mobile number, on a known allocated range
    (``app/domain/phone.py``) and outside the 0969 test-number range
    (``app/application/otp_test_numbers.py``): those never go through
    ``ConsoleSmsSender``, since the dev/demo OTP response carries the code
    back directly instead."""
    return "+98912" + "".join(str(random.randint(0, 9)) for _ in range(7))


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


async def sign_in_as_admin(
    client: TestClient, application: object, database: PostgreSQLAdapter
) -> str:
    """Promote a fresh phone to admin and sign it into the panel."""
    phone = random_phone()
    sender = application.state.sms_sender  # type: ignore[attr-defined]
    assert isinstance(sender, ConsoleSmsSender)
    client.post(
        "/api/v1/auth/request",
        json={"identifier": phone},
        headers={"X-Requested-With": "test"},
    )
    async with database.session_factory() as session:
        await session.execute(
            text("UPDATE users SET role = 'admin' WHERE identifier = :phone"),
            {"phone": phone},
        )
        await session.commit()
    # The player-signup cooldown from the request above still applies to
    # this number; clear it so the admin "send" below is not blocked too.
    async with database.session_factory() as session:
        await session.execute(
            text(
                "DELETE FROM authentication_challenges WHERE user_id = "
                "(SELECT id FROM users WHERE identifier = :phone)"
            ),
            {"phone": phone},
        )
        await session.commit()
    client.post("/admin/login", data={"action": "send", "phone": phone})
    assert sender.last_code is not None
    done = client.post(
        "/admin/login", data={"action": "verify", "code": sender.last_code}
    )
    assert done.status_code == 302
    return phone


async def ledger_rows_for(database: PostgreSQLAdapter, user_id: UUID) -> int:
    async with database.session_factory() as session:
        count = await session.scalar(
            select(func.count()).where(CoinLedgerEntryModel.user_id == user_id)
        )
    return int(count or 0)


async def audit_rows_for(database: PostgreSQLAdapter, entity_id: str) -> list[dict]:
    async with database.session_factory() as session:
        rows = (
            await session.execute(
                select(AuditLogModel).where(AuditLogModel.entity_id == entity_id)
            )
        ).scalars()
        return [
            {"action": row.action, "entity": row.entity, "changes": row.changes}
            for row in rows
        ]


@pytest.mark.asyncio
async def test_a_coin_adjustment_commits_ledger_wallet_and_audit_together(
    test_database_url: str, database: PostgreSQLAdapter
) -> None:
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)

    with TestClient(application, follow_redirects=False) as client:
        await sign_in_as_admin(client, application, database)
        users = PostgreSQLUserRepository(database.session_factory)
        player = await users.create(random_phone(), datetime.now(UTC))

        response = client.post(
            "/admin/coin-adjustments",
            data={
                "identifier": player.identifier,
                "amount": "250",
                "note": "integration test bonus",
            },
        )

        assert response.status_code == 303
        assert await ledger_rows_for(database, player.id) == 1
        async with database.session_factory() as session:
            balance = await session.scalar(
                select(WalletModel.balance).where(WalletModel.user_id == player.id)
            )
        assert balance == 250
        rows = await audit_rows_for(database, str(player.id))
        assert len(rows) == 1
        assert rows[0]["action"] == "create"
        assert rows[0]["entity"] == "coin_ledger_entry"
        assert rows[0]["changes"]["amount"] == 250
        assert rows[0]["changes"]["note"] == "integration test bonus"


@pytest.mark.asyncio
async def test_an_unknown_phone_number_adjusts_nothing(
    test_database_url: str, database: PostgreSQLAdapter
) -> None:
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)

    with TestClient(application, follow_redirects=False) as client:
        await sign_in_as_admin(client, application, database)

        response = client.post(
            "/admin/coin-adjustments",
            data={
                "identifier": random_phone(),
                "amount": "100",
                "note": "typo'd number",
            },
        )

        assert response.status_code == 303  # redirects back with a flash error


@pytest.mark.asyncio
async def test_audit_log_rejects_update_and_delete(database: PostgreSQLAdapter) -> None:
    users = PostgreSQLUserRepository(database.session_factory)
    actor = await users.create(random_phone(), datetime.now(UTC))
    async with database.session_factory() as session:
        row = AuditLogModel(
            actor_user_id=actor.id,
            action="create",
            entity="probe",
            entity_id="x",
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()
        row_id = row.id

    async with database.session_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE audit_log SET action = 'update' WHERE id = :id"),
                {"id": row_id},
            )
            await session.commit()

    async with database.session_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("DELETE FROM audit_log WHERE id = :id"), {"id": row_id}
            )
            await session.commit()

    async with database.session_factory() as session:
        surviving = await session.scalar(
            select(AuditLogModel.action).where(AuditLogModel.id == row_id)
        )
    assert surviving == "create"
