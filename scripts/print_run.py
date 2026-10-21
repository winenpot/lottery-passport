"""Generate one weighted print run across flavors.

Details and the reasoning: docs/CODES.md, "Print runs".

The campaign pool is 1,000,000 codes split evenly over the seven flavors
(142,857 each, ``app/domain/print_runs.py``). A run asks for ``k`` codes and
one weight per flavor (weights add up to exactly 1); flavor ``i`` gets about
``w_i * k``. The run is refused as a whole if any flavor would go past its
quota. Every code ever generated counts against the quota, including codes
of voided batches.

Each flavor with a non-zero share becomes one ``generated`` batch (NOT
redeemable), its own CSPRNG-shuffled printer CSV (mode 0600, ``.sha256``
next to it) and an ``exported`` event recording that checksum. A
``manifest.json`` (no codes in it) records the run. If anything fails
half-way, the batches already created are voided and their files deleted.

Usage::

    uv run python -m scripts.print_run --k 7000 --equal --dry-run
    uv run python -m scripts.print_run --k 7000 --weights "TO=0.3,PR=0.2,BE=0.1,\\
        PA=0.1,ME=0.1,MA=0.1,MO=0.1" --coins-per-code 100 \\
        --base-url https://torshx.com --output-dir var/print-runs/run1

Weights are decimals or fractions (``1/7``); flavors left out weigh 0. Two
runs never overlap: a Postgres advisory lock serializes them, and the quota
is re-read after the lock is taken.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import get_settings
from app.domain.code_batches import BatchStatus
from app.domain.codes import get_format
from app.domain.passports import CityCode
from app.domain.print_runs import (
    QUOTA_PER_SKU,
    SKU_ORDER,
    PrintRunError,
    equal_weights,
    parse_weights,
    plan_run,
    remaining_quota,
)
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import CodeBatchModel
from scripts.code_batches import freeze_batch, set_status
from scripts.generate_codes import CodeGenerator, generate_batch

# pg_advisory_lock key for "a print run is being generated" (arbitrary, fixed).
PRINT_RUN_LOCK_KEY = 0x4C50_5052  # "LPPR"
# The only host the in-app scanner accepts in a QR (docs/API_CONTRACT.md).
SCANNER_HOST = "torshx.com"


@dataclass(frozen=True, slots=True)
class RunBatch:
    city: CityCode
    batch_id: UUID
    quantity: int
    csv_name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class PrintRunResult:
    run_id: str
    allocation: dict[CityCode, int]
    issued_before: dict[CityCode, int]
    remaining_after: dict[CityCode, int]
    batches: list[RunBatch] = field(default_factory=list)


async def issued_per_city(connection: AsyncConnection) -> dict[CityCode, int]:
    """Codes ever generated per flavor (every batch status counts)."""
    rows = await connection.execute(
        select(CodeBatchModel.city, func.sum(CodeBatchModel.quantity)).group_by(
            CodeBatchModel.city
        )
    )
    issued = dict.fromkeys(SKU_ORDER, 0)
    for city, total in rows.all():
        issued[CityCode(city)] = int(total or 0)
    return issued


def new_run_id(now: datetime) -> str:
    return f"PR-{now.astimezone(UTC):%Y%m%dT%H%M%SZ}"


async def unique_run_id(connection: AsyncConnection, now: datetime) -> str:
    """A run id no batch label uses yet (call it under the advisory lock).

    Batch labels start with ``"<run id> "``; the rollback finds a run's
    batches by that prefix, so two runs must never share an id.
    """
    base = new_run_id(now)
    candidate, suffix = base, 1
    while await connection.scalar(
        select(func.count(CodeBatchModel.id)).where(
            CodeBatchModel.label.startswith(f"{candidate} ")
        )
    ):
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def format_table(
    allocation: Mapping[CityCode, int],
    issued: Mapping[CityCode, int],
    quota_per_sku: int,
) -> list[str]:
    remaining = remaining_quota(issued, quota_per_sku)
    lines = [
        f"{'flavor':<11}{'this run':>10}{'issued':>10}{'left now':>10}"
        f"{'left after':>12}"
    ]
    for city in SKU_ORDER:
        lines.append(
            f"{city.value} {city.name.lower():<8}{allocation.get(city, 0):>10}"
            f"{issued[city]:>10}{remaining[city]:>10}"
            f"{remaining[city] - allocation.get(city, 0):>12}"
        )
    lines.append(f"{'total':<8}{sum(allocation.values()):>10}")
    return lines


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


async def plan_print_run(
    engine: AsyncEngine,
    *,
    k: int,
    weights: Mapping[CityCode, Fraction],
    quota_per_sku: int = QUOTA_PER_SKU,
) -> tuple[dict[CityCode, int], dict[CityCode, int]]:
    """Dry run: ``(allocation, issued)``; raises if the run would be refused."""
    async with engine.connect() as connection:
        issued = await issued_per_city(connection)
    return plan_run(k, weights, issued, quota_per_sku), issued


async def run_print_run(
    engine: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    *,
    k: int,
    weights: Mapping[CityCode, Fraction],
    coins_per_code: int,
    base_url: str,
    output_dir: Path,
    pepper: str,
    quota_per_sku: int = QUOTA_PER_SKU,
    format_id: str = "",
    generate: CodeGenerator | None = None,
) -> PrintRunResult:
    """Generate the run under the advisory lock; all or nothing."""
    code_format = get_format(format_id)
    async with engine.connect() as raw:
        # Session-level lock on an autocommit connection: no transaction is
        # left open while the codes are generated, so no idle-in-transaction
        # timeout can drop the lock half-way through.
        lock = await raw.execution_options(isolation_level="AUTOCOMMIT")
        await lock.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": PRINT_RUN_LOCK_KEY}
        )
        try:
            now = datetime.now(UTC)
            run_id = await unique_run_id(lock, now)
            issued = await issued_per_city(lock)
            allocation = plan_run(k, weights, issued, quota_per_sku)
            output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            batches = await _generate_all(
                factory,
                run_id=run_id,
                k=k,
                allocation=allocation,
                coins_per_code=coins_per_code,
                base_url=base_url,
                output_dir=output_dir,
                pepper=pepper,
                format_id=code_format.format_id,
                generate=generate,
            )
        finally:
            await lock.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": PRINT_RUN_LOCK_KEY}
            )

    remaining_after = {
        city: left - allocation[city]
        for city, left in remaining_quota(issued, quota_per_sku).items()
    }
    manifest = {
        "run_id": run_id,
        "created_at": now.isoformat(),
        "k": k,
        "weights": {city.value: str(weights.get(city, 0)) for city in SKU_ORDER},
        "quota_per_sku": quota_per_sku,
        "issued_before": {city.value: n for city, n in issued.items()},
        "allocation": {city.value: n for city, n in allocation.items()},
        "remaining_after": {city.value: n for city, n in remaining_after.items()},
        "coins_per_code": coins_per_code,
        "base_url": base_url,
        "format_id": code_format.format_id,
        "status": BatchStatus.GENERATED.value,
        "batches": [
            {
                "city": batch.city.value,
                "batch_id": str(batch.batch_id),
                "quantity": batch.quantity,
                "csv": batch.csv_name,
                "sha256": batch.sha256,
            }
            for batch in batches
        ],
    }
    _write_private(output_dir / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return PrintRunResult(run_id, allocation, issued, remaining_after, batches)


async def _generate_all(
    factory: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
    k: int,
    allocation: Mapping[CityCode, int],
    coins_per_code: int,
    base_url: str,
    output_dir: Path,
    pepper: str,
    format_id: str,
    generate: CodeGenerator | None,
) -> list[RunBatch]:
    batches: list[RunBatch] = []
    written: list[Path] = []
    try:
        for city in SKU_ORDER:
            quantity = allocation[city]
            if quantity == 0:
                continue
            csv_path = output_dir / f"{run_id}-{city.value}-{city.name.lower()}.csv"
            written += [csv_path, csv_path.with_name(csv_path.name + ".sha256")]
            batch_id = await generate_batch(
                factory,
                city=city,
                quantity=quantity,
                coins_per_code=coins_per_code,
                label=f"{run_id} {city.name.lower()} {quantity}/{k}",
                base_url=base_url,
                output=csv_path,
                pepper=pepper,
                format_id=format_id,
                generate=generate,
                shuffle=True,
            )
            digest = _sha256(csv_path)
            await freeze_batch(
                factory, batch_id, export_sha256=digest, actor="print_run"
            )
            batches.append(RunBatch(city, batch_id, quantity, csv_path.name, digest))
    except BaseException:
        # By label, not by returned id: a batch whose generation died half-way
        # has a row (and some codes) but never returned its id.
        async with factory() as session:
            orphans = (
                await session.scalars(
                    select(CodeBatchModel.id).where(
                        CodeBatchModel.label.startswith(f"{run_id} ")
                    )
                )
            ).all()
        for batch_id in orphans:
            await set_status(
                factory, batch_id, BatchStatus.VOID, actor="print_run rollback"
            )
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return batches


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--k", type=int, required=True, help="codes in this run")
    shares = parser.add_mutually_exclusive_group(required=True)
    shares.add_argument("--weights", help='e.g. "TO=0.3,PR=0.2,..." (sum exactly 1)')
    shares.add_argument("--equal", action="store_true", help="1/7 per flavor")
    parser.add_argument("--dry-run", action="store_true", help="show the split only")
    parser.add_argument("--coins-per-code", type=int, default=100)
    parser.add_argument("--base-url", help="QR host, https://torshx.com in production")
    parser.add_argument("--output-dir", type=Path, help="new directory for the files")
    parser.add_argument("--quota-per-sku", type=int, default=QUOTA_PER_SKU)
    parser.add_argument("--format", default="", help="code format id (default format)")
    arguments = parser.parse_args(argv)
    if not arguments.dry_run and (not arguments.base_url or not arguments.output_dir):
        parser.error("--base-url and --output-dir are required unless --dry-run")
    if arguments.base_url and urlsplit(arguments.base_url).scheme != "https":
        parser.error("--base-url must be https")
    return arguments


async def main_async(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        weights = (
            equal_weights() if arguments.equal else parse_weights(arguments.weights)
        )
    except PrintRunError as error:
        print(error, file=sys.stderr)
        return 2
    database = PostgreSQLAdapter(settings)
    try:
        if arguments.dry_run:
            allocation, issued = await plan_print_run(
                database.engine,
                k=arguments.k,
                weights=weights,
                quota_per_sku=arguments.quota_per_sku,
            )
            print("\n".join(format_table(allocation, issued, arguments.quota_per_sku)))
            print("dry run: nothing written", file=sys.stderr)
            return 0
        if settings.redemption_code_pepper is None:
            print(
                "REDEMPTION_CODE_PEPPER must be set to generate codes", file=sys.stderr
            )
            return 2
        if urlsplit(arguments.base_url).hostname != SCANNER_HOST:
            print(
                f"warning: the in-app scanner only accepts QR codes on {SCANNER_HOST}",
                file=sys.stderr,
            )
        result = await run_print_run(
            database.engine,
            database.session_factory,
            k=arguments.k,
            weights=weights,
            coins_per_code=arguments.coins_per_code,
            base_url=arguments.base_url,
            output_dir=arguments.output_dir,
            pepper=settings.redemption_code_pepper.get_secret_value(),
            quota_per_sku=arguments.quota_per_sku,
            format_id=arguments.format,
        )
    except PrintRunError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        await database.dispose()
    print(
        "\n".join(
            format_table(
                result.allocation, result.issued_before, arguments.quota_per_sku
            )
        )
    )
    print(f"\nrun {result.run_id} -> {arguments.output_dir}", file=sys.stderr)
    for batch in result.batches:
        print(
            f"  {batch.city.value} batch {batch.batch_id}  {batch.quantity:>7}"
            f"  {batch.csv_name}",
            file=sys.stderr,
        )
    print(
        "status is 'generated' (not redeemable). Activate each batch at launch with\n"
        "  python -m scripts.code_batches activate <batch-id>\n"
        "the CSVs are the only plaintext copy: send them encrypted, then delete them",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async(parse_arguments())))


if __name__ == "__main__":
    main()
