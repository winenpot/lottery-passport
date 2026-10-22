"""Launch-day reset: delete every user except a named keep-list, in one transaction.

Removes the 2026-10 test accounts before the codes go live, without touching
``redemption_codes``/``code_batches`` (those keep their rows; redemption_codes
only ``SET NULL``s ``redeemed_by_user_id``, which this script proves is a
no-op first -- see the safety checks below). ``users`` cascades to
``auth_sessions``, ``authentication_challenges``, ``passport_progress``,
``team_memberships``, ``challenge_claims``, ``user_achievements``,
``mini_game_runs`` and ``referrals``.

A user to keep is named by the LAST 4 DIGITS of their phone number (never the
full number in a command line or a log): ``--keep-suffix 9098``. Each suffix
must match exactly one user, or this refuses to guess.

Safety, checked before anything is deleted, any failure aborts with no writes:
- no ``redemption_codes`` row has ``redeemed_at`` set (a redeemed code must
  never lose its redeemer to a reset)
- ``coin_ledger_entries``, ``wallets`` and ``audit_log`` are all empty (their
  foreign keys to ``users`` are ``RESTRICT``; once any of them has rows this
  script is the wrong tool -- there is real play data to protect)
- every ``--keep-suffix`` matches exactly one existing user

Usage::

    uv run python -m scripts.reset_test_users list
    uv run python -m scripts.reset_test_users run --keep-suffix 9098 --keep-suffix 4789
    uv run python -m scripts.reset_test_users run --keep-suffix 9098 \\
        --keep-suffix 4789 --yes
"""

import argparse
import asyncio
import sys

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.domain.phone import mask_phone
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    AuditLogModel,
    CoinLedgerEntryModel,
    RedemptionCodeModel,
    UserModel,
    WalletModel,
)


class ResetRefused(Exception):
    """A safety check failed; no row has been touched."""


async def resolve_keepers(session: AsyncSession, suffixes: list[str]) -> dict[str, str]:
    """``{suffix: identifier}`` for every suffix; raises if one isn't unique."""
    resolved: dict[str, str] = {}
    for suffix in suffixes:
        rows = (
            (
                await session.execute(
                    select(UserModel.identifier).where(
                        UserModel.identifier.like(f"%{suffix}")
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != 1:
            raise ResetRefused(
                f"--keep-suffix {suffix} matches {len(rows)} user(s), need exactly 1"
            )
        resolved[suffix] = rows[0]
    return resolved


async def check_safe_to_reset(session: AsyncSession) -> None:
    redeemed = await session.scalar(
        select(func.count())
        .select_from(RedemptionCodeModel)
        .where(RedemptionCodeModel.redeemed_at.is_not(None))
    )
    if redeemed:
        raise ResetRefused(f"{redeemed} code(s) already redeemed; refusing to reset")
    for model, name in (
        (CoinLedgerEntryModel, "coin_ledger_entries"),
        (WalletModel, "wallets"),
        (AuditLogModel, "audit_log"),
    ):
        count = await session.scalar(select(func.count()).select_from(model))
        if count:
            raise ResetRefused(
                f"{name} has {count} row(s); this is no longer test data"
            )


async def reset(
    factory: async_sessionmaker[AsyncSession], suffixes: list[str]
) -> tuple[dict[str, str], int]:
    """Delete every user not kept. Returns (kept identifiers, users deleted)."""
    async with factory() as session, session.begin():
        await check_safe_to_reset(session)
        keepers = await resolve_keepers(session, suffixes)
        result = await session.execute(
            delete(UserModel)
            .where(UserModel.identifier.not_in(keepers.values()))
            .returning(UserModel.id)
        )
        deleted = len(result.all())
        remaining = await session.scalar(select(func.count()).select_from(UserModel))
        if remaining != len(keepers):
            raise ResetRefused(
                f"expected {len(keepers)} user(s) left, found {remaining}; rolling back"
            )
    return keepers, deleted


async def list_users(factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    UserModel.identifier, UserModel.role, UserModel.created_at
                ).order_by(UserModel.created_at)
            )
        ).all()
    return [
        f"{mask_phone(identifier)}  {role}  since {created_at.isoformat()}"
        for identifier, role, created_at in rows
    ]


async def main_async(arguments: argparse.Namespace) -> int:
    database = PostgreSQLAdapter(get_settings())
    try:
        if arguments.command == "list":
            for line in await list_users(database.session_factory):
                print(line)
            return 0

        if not arguments.keep_suffix:
            print("run needs at least one --keep-suffix", file=sys.stderr)
            return 1

        try:
            async with database.session_factory() as session:
                await check_safe_to_reset(session)
                keepers = await resolve_keepers(session, arguments.keep_suffix)
        except ResetRefused as error:
            print(f"REFUSED: {error}", file=sys.stderr)
            return 1

        print(f"will keep: {', '.join(mask_phone(v) for v in keepers.values())}")
        if not arguments.yes:
            print("dry run only; pass --yes to actually delete", file=sys.stderr)
            return 0

        try:
            kept, deleted = await reset(database.session_factory, arguments.keep_suffix)
        except ResetRefused as error:
            print(f"REFUSED: {error}", file=sys.stderr)
            return 1
        print(
            f"deleted {deleted} user(s); "
            f"kept {', '.join(mask_phone(v) for v in kept.values())}",
            file=sys.stderr,
        )
        return 0
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    run = commands.add_parser("run")
    run.add_argument(
        "--keep-suffix",
        action="append",
        default=[],
        metavar="LAST4DIGITS",
        help="repeatable; the last 4 digits of a phone number to keep",
    )
    run.add_argument(
        "--yes", action="store_true", help="actually delete (default: dry run)"
    )
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
