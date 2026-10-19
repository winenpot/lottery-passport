"""The batch lifecycle CLI against real PostgreSQL: export, freeze, history."""

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.app import create_app
from app.application.redemption_codes import PepperMismatchError, pepper_fingerprint
from app.core.config import Settings
from app.domain.code_batches import BatchEventType, BatchStatus
from app.domain.codes import (
    V2_B10,
    CodeFormat,
    FormatRegistryError,
    register_format,
    unregister_format,
)
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import CodeBatchEventModel, CodeBatchModel
from scripts.code_batches import (
    batch_history,
    freeze_batch,
    list_batches,
    list_formats,
    set_status,
)
from scripts.generate_codes import generate_batch

PEPPER = "batch-lifecycle-test-pepper"


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


async def make_batch(
    database: PostgreSQLAdapter, tmp_path: Path, name: str, format_id: str = "v2-b10"
) -> UUID:
    output = tmp_path / f"{name}.csv"
    return await generate_batch(
        database.session_factory,
        city=CityCode.PARIS,
        quantity=1,
        coins_per_code=0,
        label=name,
        base_url="https://play.example.ir",
        output=output,
        pepper=PEPPER,
        format_id=format_id,
    )


async def test_generating_a_batch_records_a_generated_event(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    batch_id = await make_batch(database, tmp_path, "gen")

    lines = await batch_history(database.session_factory, batch_id)

    assert len(lines) == 1
    assert "generated" in lines[0]


async def test_export_freezes_the_format_and_stores_the_checksum(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    batch_id = await make_batch(database, tmp_path, "export")
    checksum = hashlib.sha256(b"printer file").hexdigest()

    changed = await freeze_batch(
        database.session_factory, batch_id, export_sha256=checksum
    )

    assert changed is True
    async with database.session_factory() as session:
        batch = await session.get(CodeBatchModel, batch_id)
    assert batch is not None
    assert batch.frozen_at is not None
    assert batch.exported_at is not None
    assert batch.export_sha256 == checksum
    assert batch.format_fingerprint == V2_B10.fingerprint()

    lines = await batch_history(database.session_factory, batch_id)
    assert any("exported" in line for line in lines)


async def test_freezing_twice_is_a_no_op_and_stays_consistent(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    batch_id = await make_batch(database, tmp_path, "double-freeze")

    first = await freeze_batch(database.session_factory, batch_id)
    second = await freeze_batch(database.session_factory, batch_id)

    assert first is True
    assert second is True
    lines = await batch_history(database.session_factory, batch_id)
    assert sum(1 for line in lines if "frozen" in line) == 1


async def test_freezing_an_unknown_batch_returns_false(
    database: PostgreSQLAdapter,
) -> None:
    assert await freeze_batch(database.session_factory, uuid4()) is False


async def test_activate_and_void_record_events(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    batch_id = await make_batch(database, tmp_path, "lifecycle")

    assert await set_status(database.session_factory, batch_id, BatchStatus.ACTIVE)
    assert await set_status(database.session_factory, batch_id, BatchStatus.VOID)

    lines = await batch_history(database.session_factory, batch_id)
    kinds = [line.split()[1] for line in lines]
    assert kinds == [
        BatchEventType.GENERATED.value,
        BatchEventType.ACTIVATED.value,
        BatchEventType.VOIDED.value,
    ]


async def test_batch_events_table_is_append_only(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    batch_id = await make_batch(database, tmp_path, "append-only")
    async with database.session_factory() as session:
        event_id = await session.scalar(
            select(CodeBatchEventModel.id).where(
                CodeBatchEventModel.batch_id == batch_id
            )
        )
        with pytest.raises(Exception, match="append-only"):
            await session.execute(
                update(CodeBatchEventModel)
                .where(CodeBatchEventModel.id == event_id)
                .values(detail="tampered")
            )
            await session.commit()


async def test_list_batches_shows_format_and_frozen_state(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    batch_id = await make_batch(database, tmp_path, "listing")
    await freeze_batch(database.session_factory, batch_id)

    lines = await list_batches(database.session_factory)

    matching = [line for line in lines if str(batch_id) in line]
    assert len(matching) == 1
    assert "format=v2-b10" in matching[0]
    assert "frozen=yes" in matching[0]


async def test_list_formats_includes_every_registered_format() -> None:
    extra = CodeFormat(format_id="listing-test", body_length=3, grouping=(2, 2))
    register_format(extra)
    try:
        lines = list_formats()
        assert any(line.startswith("v2-b10") for line in lines)
        assert any(line.startswith("listing-test") for line in lines)
    finally:
        unregister_format("listing-test")


async def test_frozen_batch_formats_reports_only_frozen_rows(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    unfrozen_id = await make_batch(database, tmp_path, "unfrozen")
    frozen_id = await make_batch(database, tmp_path, "frozen")
    await freeze_batch(database.session_factory, frozen_id)

    pairs = await database.frozen_batch_formats()

    assert (V2_B10.format_id, V2_B10.fingerprint()) in pairs
    async with database.session_factory() as session:
        unfrozen = await session.get(CodeBatchModel, unfrozen_id)
    assert unfrozen is not None and unfrozen.frozen_at is None


async def test_app_startup_fails_loudly_when_a_frozen_format_has_drifted(
    database: PostgreSQLAdapter, tmp_path: Path, test_database_url: str
) -> None:
    """A tampered/renamed format must block startup, not fail silently."""
    batch_id = await make_batch(database, tmp_path, "drifted")
    await freeze_batch(database.session_factory, batch_id)
    correct_fingerprint = V2_B10.fingerprint()
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(CodeBatchModel)
            .where(CodeBatchModel.id == batch_id)
            .values(format_fingerprint="0" * 64)
        )
    try:
        settings = Settings(database_url=test_database_url, _env_file=None)
        with (
            pytest.raises(FormatRegistryError, match="has changed since it was frozen"),
            TestClient(create_app(settings)),
        ):
            pass
    finally:
        # This row is shared, real database state: every other test that
        # boots the app against the same database runs this startup check
        # too, so a tampered fingerprint must never outlive this test.
        async with database.session_factory() as session, session.begin():
            await session.execute(
                update(CodeBatchModel)
                .where(CodeBatchModel.id == batch_id)
                .values(format_fingerprint=correct_fingerprint)
            )


async def test_active_batch_peppers_reports_only_active_rows(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    generated_id = await make_batch(database, tmp_path, "pepper-generated")
    active_id = await make_batch(database, tmp_path, "pepper-active")
    try:
        assert await set_status(database.session_factory, active_id, BatchStatus.ACTIVE)

        rows = await database.active_batch_peppers()

        assert (active_id, CityCode.PARIS.value, pepper_fingerprint(PEPPER)) in rows
        assert generated_id not in {row[0] for row in rows}
    finally:
        # Shared, real database state (see the format-drift test above): an
        # ACTIVE batch's fingerprint is only ever correct for THIS file's
        # own PEPPER, so it would fail another test file's startup check
        # (a different pepper string) against this same database.
        await set_status(database.session_factory, active_id, BatchStatus.VOID)


async def test_app_startup_fails_loudly_when_an_active_batch_pepper_has_drifted(
    database: PostgreSQLAdapter, tmp_path: Path, test_database_url: str
) -> None:
    """A batch printed under a different pepper must block startup, not fail

    one redemption at a time as CODE_INVALID.
    """
    batch_id = await make_batch(database, tmp_path, "pepper-drifted")
    assert await set_status(database.session_factory, batch_id, BatchStatus.ACTIVE)

    try:
        settings = Settings(
            database_url=test_database_url,
            redemption_code_pepper="a-completely-different-pepper",
            _env_file=None,
        )
        with (
            pytest.raises(PepperMismatchError, match=str(batch_id)),
            TestClient(create_app(settings)),
        ):
            pass
    finally:
        # Shared, real database state (see the format-drift test above): an
        # ACTIVE batch's fingerprint is only ever correct for THIS file's
        # own PEPPER, so it would fail another test file's startup check
        # (a different pepper string) against this same database.
        await set_status(database.session_factory, batch_id, BatchStatus.VOID)


async def test_app_startup_passes_when_the_pepper_matches(
    database: PostgreSQLAdapter, tmp_path: Path, test_database_url: str
) -> None:
    batch_id = await make_batch(database, tmp_path, "pepper-matching")
    assert await set_status(database.session_factory, batch_id, BatchStatus.ACTIVE)

    try:
        settings = Settings(
            database_url=test_database_url,
            redemption_code_pepper=PEPPER,
            _env_file=None,
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").status_code == 200
    finally:
        await set_status(database.session_factory, batch_id, BatchStatus.VOID)


async def test_ready_rejects_a_pepper_mismatch_distinctly_from_a_down_database(
    database: PostgreSQLAdapter, tmp_path: Path, test_database_url: str
) -> None:
    """Startup only runs once; /ready must keep catching drift on every poll."""
    batch_id = await make_batch(database, tmp_path, "pepper-ready")
    assert await set_status(database.session_factory, batch_id, BatchStatus.ACTIVE)

    try:
        # A pepper that passes at boot (so startup does not already refuse
        # to serve), then drifted in storage afterwards -- the only way to
        # reach /ready's own check instead of startup's.
        settings = Settings(
            database_url=test_database_url,
            redemption_code_pepper=PEPPER,
            _env_file=None,
        )
        with TestClient(create_app(settings)) as client:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    update(CodeBatchModel)
                    .where(CodeBatchModel.id == batch_id)
                    .values(pepper_fingerprint=pepper_fingerprint("a-rotated-pepper"))
                )
            response = client.get("/ready")

        assert response.status_code == 503
        assert response.json()["error"]["message"] == (
            "an active code batch's pepper does not match the configured pepper"
        )
    finally:
        # Shared, real database state (see the format-drift test above): a
        # batch left ACTIVE with a fingerprint that matches no real pepper
        # would fail every other test's startup check against this database.
        await set_status(database.session_factory, batch_id, BatchStatus.VOID)
