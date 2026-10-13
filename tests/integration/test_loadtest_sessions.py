"""The load-test session generator: usable sessions, refuses production."""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings
from app.infrastructure.postgres.database import PostgreSQLAdapter
from scripts.loadtest_sessions import (
    count_active_loadtest_users,
    create_sessions,
    deactivate,
    refuse_production,
)


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


def test_refuses_to_run_in_production() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://app:secret@postgres:5432/db",
        redemption_code_pepper="p" * 48,
        admin_session_secret="a" * 48,
        _env_file=None,
    )

    with pytest.raises(SystemExit):
        refuse_production(settings)


async def test_generated_sessions_authenticate_and_can_be_revoked(
    database: PostgreSQLAdapter, test_database_url: str
) -> None:
    (token,) = await create_sessions(database.session_factory, 1, timedelta(hours=1))
    application = create_app(Settings(database_url=test_database_url, _env_file=None))

    with TestClient(application) as client:
        client.cookies.set("lottery_passport_session", token)
        before = client.get("/api/v1/me")
        assert await count_active_loadtest_users(database.session_factory) >= 1
        await deactivate(database.session_factory)
        after = client.get("/api/v1/me")

    assert before.status_code == 200
    assert before.json()["identifier"].startswith("loadtest:")
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "AUTH_REQUIRED"
    assert await count_active_loadtest_users(database.session_factory) == 0
