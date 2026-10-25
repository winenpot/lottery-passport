"""Promote or demote a user between the ``player`` and ``admin`` roles, or
clear an admin's TOTP secret after a lost phone.

Usage::

    uv run python -m scripts.admins list
    uv run python -m scripts.admins promote <identifier>
    uv run python -m scripts.admins demote <identifier>
    uv run python -m scripts.admins reset-totp <identifier>

This is the superuser bootstrap: there is no "first admin" API route (a
player can never promote themselves), so the very first admin, and every
later one, is made the same way -- direct database access, same as
scripts/code_batches.py. ``identifier`` is the account's phone number, typed
any usual way (``0912 345 6789``, ``+98912...``): it is matched in the stored
``+989XXXXXXXXX`` form. Anything that is not an Iranian mobile number is
matched exactly as typed.

The user must already exist (sign up first, then promote); this script does
not create accounts. ``reset-totp`` is the same kind of CLI-only action, for
the admin TOTP second factor (ADR-0013): it exists because a hijacked admin
session must never be able to clear or swap its own second factor.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.domain.phone import PhoneNumberError, normalize_iranian_mobile
from app.domain.users import UserRole
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import UserModel


def resolve_identifier(raw: str) -> str:
    """The stored form of ``raw``: accounts are saved as ``+989XXXXXXXXX``,
    so a number typed as ``0912...`` would otherwise match nobody and the
    operator would read 'no user' during a lost-phone reset."""
    try:
        return normalize_iranian_mobile(raw)
    except PhoneNumberError:
        return raw.strip()


async def list_admins(factory: async_sessionmaker[AsyncSession]) -> list[str]:
    statement = (
        select(UserModel.id, UserModel.identifier, UserModel.created_at)
        .where(UserModel.role == UserRole.ADMIN.value)
        .order_by(UserModel.created_at)
    )
    async with factory() as session:
        rows = (await session.execute(statement)).all()
    return [
        f"{user_id}  {identifier:<40}  admin since {created_at.isoformat()}"
        for user_id, identifier, created_at in rows
    ]


async def set_role(
    factory: async_sessionmaker[AsyncSession], identifier: str, role: UserRole
) -> bool:
    """Set ``identifier``'s role. Returns False if no such user exists."""
    async with factory() as session, session.begin():
        result = await session.execute(
            update(UserModel)
            .where(UserModel.identifier == identifier)
            .values(role=role.value)
            .returning(UserModel.id)
        )
        return result.scalar_one_or_none() is not None


async def reset_totp(
    factory: async_sessionmaker[AsyncSession], identifier: str
) -> bool:
    """Clear ``identifier``'s TOTP secret (lost phone recovery; ADR-0013).

    Direct database access, same reason as promote/demote: there is no API
    route for this, and there must not be one -- a hijacked admin session
    must never be able to swap or clear its own second factor. Returns
    False if no such user exists."""
    async with factory() as session, session.begin():
        result = await session.execute(
            update(UserModel)
            .where(UserModel.identifier == identifier)
            .values(totp_secret_encrypted=None, totp_confirmed_at=None)
            .returning(UserModel.id)
        )
        return result.scalar_one_or_none() is not None


async def main_async(arguments: argparse.Namespace) -> int:
    identifier = resolve_identifier(getattr(arguments, "identifier", ""))
    database = PostgreSQLAdapter(get_settings())
    try:
        if arguments.command == "list":
            lines = await list_admins(database.session_factory)
            if not lines:
                print("no admins", file=sys.stderr)
                return 0
            for line in lines:
                print(line)
            return 0
        if arguments.command == "reset-totp":
            cleared = await reset_totp(database.session_factory, identifier)
            if not cleared:
                print(
                    f"no user with identifier {identifier!r}",
                    file=sys.stderr,
                )
                return 1
            print(
                f"{identifier}'s TOTP secret was cleared; "
                "they can enroll again from /admin/security/totp",
                file=sys.stderr,
            )
            return 0
        role = UserRole.ADMIN if arguments.command == "promote" else UserRole.PLAYER
        changed = await set_role(database.session_factory, identifier, role)
    finally:
        await database.dispose()
    if not changed:
        print(
            f"no user with identifier {identifier!r}; they must sign up first",
            file=sys.stderr,
        )
        return 1
    print(f"{identifier} is now {role.value}", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    for name in ("promote", "demote", "reset-totp"):
        command = commands.add_parser(name)
        command.add_argument("identifier")
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
