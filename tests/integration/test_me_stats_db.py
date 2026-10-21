"""``GET /me/stats`` (B48) against real PostgreSQL.

Exercises ``PostgreSQLStatsReader``'s combined scalar-subquery SELECT and
``MeService.stats``'s reuse of ``ChallengesReader.checkin_days`` +
``current_streak`` for the one field the SQL query does not cover.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from random import randint
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from app.app import create_app
from app.application.me import MeService
from app.core.config import Settings
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    AchievementModel,
    ChallengeClaimModel,
    ChallengeModel,
    MiniGameRunModel,
    RedemptionCodeModel,
    UserAchievementModel,
)
from app.infrastructure.postgres.repositories import (
    PostgreSQLChallengesReader,
    PostgreSQLLastScanReader,
    PostgreSQLStatsReader,
    PostgreSQLTeamsReader,
    PostgreSQLUserRepository,
)

ZONE = ZoneInfo("Asia/Tehran")


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


def make_me_service(database: PostgreSQLAdapter, now: datetime) -> MeService:
    return MeService(
        teams=PostgreSQLTeamsReader(database.session_factory),
        last_scans=PostgreSQLLastScanReader(database.session_factory),
        stats=PostgreSQLStatsReader(database.session_factory),
        challenges=PostgreSQLChallengesReader(database.session_factory),
        clock=FixedClock(now),
        zone=ZONE,
    )


async def new_user_id(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"+989{uuid4().int % 10**9:09d}", datetime.now(UTC))
    return user.id


async def add_redeemed_code(
    database: PostgreSQLAdapter, user_id: UUID, flavor: str
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(RedemptionCodeModel).values(
                id=uuid4(),
                city=flavor,
                code_hash=f"it-stats-{uuid4().hex}",
                created_at=datetime.now(UTC),
                redeemed_at=datetime.now(UTC),
                redeemed_by_user_id=user_id,
            )
        )


async def add_claim(
    database: PostgreSQLAdapter, challenge_id: str, user_id: UUID, period_key: str
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(ChallengeClaimModel).values(
                challenge_id=challenge_id,
                user_id=user_id,
                period_key=period_key,
                claimed_at=datetime.now(UTC),
            )
        )


async def add_mini_game_run(
    database: PostgreSQLAdapter,
    user_id: UUID,
    status: str,
    average_reaction_ms: float | None,
) -> None:
    now = datetime.now(UTC)
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(MiniGameRunModel).values(
                id=uuid4(),
                user_id=user_id,
                mini_game_id="tap_reflex",
                round_delays_ms=[300, 400, 500],
                issued_at=now,
                expires_at=now,
                finished_at=now if status != "open" else None,
                status=status,
                average_reaction_ms=average_reaction_ms,
            )
        )


async def test_a_fresh_user_has_all_zero_stats(database: PostgreSQLAdapter) -> None:
    user_id = await new_user_id(database)
    now = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    service = make_me_service(database, now)

    stats = await service.stats(user_id)

    assert stats.scans_total == 0
    assert stats.flavors_discovered == 0
    assert stats.challenges_completed == 0
    assert stats.achievements_unlocked == 0
    assert stats.checkin_streak_days == 0
    assert stats.mini_game_runs_accepted == 0
    assert stats.mini_game_best_reaction_ms is None


async def test_stats_aggregate_across_tables_for_one_user(
    database: PostgreSQLAdapter,
) -> None:
    daily_checkin_id = f"it-daily-checkin-{uuid4().hex[:8]}"
    team_choice_id = f"it-team-choice-{uuid4().hex[:8]}"
    achievement_id = f"it-streak-{uuid4().hex[:8]}"
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(ChallengeModel).values(
                id=daily_checkin_id,
                kind="daily_checkin",
                period="day",
                target=1,
                reward_coins=5,
                active=True,
                created_at=datetime.now(UTC),
            )
        )
        await session.execute(
            insert(ChallengeModel).values(
                id=team_choice_id,
                kind="team_choice",
                period="once",
                target=1,
                reward_coins=30,
                active=True,
                created_at=datetime.now(UTC),
            )
        )
        await session.execute(
            insert(AchievementModel).values(
                id=achievement_id,
                fact="checkin_streak",
                threshold=3,
                reward_coins=20,
                active=True,
                created_at=datetime.now(UTC),
            )
        )
    try:
        user_id = await new_user_id(database)

        # scans_total=3 across 2 distinct flavors
        await add_redeemed_code(database, user_id, "PR")
        await add_redeemed_code(database, user_id, "PR")
        await add_redeemed_code(database, user_id, "BE")

        # challenges_completed=3 total claims (any challenge, any period);
        # the 2 consecutive daily_checkin days separately drive the streak.
        await add_claim(database, team_choice_id, user_id, "ONCE")
        await add_claim(database, daily_checkin_id, user_id, "D:2026-10-20")
        await add_claim(database, daily_checkin_id, user_id, "D:2026-10-21")

        await async_add_user_achievement(database, achievement_id, user_id)

        await add_mini_game_run(database, user_id, "accepted", 250.0)
        await add_mini_game_run(database, user_id, "accepted", 310.0)
        await add_mini_game_run(database, user_id, "open", None)  # not counted

        now = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)  # D:2026-10-21 in Tehran
        service = make_me_service(database, now)

        stats = await service.stats(user_id)

        assert stats.scans_total == 3
        assert stats.flavors_discovered == 2
        assert stats.challenges_completed == 3
        assert stats.achievements_unlocked == 1
        assert stats.checkin_streak_days == 2
        assert stats.mini_game_runs_accepted == 2
        assert stats.mini_game_best_reaction_ms == 250.0
    finally:
        async with database.session_factory() as session, session.begin():
            await session.execute(
                delete(UserAchievementModel).where(
                    UserAchievementModel.achievement_id == achievement_id
                )
            )
            await session.execute(
                delete(AchievementModel).where(AchievementModel.id == achievement_id)
            )
            await session.execute(
                delete(ChallengeClaimModel).where(
                    ChallengeClaimModel.challenge_id.in_(
                        [daily_checkin_id, team_choice_id]
                    )
                )
            )
            await session.execute(
                delete(ChallengeModel).where(
                    ChallengeModel.id.in_([daily_checkin_id, team_choice_id])
                )
            )


async def async_add_user_achievement(
    database: PostgreSQLAdapter, achievement_id: str, user_id: UUID
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(UserAchievementModel).values(
                achievement_id=achievement_id,
                user_id=user_id,
                unlocked_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_get_me_stats_api_requires_a_session(test_database_url: str) -> None:
    settings = Settings(database_url=test_database_url, _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/me/stats")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_stats_api_shape_for_a_fresh_user(test_database_url: str) -> None:
    settings = Settings(
        database_url=test_database_url, cors_origins="*", _env_file=None
    )
    application = create_app(settings)
    subscriber = "".join(str(randint(0, 9)) for _ in range(7))
    identifier = f"+98912{subscriber}"

    with TestClient(application, headers={"X-Requested-With": "test"}) as client:
        client.post("/api/v1/auth/request", json={"identifier": identifier})
        sender = application.state.sms_sender
        client.post(
            "/api/v1/auth/verify",
            json={"identifier": identifier, "code": sender.last_code},
        )

        response = client.get("/api/v1/me/stats")

        assert response.status_code == 200
        assert response.json() == {
            "scans_total": 0,
            "flavors_discovered": 0,
            "challenges_completed": 0,
            "achievements_unlocked": 0,
            "checkin_streak_days": 0,
            "mini_game_runs_accepted": 0,
            "mini_game_best_reaction_ms": None,
        }
