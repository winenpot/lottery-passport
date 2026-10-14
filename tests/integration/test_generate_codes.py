"""The batch generator against real PostgreSQL."""

import csv
import hashlib
import itertools
import stat
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.application.redemption_codes import hash_redemption_code
from app.core.config import Settings
from app.domain.code_batches import BatchStatus
from app.domain.codes import generate_code, parse_code
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import CodeBatchModel, RedemptionCodeModel
from scripts.generate_codes import CSV_HEADER, INSERT_CHUNK, generate_batch

PEPPER = "generator-test-pepper"


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


def read_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


async def test_batch_spanning_chunks_stores_hashes_and_writes_private_csv(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    output = tmp_path / "paris.csv"
    quantity = INSERT_CHUNK + 37

    batch_id = await generate_batch(
        database.session_factory,
        city=CityCode.PARIS,
        quantity=quantity,
        coins_per_code=10,
        label="test run",
        base_url="https://play.example.ir/",
        output=output,
        pepper=PEPPER,
    )

    rows = read_rows(output)
    assert rows[0] == CSV_HEADER
    body = rows[1:]
    assert len(body) == quantity
    assert len({row[3] for row in body}) == quantity
    for _, city, printed, code, url in body[:50]:
        assert city == "PARIS"
        assert parse_code(printed).canonical == code
        assert url == f"https://play.example.ir/b/{printed}"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    assert (tmp_path / "paris.csv.sha256").read_text().startswith(digest)

    async with database.session_factory() as session:
        stored = await session.scalar(
            select(func.count()).where(RedemptionCodeModel.batch_id == batch_id)
        )
        batch = await session.get(CodeBatchModel, batch_id)
        sample_hash = hash_redemption_code(body[0][3], PEPPER)
        found = await session.scalar(
            select(RedemptionCodeModel.id).where(
                RedemptionCodeModel.code_hash == sample_hash
            )
        )
    assert stored == quantity
    assert batch is not None and batch.status == BatchStatus.GENERATED.value
    assert found is not None


async def test_codes_that_already_exist_are_replaced_not_duplicated(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    first_output = tmp_path / "first.csv"
    await generate_batch(
        database.session_factory,
        city=CityCode.TOKYO,
        quantity=1,
        coins_per_code=0,
        label="existing",
        base_url="https://play.example.ir",
        output=first_output,
        pepper=PEPPER,
    )
    existing = read_rows(first_output)[1][3]
    # The second run's generator first returns the code that already exists.
    sequence = itertools.chain(
        [existing], iter(lambda: generate_code(CityCode.TOKYO), None)
    )
    second_output = tmp_path / "second.csv"

    batch_id = await generate_batch(
        database.session_factory,
        city=CityCode.TOKYO,
        quantity=5,
        coins_per_code=0,
        label="collision",
        base_url="https://play.example.ir",
        output=second_output,
        pepper=PEPPER,
        generate=lambda _: next(sequence),
    )

    codes = [row[3] for row in read_rows(second_output)[1:]]
    assert len(codes) == 5
    assert existing not in codes
    async with database.session_factory() as session:
        stored = await session.scalar(
            select(func.count()).where(RedemptionCodeModel.batch_id == batch_id)
        )
    assert stored == 5


async def test_refuses_to_overwrite_an_existing_file_before_touching_the_database(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    output = tmp_path / "exists.csv"
    output.write_text("do not overwrite\n", encoding="utf-8")
    async with database.session_factory() as session:
        batches_before = await session.scalar(select(func.count(CodeBatchModel.id)))

    with pytest.raises(FileExistsError):
        await generate_batch(
            database.session_factory,
            city=CityCode.TOKYO,
            quantity=1,
            coins_per_code=0,
            label="should not exist",
            base_url="https://play.example.ir",
            output=output,
            pepper=PEPPER,
        )

    async with database.session_factory() as session:
        batches_after = await session.scalar(select(func.count(CodeBatchModel.id)))
    assert batches_after == batches_before
    assert output.read_text(encoding="utf-8") == "do not overwrite\n"
