"""Migration 0014 (profile + teams) against real PostgreSQL.

Proves what only the database can: the ``team_memberships`` CHECKs and the
UNIQUE (user_id, switch_no) race guard hold, and deleting an avatar clears
``users.avatar_id`` instead of failing. The avatar created here is deleted
again (the catalogue is shared state on this test database); throwaway
users and their team rows stay, as in the other integration tests.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import Settings
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    AvatarModel,
    TeamMembershipModel,
    UserModel,
)
from app.infrastructure.postgres.repositories import PostgreSQLUserRepository


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


def random_phone() -> str:
    # Never the +98969 test-number range: it takes another sign-in path.
    while True:
        phone = f"+989{uuid4().int % 10**9:09d}"
        if not phone.startswith("+98969"):
            return phone


async def new_user_id(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    return (await users.create(random_phone(), datetime.now(UTC))).id


async def add_membership(
    database: PostgreSQLAdapter, user_id: UUID, flavor: str, switch_no: int
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(TeamMembershipModel).values(
                user_id=user_id,
                flavor=flavor,
                switch_no=switch_no,
                joined_at=datetime.now(UTC),
            )
        )


async def test_team_membership_checks_reject_bad_rows(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)

    with pytest.raises(DBAPIError, match="ck_team_memberships_flavor"):
        await add_membership(database, user_id, "XX", 0)
    with pytest.raises(DBAPIError, match="ck_team_memberships_switch_no"):
        await add_membership(database, user_id, "TO", -1)


async def test_one_player_cannot_hold_the_same_switch_number_twice(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    await add_membership(database, user_id, "TO", 0)

    with pytest.raises(IntegrityError, match="uq_team_memberships_user_switch"):
        await add_membership(database, user_id, "MO", 0)

    await add_membership(database, user_id, "MO", 1)
    async with database.session_factory() as session:
        flavors = (
            await session.scalars(
                select(TeamMembershipModel.flavor)
                .where(TeamMembershipModel.user_id == user_id)
                .order_by(TeamMembershipModel.switch_no)
            )
        ).all()
    assert flavors == ["TO", "MO"]


async def test_deleting_an_avatar_clears_the_players_pick(
    database: PostgreSQLAdapter,
) -> None:
    user_id = await new_user_id(database)
    avatar_id = f"test-{uuid4().hex[:12]}"
    async with database.session_factory() as session, session.begin():
        session.add(
            AvatarModel(
                id=avatar_id,
                image_url="https://example.invalid/a.png",
                created_at=datetime.now(UTC),
            )
        )
    try:
        async with database.session_factory() as session, session.begin():
            await session.execute(
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(avatar_id=avatar_id, location_city="tehran")
            )
            avatar = await session.get(AvatarModel, avatar_id)
            assert avatar is not None
            assert (avatar.locked, avatar.sort, avatar.active) == (False, 0, True)
    finally:
        async with database.session_factory() as session, session.begin():
            result = await session.execute(
                delete(AvatarModel).where(AvatarModel.id == avatar_id)
            )
            assert result.rowcount == 1  # type: ignore[attr-defined]

    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(UserModel.avatar_id, UserModel.location_city).where(
                    UserModel.id == user_id
                )
            )
        ).one()
    assert tuple(row) == (None, "tehran")
