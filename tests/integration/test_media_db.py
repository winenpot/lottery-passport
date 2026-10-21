"""Admin image upload (W10) against real Postgres: the repository
adapter's content-addressed dedup, and the full admin "Images" page ->
``GET /media/{sha256}.{ext}`` round trip over HTTP.
"""

import random
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.app import create_app
from app.core.config import Settings
from app.domain.media import MediaContentType, NewMediaAsset
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.repositories import PostgreSQLMediaAssets
from app.infrastructure.sms import ConsoleSmsSender

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def _random_known_prefix_phone() -> str:
    return "+98912" + "".join(str(random.randint(0, 9)) for _ in range(7))


@pytest.fixture
async def database(test_database_url: str) -> AsyncGenerator[PostgreSQLAdapter]:
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    adapter = PostgreSQLAdapter(settings)
    yield adapter
    await adapter.dispose()


async def test_put_if_absent_dedups_identical_bytes_by_sha256(
    database: PostgreSQLAdapter,
) -> None:
    repo = PostgreSQLMediaAssets(database.session_factory)
    sha256 = f"{uuid4().hex}{uuid4().hex[:32]}"  # fake but unique, 64 hex-ish chars
    new_asset = NewMediaAsset(
        sha256=sha256,
        content_type=MediaContentType.PNG,
        data=PNG_BYTES,
        created_by_user_id=None,
    )
    try:
        first = await repo.put_if_absent(new_asset)
        second = await repo.put_if_absent(new_asset)

        assert first == second
        assert first.byte_size == len(PNG_BYTES)

        fetched = await repo.get(sha256)
        assert fetched is not None
        assert fetched.data == PNG_BYTES
        assert fetched.content_type == MediaContentType.PNG
    finally:
        async with database.session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM media_assets WHERE sha256 = :sha256"),
                {"sha256": sha256},
            )


async def test_get_is_none_for_an_unknown_hash(database: PostgreSQLAdapter) -> None:
    repo = PostgreSQLMediaAssets(database.session_factory)

    assert await repo.get("0" * 64) is None


async def test_admin_uploads_an_image_and_a_player_fetches_it_back(
    test_database_url: str,
) -> None:
    """The full round trip the plan's "Done when" describes: upload in
    /admin, get back a URL, that URL serves the exact bytes with no sign-in."""
    settings = Settings(database_url=test_database_url, _env_file=None)  # type: ignore[call-arg]
    application = create_app(settings)
    phone = _random_known_prefix_phone()
    sender = application.state.sms_sender
    assert isinstance(sender, ConsoleSmsSender)
    database = PostgreSQLAdapter(settings)

    with TestClient(application, follow_redirects=False) as client:
        client.post(
            "/api/v1/auth/request",
            json={"identifier": phone},
            headers={"X-Requested-With": "test"},
        )
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text("UPDATE users SET role = 'admin' WHERE identifier = :phone"),
                    {"phone": phone},
                )
                await session.execute(
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

            page = client.get("/admin/images")
            assert page.status_code == 200

            uploaded = client.post(
                "/admin/images", files={"file": ("test.png", PNG_BYTES, "image/png")}
            )
            assert uploaded.status_code == 200
            assert "/media/" in uploaded.text
            start = uploaded.text.index("/media/")
            url = uploaded.text[start : start + len("/media/") + 64 + 4]

            served = client.get(url)
            assert served.status_code == 200
            assert served.content == PNG_BYTES
            assert served.headers["content-type"] == "image/png"

            # Re-uploading the same bytes is a no-op, not a second row.
            reuploaded = client.post(
                "/admin/images", files={"file": ("again.png", PNG_BYTES, "image/png")}
            )
            assert reuploaded.status_code == 200
            assert url in reuploaded.text

            too_big = client.post(
                "/admin/images",
                files={
                    "file": ("big.png", PNG_BYTES + b"\x00" * (512 * 1024), "image/png")
                },
            )
            assert too_big.status_code == 200
            assert "512 KB" in too_big.text

            svg = client.post(
                "/admin/images",
                files={
                    "file": ("x.svg", b"<svg><script>1</script></svg>", "image/svg+xml")
                },
            )
            assert svg.status_code == 200
            assert "PNG, JPEG or WebP" in svg.text
        finally:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text("UPDATE users SET role = 'player' WHERE identifier = :phone"),
                    {"phone": phone},
                )
            await database.dispose()
