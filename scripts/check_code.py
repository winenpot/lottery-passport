"""Check a printed code: batch, status, redeemed — WITHOUT redeeming it.

For quality control (docs/CODES.md section 6, B28): the printer sends photos
of a sample of printed units; this answers "does this code exist, which
batch, is it active, has it been redeemed" without ever claiming the code.
Never writes to the database.

Usage::

    uv run python -m scripts.check_code "TO-HA1-NQC-C32"
    uv run python -m scripts.check_code "https://torshx.com/b/TO-HA1-NQC-C32"
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.redemption_codes import hash_redemption_code, pepper_fingerprint
from app.core.config import get_settings
from app.domain.codes import CodeFormatError, CodeProblem, parse_code
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import CodeBatchModel, RedemptionCodeModel


@dataclass(frozen=True, slots=True)
class CheckedCode:
    """Everything QC needs about one code, and nothing a leak would regret."""

    city: str
    batch_id: UUID
    batch_label: str
    batch_status: str
    redeemed_at: datetime | None
    # None: the batch predates the pepper guard (0018) and was never
    # stamped. False: the row WAS found (so the pepper this process used
    # to hash the code IS correct -- a wrong pepper fails the lookup
    # before this field is ever computed), yet the batch's stored
    # fingerprint disagrees with that same pepper recomputed now. That can
    # only mean the `pepper_fingerprint` column itself was corrupted or
    # hand-edited after generation -- not a pepper-rotation symptom (see
    # the app-wide guard for that, app/application/redemption_codes.py).
    pepper_matches: bool | None


async def lookup_code(
    factory: async_sessionmaker[AsyncSession], code_hash: str, pepper: str
) -> CheckedCode | None:
    statement = (
        select(
            RedemptionCodeModel.city,
            RedemptionCodeModel.redeemed_at,
            CodeBatchModel.id,
            CodeBatchModel.label,
            CodeBatchModel.status,
            CodeBatchModel.pepper_fingerprint,
        )
        .join(CodeBatchModel, CodeBatchModel.id == RedemptionCodeModel.batch_id)
        .where(RedemptionCodeModel.code_hash == code_hash)
    )
    async with factory() as session:
        row = (await session.execute(statement)).one_or_none()
    if row is None:
        return None
    city, redeemed_at, batch_id, label, status, batch_pepper_fingerprint = row
    pepper_matches = (
        None
        if batch_pepper_fingerprint is None
        else batch_pepper_fingerprint == pepper_fingerprint(pepper)
    )
    return CheckedCode(
        city=city,
        batch_id=batch_id,
        batch_label=label,
        batch_status=status,
        redeemed_at=redeemed_at,
        pepper_matches=pepper_matches,
    )


def get_settings_pepper() -> str:
    settings = get_settings()
    if settings.redemption_code_pepper is None:
        raise SystemExit("REDEMPTION_CODE_PEPPER must be set to check codes")
    return settings.redemption_code_pepper.get_secret_value()


async def main_async(raw: str) -> int:
    try:
        parsed = parse_code(raw)
    except CodeFormatError as error:
        reason = (
            "the check character does not match (likely one mistyped/misread character)"
            if error.problem is CodeProblem.MISTYPED
            else "not a recognized code shape (wrong length, unknown city "
            "prefix, or a character outside the alphabet)"
        )
        print(f"MALFORMED/MISTYPED: {reason}", file=sys.stderr)
        return 1

    pepper = get_settings_pepper()
    code_hash = hash_redemption_code(parsed.canonical, pepper)
    database = PostgreSQLAdapter(get_settings())
    try:
        found = await lookup_code(database.session_factory, code_hash, pepper)
    finally:
        await database.dispose()

    print(f"code:    {parsed.printed}")
    if found is None:
        print("exists:  no (unknown to this database)")
        return 1
    print("exists:  yes")
    print(f"city:    {found.city}")
    print(f"batch:   {found.batch_id} ({found.batch_label})")
    print(f"status:  {found.batch_status}")
    if found.redeemed_at is not None:
        print(f"redeemed: yes at {found.redeemed_at.isoformat()}")
    else:
        print("redeemed: no")
    if found.pepper_matches is False:
        print(
            "pepper:  COLUMN MISMATCH -- the code hash matched (so the pepper used "
            "for this check is correct), but this batch's stored pepper_fingerprint "
            "disagrees with it; the fingerprint column itself may be corrupted or "
            "was hand-edited after generation (see docs/CODES.md)",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("code", help="a typed code or a scanned QR URL")
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(arguments.code)))


if __name__ == "__main__":
    main()
