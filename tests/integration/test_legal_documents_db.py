"""Terms & privacy (LG1') against PostgreSQL: the seeded draft, the freeze
trigger once a player accepted a version, and the admin tab end to end."""

import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.app import create_app
from app.core.config import Settings
from app.infrastructure.postgres.database import PostgreSQLAdapter, is_pgbouncer_url
from app.infrastructure.postgres.repositories import (
    PostgreSQLLegalDocuments,
    PostgreSQLUserRepository,
)
from app.infrastructure.sms import ConsoleSmsSender

SEED_VERSION = "2026-10-20"


def _phone() -> str:
    # A known allocated range, so the admin sign-in never trips PHONE_UNUSUAL.
    return "+98912" + "".join(str(random.randint(0, 9)) for _ in range(7))


def _engine(database_url: str) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    if is_pgbouncer_url(database_url):
        connect_args["statement_cache_size"] = 0
    return create_async_engine(
        database_url, poolclass=NullPool, connect_args=connect_args
    )


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


@pytest.fixture
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    created = _engine(test_database_url)
    try:
        yield created
    finally:
        await created.dispose()


async def _insert_document(engine: AsyncEngine, version: str, body: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO legal_documents (version, body) VALUES (:v, :b)"),
            {"v": version, "b": body},
        )


async def _accept(engine: AsyncEngine, user_id: UUID, version: str | None) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE users SET terms_version = :v WHERE id = :id"),
            {"v": version, "id": user_id},
        )


async def _delete_document(engine: AsyncEngine, version: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM legal_documents WHERE version = :v"), {"v": version}
        )


async def test_the_first_draft_is_seeded_ready_to_edit(
    database: PostgreSQLAdapter,
) -> None:
    seeded = await PostgreSQLLegalDocuments(database.session_factory).get(SEED_VERSION)

    assert seeded is not None
    assert seeded.body.startswith("# قوانین و شرایط استفاده و حریم خصوصی TorshX")
    assert "{#terms}" in seeded.body
    assert "{#privacy}" in seeded.body
    assert "\u0654" not in seeded.body


async def test_an_unaccepted_version_can_be_edited(engine: AsyncEngine) -> None:
    version = f"t-{uuid4().hex[:12]}"
    await _insert_document(engine, version, "draft")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE legal_documents SET body = 'draft 2' WHERE version = :v"),
                {"v": version},
            )
    finally:
        await _delete_document(engine, version)


async def test_a_version_a_player_accepted_is_frozen(
    database: PostgreSQLAdapter, engine: AsyncEngine
) -> None:
    version = f"t-{uuid4().hex[:12]}"
    await _insert_document(engine, version, "accepted text")
    user = await PostgreSQLUserRepository(database.session_factory).create(
        _phone(), datetime.now(UTC)
    )
    await _accept(engine, user.id, version)
    try:
        for statement in (
            "UPDATE legal_documents SET body = 'changed' WHERE version = :v",
            "DELETE FROM legal_documents WHERE version = :v",
        ):
            with pytest.raises(DBAPIError, match="was accepted by players"):
                async with engine.begin() as connection:
                    await connection.execute(text(statement), {"v": version})
    finally:
        await _accept(engine, user.id, None)
        await _delete_document(engine, version)


async def test_the_admin_tab_edits_text_until_a_player_accepts_it(
    test_database_url: str, engine: AsyncEngine
) -> None:
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)
    sender = application.state.sms_sender
    assert isinstance(sender, ConsoleSmsSender)
    phone = _phone()
    version = f"t-{uuid4().hex[:12]}"
    await _insert_document(engine, version, "first text")

    with TestClient(application, follow_redirects=False) as client:
        client.post(
            "/api/v1/auth/request",
            json={"identifier": phone},
            headers={"X-Requested-With": "test"},
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET role = 'admin' WHERE identifier = :p"),
                    {"p": phone},
                )
                await connection.execute(
                    text(
                        "DELETE FROM authentication_challenges WHERE user_id = "
                        "(SELECT id FROM users WHERE identifier = :p)"
                    ),
                    {"p": phone},
                )
            client.post("/admin/login", data={"action": "send", "phone": phone})
            assert sender.last_code is not None
            signed_in = client.post(
                "/admin/login", data={"action": "verify", "code": sender.last_code}
            )
            assert signed_in.status_code == 302

            listing = client.get("/admin/legal-document-model/list")
            assert listing.status_code == 200
            create_form = client.get("/admin/legal-document-model/create")
            assert 'name="version"' in create_form.text
            form = client.get(f"/admin/legal-document-model/edit/{version}")
            assert form.status_code == 200
            assert 'dir="rtl"' in form.text

            edited = client.post(
                f"/admin/legal-document-model/edit/{version}",
                data={"version": version, "body": "## متن تازه {#privacy}"},
            )
            assert edited.status_code == 302
            page = client.get(f"/legal/{version}")
            assert page.status_code == 200
            assert '<h2 id="privacy">متن تازه</h2>' in page.text

            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET terms_version = :v WHERE identifier = :p"),
                    {"v": version, "p": phone},
                )
            refused = client.post(
                f"/admin/legal-document-model/edit/{version}",
                data={"version": version, "body": "changed after acceptance"},
            )
            assert refused.status_code == 400
            assert "can no longer change" in refused.text
            assert "متن تازه" in client.get(f"/legal/{version}").text
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE users SET role = 'player', terms_version = NULL "
                        "WHERE identifier = :p"
                    ),
                    {"p": phone},
                )
            await _delete_document(engine, version)
