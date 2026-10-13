"""Manage the partner lounges (``venues``) players pick as their home lounge.

Usage::

    uv run python -m scripts.venues list
    uv run python -m scripts.venues add <id> <name> <city> [--ip <public ip>]
    uv run python -m scripts.venues deactivate <id>

``id`` is a short stable slug (``parsa``) that the API exposes and players'
profiles point at, so never reuse or rename it. Deactivating hides a venue
from ``GET /config`` and new picks; players who already picked it keep it.
"""

import argparse
import asyncio
import ipaddress
import re
import sys
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import VenueModel

VENUE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


async def list_venues(factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with factory() as session:
        rows = await session.scalars(select(VenueModel).order_by(VenueModel.id))
        return [
            f"{row.id:<20} {'active' if row.active else 'inactive':<9} "
            f"{row.city:<12} {row.public_ip or '-':<16} {row.name}"
            for row in rows
        ]


async def add_venue(
    factory: async_sessionmaker[AsyncSession],
    venue_id: str,
    name: str,
    city: str,
    public_ip: str | None,
) -> bool:
    """Insert a venue. Returns False if the id already exists."""
    try:
        async with factory() as session, session.begin():
            session.add(
                VenueModel(
                    id=venue_id,
                    name=name,
                    city=city,
                    public_ip=public_ip,
                    active=True,
                    created_at=datetime.now(UTC),
                )
            )
    except IntegrityError:
        return False
    return True


async def deactivate_venue(
    factory: async_sessionmaker[AsyncSession], venue_id: str
) -> bool:
    async with factory() as session, session.begin():
        result = await session.execute(
            update(VenueModel)
            .where(VenueModel.id == venue_id)
            .values(active=False)
            .returning(VenueModel.id)
        )
        return result.scalar_one_or_none() is not None


async def main_async(arguments: argparse.Namespace) -> int:
    database = PostgreSQLAdapter(get_settings())
    try:
        factory = database.session_factory
        if arguments.command == "list":
            for line in await list_venues(factory):
                print(line)
            return 0
        if arguments.command == "add":
            if not await add_venue(
                factory, arguments.id, arguments.name, arguments.city, arguments.ip
            ):
                print(f"venue {arguments.id!r} already exists", file=sys.stderr)
                return 1
            print(f"added {arguments.id}", file=sys.stderr)
            return 0
        if not await deactivate_venue(factory, arguments.id):
            print(f"no venue {arguments.id!r}", file=sys.stderr)
            return 1
        print(f"deactivated {arguments.id}", file=sys.stderr)
        return 0
    finally:
        await database.dispose()


def _venue_id(value: str) -> str:
    if not VENUE_ID.match(value):
        raise argparse.ArgumentTypeError("id: 2-40 chars of a-z, 0-9, '-'")
    return value


def _ip(value: str) -> str:
    return str(ipaddress.ip_address(value))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    add = commands.add_parser("add")
    add.add_argument("id", type=_venue_id)
    add.add_argument("name")
    add.add_argument("city")
    add.add_argument("--ip", type=_ip, default=None)
    deactivate = commands.add_parser("deactivate")
    deactivate.add_argument("id")
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
