"""One-time generator for physical product redemption codes.

Reads a per-city quantity plan (counts supplied by marketing), generates
unique random 9-character codes (2-letter city prefix + 7-digit number),
inserts only the salted hash of each code into the database, and writes the
raw codes to a CSV for label manufacturing.

The CSV output contains the ONLY copy of the plaintext codes. Hand it to the
manufacturer and then delete it; the application never reads raw codes again.

Usage:
    uv run python scripts/generate_redemption_codes.py \
        --counts path/to/counts.json \
        --output var/redemption-codes/manufacturing-export.csv

counts.json shape: {"paris": 500000, "berlin": 300000, ...}
(keys are Campaign/CityCode names, case-insensitive)
"""

import argparse
import asyncio
import csv
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.application.redemption_codes import hash_redemption_code
from app.core.config import get_settings
from app.domain.passports import CityCode
from app.domain.redemption_codes import RedemptionCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.repositories import PostgreSQLRedemptionCodeRepository

CODE_NUMBER_SPACE = 10_000_000  # 7 digits: 0000000-9999999


def load_counts(path: Path) -> dict[CityCode, int]:
    raw = json.loads(path.read_text())
    counts: dict[CityCode, int] = {}
    for name, count in raw.items():
        city = CityCode[name.upper()]
        if not 0 < count <= CODE_NUMBER_SPACE:
            raise ValueError(
                f"count for {name} must be between 1 and {CODE_NUMBER_SPACE}"
            )
        counts[city] = count
    return counts


def generate_codes_for_city(city: CityCode, count: int) -> list[str]:
    numbers = random.SystemRandom().sample(range(CODE_NUMBER_SPACE), count)
    return [f"{city.value}{number:07d}" for number in numbers]


async def run(counts: dict[CityCode, int], output_path: Path) -> None:
    settings = get_settings()
    pepper = settings.redemption_code_pepper
    if pepper is None:
        raise SystemExit("REDEMPTION_CODE_PEPPER must be set to generate codes")

    database = PostgreSQLAdapter(settings)
    repository = PostgreSQLRedemptionCodeRepository(database.session_factory)
    now = datetime.now(UTC)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with output_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["city", "code"])
            for city, count in counts.items():
                codes = generate_codes_for_city(city, count)
                records = [
                    RedemptionCode(
                        id=uuid4(),
                        city=city,
                        code_hash=hash_redemption_code(code, pepper.get_secret_value()),
                        created_at=now,
                        redeemed_at=None,
                        redeemed_by_user_id=None,
                    )
                    for code in codes
                ]
                await repository.bulk_insert(records)
                writer.writerows((city.name, code) for code in codes)
                total += len(codes)
                print(f"{city.name}: generated {len(codes)} codes", file=sys.stderr)
    finally:
        await database.dispose()

    print(f"done: {total} codes written to {output_path}", file=sys.stderr)
    print(
        "this file holds the only plaintext copy of these codes — "
        "hand it to the manufacturer, then delete it",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    counts = load_counts(args.counts)
    asyncio.run(run(counts, args.output))


if __name__ == "__main__":
    main()
