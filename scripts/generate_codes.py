"""Generate one print batch of v2 product codes (see docs/CODES.md).

Creates a ``code_batches`` row with status ``generated`` (NOT redeemable),
inserts only the keyed hash of each code, and writes the plaintext codes to
a CSV for the printer. Activate the batch with ``python -m scripts.code_batches``
when the product reaches the venues.

Usage (one city per batch, one batch per print run)::

    uv run python -m scripts.generate_codes --city tokyo --quantity 50000 \
        --coins-per-code 100 --label "Tokyo can, first run" \
        --base-url https://play.example.ir \
        --output var/redemption-codes/tokyo-run1.csv

The CSV is the only plaintext copy of the codes. It is created with mode
0600 and refuses to overwrite an existing file; a ``.sha256`` file next to
it lets the printer confirm they received it intact. Hand it over
encrypted, get written confirmation, then delete it (docs/CODES.md).
"""

import argparse
import asyncio
import csv
import hashlib
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.redemption_codes import hash_redemption_code, pepper_fingerprint
from app.core.config import get_settings
from app.domain.code_batches import BatchEventType, BatchStatus
from app.domain.codes import CodeFormat, format_printed, generate_code, get_format
from app.domain.passports import Campaign, CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    CodeBatchEventModel,
    CodeBatchModel,
    RedemptionCodeModel,
)

# asyncpg allows at most 32767 bind parameters per statement; 5 columns per row.
INSERT_CHUNK = 2_000
MAX_QUANTITY = 5_000_000
CSV_HEADER = ["batch_id", "city", "printed_code", "code", "qr_url"]

CodeGenerator = Callable[[CityCode], str]


def city_from_name(name: str) -> CityCode:
    """Accept the campaign name (``tokyo``) or the prefix (``TO``)."""
    try:
        return CityCode[Campaign(name.strip().lower()).name]
    except ValueError:
        return CityCode(name.strip().upper())


def build_unique_codes(
    city: CityCode, count: int, generate: CodeGenerator = generate_code
) -> list[str]:
    codes: set[str] = set()
    while len(codes) < count:
        codes.add(generate(city))
    return sorted(codes)


def qr_url(base_url: str, code: str, code_format: CodeFormat) -> str:
    """The URL printed as the QR: ``https://torshx.com/b/TO-ABC-DEF-GHJ``.

    Path form ``/b/<code>`` (decision 2026-10-14, the frontend's route).
    Scheme, host and ``/b/`` stay lower-case because URL paths are
    case-sensitive (``/B/`` would miss the route); only the code is upper-case.
    The code reaches the web server's access log, so the proxy must not log
    ``/b/*`` paths and the page sends no Referer (docs/SECURITY.md).
    """
    printed = format_printed(code, code_format)
    return f"{base_url.rstrip('/').lower()}/b/{printed}"


async def insert_codes(
    factory: async_sessionmaker[AsyncSession],
    batch_id: UUID,
    city: CityCode,
    codes: list[str],
    pepper: str,
    now: datetime,
) -> list[str]:
    """Insert codes; return those actually inserted (hash collisions skipped)."""
    by_hash = {hash_redemption_code(code, pepper): code for code in codes}
    statement = (
        pg_insert(RedemptionCodeModel)
        .values(
            [
                {
                    "id": uuid4(),
                    "city": city.value,
                    "code_hash": code_hash,
                    "created_at": now,
                    "batch_id": batch_id,
                }
                for code_hash in by_hash
            ]
        )
        .on_conflict_do_nothing(index_elements=["code_hash"])
        .returning(RedemptionCodeModel.code_hash)
    )
    async with factory() as session, session.begin():
        inserted_hashes = (await session.scalars(statement)).all()
    return [by_hash[code_hash] for code_hash in inserted_hashes]


def open_private_csv(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)


def write_checksum(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_name(path.name + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return checksum_path


async def generate_batch(
    factory: async_sessionmaker[AsyncSession],
    *,
    city: CityCode,
    quantity: int,
    coins_per_code: int,
    label: str,
    base_url: str,
    output: Path,
    pepper: str,
    format_id: str = "",
    generate: CodeGenerator | None = None,
) -> UUID:
    """Create the batch, insert ``quantity`` unique codes, write the CSV."""
    if not 0 < quantity <= MAX_QUANTITY:
        raise ValueError(f"quantity must be between 1 and {MAX_QUANTITY}")
    if coins_per_code < 0:
        raise ValueError("coins_per_code must not be negative")

    code_format = get_format(format_id)
    generate_fn: CodeGenerator = generate or (
        lambda city_: generate_code(city_, code_format)
    )

    now = datetime.now(UTC)
    batch_id = uuid4()
    descriptor = open_private_csv(output)  # fail before touching the database
    async with factory() as session, session.begin():
        session.add(
            CodeBatchModel(
                id=batch_id,
                city=city.value,
                label=label,
                quantity=quantity,
                coins_per_code=coins_per_code,
                status=BatchStatus.GENERATED.value,
                format_id=code_format.format_id,
                created_at=now,
                pepper_fingerprint=pepper_fingerprint(pepper),
            )
        )
        await session.flush()  # insert the batch row before its event row (FK)
        session.add(
            CodeBatchEventModel(
                batch_id=batch_id,
                event_type=BatchEventType.GENERATED.value,
                detail=f"quantity={quantity} format={code_format.format_id}",
                created_at=now,
            )
        )

    remaining = quantity
    with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        while remaining > 0:
            wanted = min(INSERT_CHUNK, remaining)
            candidates = build_unique_codes(city, wanted, generate_fn)
            inserted = await insert_codes(
                factory, batch_id, city, candidates, pepper, now
            )
            writer.writerows(
                [
                    str(batch_id),
                    city.name,
                    format_printed(code, code_format),
                    code,
                    qr_url(base_url, code, code_format),
                ]
                for code in inserted
            )
            remaining -= len(inserted)
    write_checksum(output)
    return batch_id


async def main_async(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.redemption_code_pepper is None:
        raise SystemExit("REDEMPTION_CODE_PEPPER must be set to generate codes")
    base_url = arguments.base_url or settings.public_app_origin
    if not base_url:
        raise SystemExit("pass --base-url or set PUBLIC_APP_ORIGIN")
    database = PostgreSQLAdapter(settings)
    try:
        batch_id = await generate_batch(
            database.session_factory,
            city=city_from_name(arguments.city),
            quantity=arguments.quantity,
            coins_per_code=arguments.coins_per_code,
            label=arguments.label,
            base_url=base_url,
            output=arguments.output,
            pepper=settings.redemption_code_pepper.get_secret_value(),
            format_id=arguments.format,
        )
    finally:
        await database.dispose()
    print(
        f"batch {batch_id}: {arguments.quantity} codes -> {arguments.output}",
        file=sys.stderr,
    )
    print(
        "status is 'generated' (not redeemable). Activate it at launch with "
        f"python -m scripts.code_batches activate {batch_id}",
        file=sys.stderr,
    )
    print(
        "the CSV is the only plaintext copy: send it encrypted, then delete it",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", required=True, help="campaign name or prefix")
    parser.add_argument("--quantity", type=int, required=True)
    parser.add_argument(
        "--coins-per-code",
        type=int,
        default=100,
        help="coins this batch's codes pay out (sheet default: 100, ADR 0010)",
    )
    parser.add_argument("--label", required=True, help="human description of the run")
    parser.add_argument(
        "--base-url",
        default=None,
        help="public site, e.g. https://torshx.com (default: PUBLIC_APP_ORIGIN)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--format",
        default="",
        help="registered code format id (default: the active default format)",
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
