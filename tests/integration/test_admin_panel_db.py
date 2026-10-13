"""The admin panel against PostgreSQL: real sign-in, every view renders."""

import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.app import create_app
from app.core.config import Settings
from app.infrastructure.sms import ConsoleSmsSender

VIEW_PATHS = (
    "/admin/user-model/list",
    "/admin/venue-model/list",
    "/admin/code-batch-model/list",
    "/admin/wallet-model/list",
    "/admin/coin-ledger-entry-model/list",
)


@pytest.mark.asyncio
async def test_an_admin_signs_in_by_sms_and_sees_every_view(
    test_database_url: str,
) -> None:
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)
    phone = "+989" + "".join(str(random.randint(0, 9)) for _ in range(9))
    sender = application.state.sms_sender
    assert isinstance(sender, ConsoleSmsSender)

    with TestClient(application, follow_redirects=False) as client:
        # A player first: the panel must refuse them without sending an SMS.
        client.post(
            "/api/v1/auth/request",
            json={"identifier": phone},
            headers={"X-Requested-With": "test"},
        )
        sender.last_code = None
        client.post("/admin/login", data={"action": "send", "phone": phone})
        assert sender.last_code is None
        assert client.get("/admin/").status_code in {302, 303, 307}

        # Own engine: the app's pool lives on the TestClient's event loop.
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE users SET role = 'admin' WHERE identifier = :phone"),
                {"phone": phone},
            )
        try:
            # The player's cooldown from above still applies to this number.
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM authentication_challenges WHERE user_id = "
                        "(SELECT id FROM users WHERE identifier = :phone)"
                    ),
                    {"phone": phone},
                )
            sent = client.post("/admin/login", data={"action": "send", "phone": phone})
            assert "step=code" in sent.headers["location"]
            assert sender.last_code is not None
            done = client.post(
                "/admin/login", data={"action": "verify", "code": sender.last_code}
            )
            assert done.status_code == 302

            for path in VIEW_PATHS:
                page = client.get(path)
                assert page.status_code == 200, path
            assert phone in client.get("/admin/user-model/list").text
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET role = 'player' WHERE identifier = :phone"),
                    {"phone": phone},
                )
            await engine.dispose()
