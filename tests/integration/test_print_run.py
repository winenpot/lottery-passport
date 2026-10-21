"""Weighted print runs against real PostgreSQL: quota, files, rollback."""

import csv
import json
import stat
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.application.redemption_codes import hash_redemption_code
from app.core.config import Settings
from app.domain.code_batches import BatchStatus
from app.domain.codes import generate_code, parse_code
from app.domain.passports import CityCode
from app.domain.print_runs import QuotaExceededError, parse_weights
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import CodeBatchModel, RedemptionCodeModel
from scripts.print_run import issued_per_city, run_print_run

PEPPER = "print-run-test-pepper"
BASE_URL = "https://torshx.com"


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


async def issued(database: PostgreSQLAdapter) -> dict[CityCode, int]:
    async with database.engine.connect() as connection:
        return await issued_per_city(connection)


def read_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))[1:]


async def test_a_run_creates_one_frozen_batch_and_shuffled_csv_per_flavor(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    before = await issued(database)
    output_dir = tmp_path / "run"

    result = await run_print_run(
        database.engine,
        database.session_factory,
        k=100,
        weights=parse_weights("TO=0.6,PR=0.4"),
        coins_per_code=100,
        base_url=BASE_URL,
        output_dir=output_dir,
        pepper=PEPPER,
        quota_per_sku=max(before.values()) + 1000,
    )

    assert {b.city: b.quantity for b in result.batches} == {
        CityCode.PARIS: 40,
        CityCode.TOKYO: 60,
    }
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    after = await issued(database)
    assert after[CityCode.TOKYO] == before[CityCode.TOKYO] + 60
    assert after[CityCode.MOSCOW] == before[CityCode.MOSCOW]

    for batch in result.batches:
        csv_path = output_dir / batch.csv_name
        assert stat.S_IMODE(csv_path.stat().st_mode) == 0o600
        rows = read_rows(csv_path)
        codes = [row[3] for row in rows]
        assert len(set(codes)) == batch.quantity
        assert codes != sorted(codes)  # 1 in 40! of failing by chance
        assert all(parse_code(code).city is batch.city for code in codes)
        assert rows[0][4] == f"{BASE_URL}/b/{rows[0][2]}"
        async with database.session_factory() as session:
            row = await session.get(CodeBatchModel, batch.batch_id)
            stored = await session.scalar(
                select(RedemptionCodeModel.batch_id).where(
                    RedemptionCodeModel.code_hash
                    == hash_redemption_code(codes[0], PEPPER)
                )
            )
        assert row is not None
        assert row.status == BatchStatus.GENERATED.value  # not redeemable yet
        assert row.coins_per_code == 100
        assert row.export_sha256 == batch.sha256 and row.frozen_at is not None
        assert row.label.startswith(f"{result.run_id} ")
        assert stored == batch.batch_id

    manifest_path = output_dir / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert manifest["allocation"]["TO"] == 60
    assert manifest["weights"]["TO"] == "3/5"
    first_code = read_rows(output_dir / result.batches[0].csv_name)[0][3]
    assert first_code not in manifest_text  # the manifest never holds codes


async def test_a_run_past_any_flavors_quota_is_refused_before_writing_anything(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    before = await issued(database)
    output_dir = tmp_path / "refused"
    # Tokyo has 3 left; the run wants 4 Tokyo codes (and 4 Paris codes).

    with pytest.raises(QuotaExceededError, match="TO wants 4 but has 3 left"):
        await run_print_run(
            database.engine,
            database.session_factory,
            k=8,
            weights=parse_weights("TO=0.5,PR=0.5"),
            coins_per_code=100,
            base_url=BASE_URL,
            output_dir=output_dir,
            pepper=PEPPER,
            quota_per_sku=before[CityCode.TOKYO] + 3,
        )

    assert not output_dir.exists()
    assert await issued(database) == before


async def test_runs_repeat_until_the_flavor_is_used_up_then_stop(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    before = await issued(database)
    quota = before[CityCode.MOSCOW] + 5
    weights = parse_weights("MO=1")

    for name in ("one", "two"):  # 3 codes, then the last 2 (taking the last is OK)
        await run_print_run(
            database.engine,
            database.session_factory,
            k=3 if name == "one" else 2,
            weights=weights,
            coins_per_code=0,
            base_url=BASE_URL,
            output_dir=tmp_path / name,
            pepper=PEPPER,
            quota_per_sku=quota,
        )

    with pytest.raises(QuotaExceededError, match="MO wants 1 but has 0 left"):
        await run_print_run(
            database.engine,
            database.session_factory,
            k=1,
            weights=weights,
            coins_per_code=0,
            base_url=BASE_URL,
            output_dir=tmp_path / "three",
            pepper=PEPPER,
            quota_per_sku=quota,
        )
    assert (await issued(database))[CityCode.MOSCOW] == quota


async def test_a_failure_half_way_voids_the_runs_batches_and_deletes_its_files(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    before = await issued(database)
    output_dir = tmp_path / "broken"
    started = datetime.now(UTC)

    def generate(city: CityCode) -> str:
        if city is CityCode.TOKYO:  # Paris (earlier in order) succeeds first
            raise RuntimeError("printer file disk full")
        return generate_code(city)

    with pytest.raises(RuntimeError, match="disk full"):
        await run_print_run(
            database.engine,
            database.session_factory,
            k=10,
            weights=parse_weights("PR=1/2,TO=1/2"),
            coins_per_code=100,
            base_url=BASE_URL,
            output_dir=output_dir,
            pepper=PEPPER,
            quota_per_sku=max(before.values()) + 1000,
            generate=generate,
        )

    assert [p.name for p in output_dir.iterdir()] == []
    async with database.session_factory() as session:
        statuses = (
            await session.execute(
                select(CodeBatchModel.city, CodeBatchModel.status).where(
                    CodeBatchModel.created_at >= started
                )
            )
        ).all()
    # Both the finished Paris batch and the half-made Tokyo batch are void.
    assert sorted(statuses) == [
        (CityCode.PARIS.value, BatchStatus.VOID.value),
        (CityCode.TOKYO.value, BatchStatus.VOID.value),
    ]
