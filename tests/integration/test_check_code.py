"""check_code.py against real PostgreSQL: lookup only, never a write."""

import csv
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update

from app.application.redemption_codes import hash_redemption_code
from app.core.config import Settings
from app.domain.codes import parse_code
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import CodeBatchModel, RedemptionCodeModel
from scripts.check_code import lookup_code, main_async
from scripts.generate_codes import generate_batch

PEPPER = "check-code-test-pepper"
OTHER_PEPPER = "a-different-pepper-entirely"


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


async def generate_one(
    database: PostgreSQLAdapter,
    tmp_path: Path,
    *,
    city: CityCode,
    label: str,
    pepper: str = PEPPER,
) -> tuple[str, str]:
    """Generate a 1-code batch, return (batch_id as str, printed code)."""
    output = tmp_path / f"{label.replace(' ', '-')}.csv"
    batch_id = await generate_batch(
        database.session_factory,
        city=city,
        quantity=1,
        coins_per_code=5,
        label=label,
        base_url="https://play.example.ir",
        output=output,
        pepper=pepper,
    )
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    printed = rows[1][2]
    return str(batch_id), printed


async def test_an_unknown_but_well_formed_code_is_not_found(
    database: PostgreSQLAdapter,
) -> None:
    unknown_hash = hash_redemption_code(parse_code("TO-HA1-NQC-C32").canonical, PEPPER)

    found = await lookup_code(database.session_factory, unknown_hash, PEPPER)

    assert found is None


async def test_a_fresh_unredeemed_code_reports_its_batch_and_no_redemption(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    batch_id, printed = await generate_one(
        database, tmp_path, city=CityCode.PARIS, label="fresh lookup"
    )
    code_hash = hash_redemption_code(parse_code(printed).canonical, PEPPER)

    found = await lookup_code(database.session_factory, code_hash, PEPPER)

    assert found is not None
    assert found.city == CityCode.PARIS.value
    assert str(found.batch_id) == batch_id
    assert found.batch_label == "fresh lookup"
    assert found.batch_status == "generated"
    assert found.redeemed_at is None
    assert found.pepper_matches is True


async def test_a_redeemed_code_reports_when_it_was_redeemed(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    _, printed = await generate_one(
        database, tmp_path, city=CityCode.MADRID, label="redeemed lookup"
    )
    code_hash = hash_redemption_code(parse_code(printed).canonical, PEPPER)
    redeemed_at = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    async with database.session_factory() as session:
        await session.execute(
            update(RedemptionCodeModel)
            .where(RedemptionCodeModel.code_hash == code_hash)
            .values(redeemed_at=redeemed_at)
        )
        await session.commit()

    found = await lookup_code(database.session_factory, code_hash, PEPPER)

    assert found is not None
    assert found.redeemed_at == redeemed_at


async def test_a_pepper_mismatch_is_reported_instead_of_a_false_not_found(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    """A corrupted/hand-edited pepper_fingerprint column, not a wrong pepper.

    Using the wrong pepper to check a code fails the hash lookup outright
    (see test_an_unknown_but_well_formed_code_is_not_found) -- it never
    reaches pepper_matches at all. The only way pepper_matches is False is
    for the fingerprint COLUMN to disagree with the very pepper that just
    proved itself correct by matching the hash -- simulated here directly,
    since generate_batch always keeps the two in sync by construction.
    """
    _, printed = await generate_one(
        database,
        tmp_path,
        city=CityCode.BERLIN,
        label="wrong pepper lookup",
        pepper=OTHER_PEPPER,
    )
    code_hash = hash_redemption_code(parse_code(printed).canonical, OTHER_PEPPER)

    found = await lookup_code(database.session_factory, code_hash, PEPPER)

    assert found is not None
    assert found.pepper_matches is False


async def test_a_legacy_batch_with_no_stamped_fingerprint_matches_as_unknown(
    database: PostgreSQLAdapter, tmp_path: Path
) -> None:
    _, printed = await generate_one(
        database, tmp_path, city=CityCode.MOSCOW, label="legacy lookup"
    )
    code_hash = hash_redemption_code(parse_code(printed).canonical, PEPPER)
    async with database.session_factory() as session:
        await session.execute(
            update(CodeBatchModel)
            .where(CodeBatchModel.id == RedemptionCodeModel.batch_id)
            .where(RedemptionCodeModel.code_hash == code_hash)
            .values(pepper_fingerprint=None)
        )
        await session.commit()

    found = await lookup_code(database.session_factory, code_hash, PEPPER)

    assert found is not None
    assert found.pepper_matches is None


async def test_main_async_rejects_a_malformed_code_before_touching_anything(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No TEST_DATABASE_URL / REDEMPTION_CODE_PEPPER needed: parse_code()
    # raises before main_async ever reaches the database or the pepper.
    exit_code = await main_async("not even code shaped")

    assert exit_code == 1
    assert "MALFORMED" in capsys.readouterr().err
