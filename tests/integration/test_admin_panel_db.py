"""The admin panel against PostgreSQL: real sign-in, every view renders."""

import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.app import create_app
from app.core.config import Settings
from app.infrastructure.postgres.database import is_pgbouncer_url
from app.infrastructure.postgres.models import AuditLogModel, VenueModel
from app.infrastructure.sms import ConsoleSmsSender


def _random_known_prefix_phone() -> str:
    """A fresh number on a known allocated range (app/domain/phone.py), so
    it never trips the unusual-prefix guard in AuthenticationService."""
    return "+98912" + "".join(str(random.randint(0, 9)) for _ in range(7))


VIEW_PATHS = (
    "/admin/user-model/list",
    "/admin/venue-model/list",
    "/admin/code-batch-model/list",
    "/admin/wallet-model/list",
    "/admin/coin-ledger-entry-model/list",
    "/admin/legal-document-model/list",
)


def _pgbouncer_safe_engine(database_url: str):
    # PgBouncer (Supabase's transaction-pooler, port 6543) does not support
    # named prepared statements; without this, a second engine opened in
    # the same test run intermittently fails with "prepared statement
    # already exists" (app/infrastructure/postgres/database.py has the
    # same guard for the app's own engine).
    connect_args: dict[str, object] = {}
    if is_pgbouncer_url(database_url):
        connect_args["statement_cache_size"] = 0
    return create_async_engine(
        database_url, poolclass=NullPool, connect_args=connect_args
    )


@pytest.mark.asyncio
async def test_an_admin_signs_in_by_sms_and_sees_every_view(
    test_database_url: str,
) -> None:
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)
    # Outside the 0969 test-number range (app/application/otp_test_numbers.py):
    # those never reach ConsoleSmsSender, since the dev/demo OTP response
    # carries the code back directly instead.
    phone = _random_known_prefix_phone()
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
        engine = _pgbouncer_safe_engine(settings.database_url)
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


@pytest.mark.asyncio
async def test_editing_a_lounge_writes_an_audit_row(test_database_url: str) -> None:
    """B20 step 2: SQLAdmin's own audit backend, wired to our audit_log."""
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)
    phone = _random_known_prefix_phone()
    sender = application.state.sms_sender
    assert isinstance(sender, ConsoleSmsSender)
    engine = _pgbouncer_safe_engine(settings.database_url)
    venue_id = f"audit-{uuid4().hex}"

    with TestClient(application, follow_redirects=False) as client:
        client.post(
            "/api/v1/auth/request",
            json={"identifier": phone},
            headers={"X-Requested-With": "test"},
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET role = 'admin' WHERE identifier = :phone"),
                    {"phone": phone},
                )
                await connection.execute(
                    text(
                        "DELETE FROM authentication_challenges WHERE user_id = "
                        "(SELECT id FROM users WHERE identifier = :phone)"
                    ),
                    {"phone": phone},
                )
                await connection.execute(
                    VenueModel.__table__.insert().values(
                        id=venue_id,
                        name="CI audit test lounge",
                        city="tehran",
                        active=True,
                        created_at=datetime.now(UTC),
                    )
                )
            client.post("/admin/login", data={"action": "send", "phone": phone})
            assert sender.last_code is not None
            done = client.post(
                "/admin/login", data={"action": "verify", "code": sender.last_code}
            )
            assert done.status_code == 302

            edited = client.post(
                f"/admin/venue-model/edit/{venue_id}",
                data={"name": "Integration test lounge", "active": "true"},
            )
            assert edited.status_code == 302

            async with engine.begin() as connection:
                name = (
                    await connection.execute(
                        select(VenueModel.name).where(VenueModel.id == venue_id)
                    )
                ).scalar_one()
                assert name == "Integration test lounge"
                rows = (
                    await connection.execute(
                        select(AuditLogModel.action, AuditLogModel.changes).where(
                            AuditLogModel.entity == "venue-model",
                            AuditLogModel.entity_id == venue_id,
                        )
                    )
                ).all()
            assert any(
                action == "update"
                and (changes or {}).get("name") == "Integration test lounge"
                for action, changes in rows
            )
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET role = 'player' WHERE identifier = :phone"),
                    {"phone": phone},
                )
                await connection.execute(
                    text("DELETE FROM venues WHERE id = :id"), {"id": venue_id}
                )
            await engine.dispose()


# Every view whose rows an admin creates, and the key field the admin types.
CREATABLE = {
    "avatar-model": "id",
    "reward-rule-model": "key",
    "challenge-model": "id",
    "achievement-model": "id",
    "legal-document-model": "version",
}
# Tables behind the four catalogue views above, and their key column.
TABLES = (
    ("avatars", "id"),
    ("reward_rules", "key"),
    ("challenges", "id"),
    ("achievements", "id"),
)


@pytest.mark.asyncio
async def test_create_forms_show_the_key_and_every_catalogue_can_be_filled(
    test_database_url: str,
) -> None:
    """SQLAdmin hides primary-key columns from forms unless the view sets
    ``form_include_pk``, and the forms never show timestamps; every catalogue
    here has an admin-typed key and a NOT NULL timestamp, so before both
    fixes nothing could be created from the panel at all."""
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)
    phone = _random_known_prefix_phone()
    sender = application.state.sms_sender
    assert isinstance(sender, ConsoleSmsSender)
    engine = _pgbouncer_safe_engine(settings.database_url)
    row_id = f"t-{uuid4().hex[:12]}"

    with TestClient(application, follow_redirects=False) as client:
        client.post(
            "/api/v1/auth/request",
            json={"identifier": phone},
            headers={"X-Requested-With": "test"},
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET role = 'admin' WHERE identifier = :phone"),
                    {"phone": phone},
                )
                await connection.execute(
                    text(
                        "DELETE FROM authentication_challenges WHERE user_id = "
                        "(SELECT id FROM users WHERE identifier = :phone)"
                    ),
                    {"phone": phone},
                )
            client.post("/admin/login", data={"action": "send", "phone": phone})
            assert sender.last_code is not None
            done = client.post(
                "/admin/login", data={"action": "verify", "code": sender.last_code}
            )
            assert done.status_code == 302

            for identity, key in CREATABLE.items():
                form = client.get(f"/admin/{identity}/create")
                assert form.status_code == 200, identity
                assert f'name="{key}"' in form.text, identity

            # Inactive (BooleanField omitted = false), so no other test sees them.
            payloads = {
                "avatar-model": {
                    "id": row_id,
                    "image_url": "https://play.torshx.com/avatars/test.png",
                    "sort": "0",
                },
                "reward-rule-model": {"key": row_id, "amount": "5", "cadence": "once"},
                "challenge-model": {
                    "id": row_id,
                    "kind": "daily_checkin",
                    "period": "day",
                    "target": "1",
                    "reward_coins": "5",
                },
                "achievement-model": {
                    "id": row_id,
                    "fact": "checkin_streak",
                    "threshold": "3",
                    "reward_coins": "5",
                },
            }
            for identity, data in payloads.items():
                created = client.post(f"/admin/{identity}/create", data=data)
                assert created.status_code == 302, (identity, created.text[-500:])
            async with engine.begin() as connection:
                for table, key in TABLES:
                    stored = (
                        await connection.execute(
                            text(f"SELECT count(*) FROM {table} WHERE {key} = :id"),
                            {"id": row_id},
                        )
                    ).scalar_one()
                    assert stored == 1, table
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET role = 'player' WHERE identifier = :phone"),
                    {"phone": phone},
                )
                for table, key in TABLES:
                    await connection.execute(
                        text(f"DELETE FROM {table} WHERE {key} = :id"), {"id": row_id}
                    )
            await engine.dispose()
