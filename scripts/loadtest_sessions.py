"""Create throwaway users with ready-made sessions for a staging load test.

Usage (staging only; refuses to run with ENVIRONMENT=production)::

    uv run python -m scripts.loadtest_sessions --count 2000 --output sessions.csv

Writes one session token per line (0600). k6 sends each as the session cookie
(loadtest/redeem.js), so the test exercises real authenticated requests
without sending thousands of SMS. Afterwards, ``--deactivate`` revokes the
sessions and disables the users (they cannot be deleted once they hold coins:
the ledger is append-only).
"""

import argparse
import asyncio
import csv
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.authentication import AuthenticationService
from app.core.config import Settings, get_settings
from app.domain.nickname import parse_nickname
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import SessionModel, UserModel

IDENTIFIER_PREFIX = "loadtest:"


def refuse_production(settings: Settings) -> None:
    if settings.environment.lower() == "production":
        raise SystemExit("refusing to create load-test users in production")


async def create_sessions(
    factory: async_sessionmaker[AsyncSession], count: int, ttl: timedelta
) -> list[str]:
    now = datetime.now(UTC)
    tokens: list[str] = []
    async with factory() as session, session.begin():
        for _ in range(count):
            user_id = uuid4()
            token = secrets.token_urlsafe(32)
            # A finished profile, because scanning requires one.
            nickname = parse_nickname(f"lt{user_id.hex[:12]}")
            session.add(
                UserModel(
                    id=user_id,
                    identifier=f"{IDENTIFIER_PREFIX}{user_id}",
                    account_status="active",
                    verification_status="verified",
                    nickname=nickname.display,
                    nickname_key=nickname.key,
                    terms_version=get_settings().terms_version,
                    terms_accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                SessionModel(
                    id=uuid4(),
                    user_id=user_id,
                    token_hash=AuthenticationService.hash_secret(token),
                    expires_at=now + ttl,
                    created_at=now,
                    last_used_at=None,
                    revoked_at=None,
                )
            )
            tokens.append(token)
    return tokens


async def count_active_loadtest_users(
    factory: async_sessionmaker[AsyncSession],
) -> int:
    async with factory() as session:
        count = await session.scalar(
            select(func.count()).where(
                UserModel.identifier.like(f"{IDENTIFIER_PREFIX}%"),
                UserModel.account_status == "active",
            )
        )
        return int(count or 0)


async def deactivate(factory: async_sessionmaker[AsyncSession]) -> int:
    """Revoke load-test sessions and disable the users; return how many users."""
    now = datetime.now(UTC)
    loadtest_users = select(UserModel.id).where(
        UserModel.identifier.like(f"{IDENTIFIER_PREFIX}%")
    )
    async with factory() as session, session.begin():
        await session.execute(
            update(SessionModel)
            .where(
                SessionModel.user_id.in_(loadtest_users),
                SessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        result = await session.execute(
            update(UserModel)
            .where(
                UserModel.identifier.like(f"{IDENTIFIER_PREFIX}%"),
                UserModel.account_status == "active",
            )
            .values(account_status="inactive", updated_at=now)
            .returning(UserModel.id)
        )
        return len(result.all())


def write_tokens(path: Path, tokens: list[str]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session"])
        writer.writerows([token] for token in tokens)


async def main_async(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    refuse_production(settings)
    database = PostgreSQLAdapter(settings)
    try:
        if arguments.deactivate:
            disabled = await deactivate(database.session_factory)
            print(f"deactivated {disabled} load-test users", file=sys.stderr)
            return
        tokens = await create_sessions(
            database.session_factory, arguments.count, timedelta(days=1)
        )
    finally:
        await database.dispose()
    write_tokens(arguments.output, tokens)
    print(f"{len(tokens)} sessions -> {arguments.output}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("sessions.csv"))
    parser.add_argument("--deactivate", action="store_true")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
