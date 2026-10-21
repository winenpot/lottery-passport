"""Challenges (C1) against real PostgreSQL.

Proves what only the database can (the CHECK constraints on ``challenges``
and the UNIQUE (challenge_id, user_id, period_key) race guard on
``challenge_claims``), plus an end-to-end claim for both shipped kinds
through the real ``ChallengeService`` + ``SqlAlchemyUnitOfWork``. The
challenge rows this test creates are deleted again (the catalogue is
shared state on this test database, like avatars in
test_profile_teams_db.py); throwaway users and their rows stay, as in the
other integration tests.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.application.achievements import AchievementService
from app.application.challenges import ChallengeService
from app.application.unit_of_work import UnitOfWork
from app.core.config import Settings
from app.domain.challenges import ChallengeClaimError, ChallengeClaimRefusal
from app.domain.passports import CityCode
from app.infrastructure.postgres.database import PostgreSQLAdapter
from app.infrastructure.postgres.models import (
    AchievementModel,
    ChallengeClaimModel,
    ChallengeModel,
    MiniGameRunModel,
    RedemptionCodeModel,
    TeamMembershipModel,
    UserAchievementModel,
)
from app.infrastructure.postgres.repositories import (
    PostgreSQLAchievementsReader,
    PostgreSQLChallengesReader,
    PostgreSQLTeamsReader,
    PostgreSQLUserRepository,
)
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork

ZONE = ZoneInfo("Asia/Tehran")


@pytest.fixture
async def database(test_database_url: str) -> AsyncIterator[PostgreSQLAdapter]:
    adapter = PostgreSQLAdapter(
        Settings(database_url=test_database_url, _env_file=None)
    )
    try:
        yield adapter
    finally:
        await adapter.dispose()


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_service(database: PostgreSQLAdapter, now: datetime) -> ChallengeService:
    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory)

    return ChallengeService(
        reader=PostgreSQLChallengesReader(database.session_factory),
        teams=PostgreSQLTeamsReader(database.session_factory),
        unit_of_work=unit_of_work,
        clock=FixedClock(now),
        zone=ZONE,
    )


async def new_user_id(database: PostgreSQLAdapter) -> UUID:
    users = PostgreSQLUserRepository(database.session_factory)
    user = await users.create(f"+989{uuid4().int % 10**9:09d}", datetime.now(UTC))
    return user.id


async def add_challenge(
    database: PostgreSQLAdapter,
    challenge_id: str,
    kind: str,
    period: str,
    target: int,
    reward_coins: int,
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(ChallengeModel).values(
                id=challenge_id,
                kind=kind,
                period=period,
                target=target,
                reward_coins=reward_coins,
                active=True,
                created_at=datetime.now(UTC),
            )
        )


async def delete_challenge(database: PostgreSQLAdapter, challenge_id: str) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            delete(ChallengeClaimModel).where(
                ChallengeClaimModel.challenge_id == challenge_id
            )
        )
        await session.execute(
            delete(ChallengeModel).where(ChallengeModel.id == challenge_id)
        )


async def add_team_membership(
    database: PostgreSQLAdapter, user_id: UUID, flavor: str
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(TeamMembershipModel).values(
                user_id=user_id,
                flavor=flavor,
                switch_no=0,
                joined_at=datetime.now(UTC),
            )
        )


async def add_redeemed_code(
    database: PostgreSQLAdapter, user_id: UUID, flavor: str, redeemed_at: datetime
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(RedemptionCodeModel).values(
                id=uuid4(),
                city=flavor,
                code_hash=f"it-challenge-{uuid4().hex}",
                created_at=datetime.now(UTC),
                redeemed_at=redeemed_at,
                redeemed_by_user_id=user_id,
            )
        )


async def add_checkin_claim(
    database: PostgreSQLAdapter, challenge_id: str, user_id: UUID, period_key: str
) -> None:
    """Backfills a prior day's check-in directly (no wallet lock needed --
    this models history, not a live claim through the service)."""
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
    *,
    status: str,
    average_reaction_ms: float,
    finished_at: datetime,
) -> None:
    """Inserts a finished ``mini_game_runs`` row directly -- the plausibility
    assessment itself (app/domain/mini_games.py) is tested there; this
    models its outcome for the challenge engine's own read."""
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(MiniGameRunModel).values(
                id=uuid4(),
                user_id=user_id,
                mini_game_id="tap_reflex",
                round_delays_ms=[800, 900, 1000, 1100, 1200],
                issued_at=finished_at,
                expires_at=finished_at,
                finished_at=finished_at,
                status=status,
                average_reaction_ms=average_reaction_ms,
            )
        )


async def add_achievement(
    database: PostgreSQLAdapter,
    achievement_id: str,
    fact: str,
    threshold: int,
    reward_coins: int,
) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            insert(AchievementModel).values(
                id=achievement_id,
                fact=fact,
                threshold=threshold,
                reward_coins=reward_coins,
                active=True,
                created_at=datetime.now(UTC),
            )
        )


async def delete_achievement(database: PostgreSQLAdapter, achievement_id: str) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            delete(UserAchievementModel).where(
                UserAchievementModel.achievement_id == achievement_id
            )
        )
        await session.execute(
            delete(AchievementModel).where(AchievementModel.id == achievement_id)
        )


async def test_challenge_checks_reject_bad_rows(database: PostgreSQLAdapter) -> None:
    with pytest.raises(DBAPIError, match="ck_challenges_kind"):
        await add_challenge(database, f"it-{uuid4().hex[:8]}", "bogus", "once", 1, 10)
    with pytest.raises(DBAPIError, match="ck_challenges_period"):
        await add_challenge(
            database, f"it-{uuid4().hex[:8]}", "team_choice", "yearly", 1, 10
        )
    with pytest.raises(DBAPIError, match="ck_challenges_target_positive"):
        await add_challenge(
            database, f"it-{uuid4().hex[:8]}", "team_choice", "once", 0, 10
        )
    with pytest.raises(DBAPIError, match="ck_challenges_reward_coins_non_negative"):
        await add_challenge(
            database, f"it-{uuid4().hex[:8]}", "team_choice", "once", 1, -1
        )


async def test_a_claim_cannot_be_recorded_twice_for_the_same_period(
    database: PostgreSQLAdapter,
) -> None:
    challenge_id = f"it-choose-team-{uuid4().hex[:8]}"
    await add_challenge(database, challenge_id, "team_choice", "once", 1, 30)
    try:
        user_id = await new_user_id(database)
        async with database.session_factory() as session, session.begin():
            await session.execute(
                insert(ChallengeClaimModel).values(
                    challenge_id=challenge_id,
                    user_id=user_id,
                    period_key="ONCE",
                    claimed_at=datetime.now(UTC),
                )
            )
        with pytest.raises(
            IntegrityError, match="uq_challenge_claims_challenge_user_period"
        ):
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    insert(ChallengeClaimModel).values(
                        challenge_id=challenge_id,
                        user_id=user_id,
                        period_key="ONCE",
                        claimed_at=datetime.now(UTC),
                    )
                )
    finally:
        await delete_challenge(database, challenge_id)


async def test_team_choice_claim_end_to_end(database: PostgreSQLAdapter) -> None:
    challenge_id = f"it-choose-team-{uuid4().hex[:8]}"
    await add_challenge(database, challenge_id, "team_choice", "once", 1, 30)
    try:
        user_id = await new_user_id(database)
        now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
        service = make_service(database, now)

        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED

        await add_team_membership(database, user_id, CityCode.TOKYO.value)
        result = await service.claim(user_id, challenge_id)
        assert (result.coins_awarded, result.coin_balance) == (30, 30)

        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.ALREADY_CLAIMED
    finally:
        await delete_challenge(database, challenge_id)


async def test_distinct_flavors_claim_counts_within_the_month(
    database: PostgreSQLAdapter,
) -> None:
    challenge_id = f"it-discover-flavors-{uuid4().hex[:8]}"
    await add_challenge(database, challenge_id, "distinct_flavors", "month", 3, 100)
    try:
        user_id = await new_user_id(database)
        now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
        service = make_service(database, now)

        await add_redeemed_code(database, user_id, "PR", now)
        await add_redeemed_code(database, user_id, "BE", now)
        # A redemption from last month must not count toward this month.
        await add_redeemed_code(
            database, user_id, "TO", datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
        )
        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert (caught.value.required, caught.value.have) == (3, 2)

        await add_redeemed_code(database, user_id, "MA", now)
        result = await service.claim(user_id, challenge_id)
        assert result.coins_awarded == 100
    finally:
        await delete_challenge(database, challenge_id)


async def test_achievement_checks_reject_bad_rows(database: PostgreSQLAdapter) -> None:
    with pytest.raises(DBAPIError, match="ck_achievements_fact"):
        await add_achievement(database, f"it-{uuid4().hex[:8]}", "bogus_fact", 3, 20)
    with pytest.raises(DBAPIError, match="ck_achievements_threshold_positive"):
        await add_achievement(
            database, f"it-{uuid4().hex[:8]}", "checkin_streak", 0, 20
        )
    with pytest.raises(DBAPIError, match="ck_achievements_reward_coins_non_negative"):
        await add_achievement(
            database, f"it-{uuid4().hex[:8]}", "checkin_streak", 3, -1
        )


async def test_an_achievement_cannot_be_unlocked_twice_for_the_same_user(
    database: PostgreSQLAdapter,
) -> None:
    achievement_id = f"it-streak-{uuid4().hex[:8]}"
    await add_achievement(database, achievement_id, "checkin_streak", 3, 20)
    try:
        user_id = await new_user_id(database)
        async with database.session_factory() as session, session.begin():
            await session.execute(
                insert(UserAchievementModel).values(
                    achievement_id=achievement_id,
                    user_id=user_id,
                    unlocked_at=datetime.now(UTC),
                )
            )
        with pytest.raises(
            IntegrityError, match="uq_user_achievements_achievement_user"
        ):
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    insert(UserAchievementModel).values(
                        achievement_id=achievement_id,
                        user_id=user_id,
                        unlocked_at=datetime.now(UTC),
                    )
                )
    finally:
        await delete_achievement(database, achievement_id)


async def test_daily_checkin_streak_unlocks_an_achievement_end_to_end(
    database: PostgreSQLAdapter,
) -> None:
    """The widened ``ck_challenges_kind`` CHECK (daily_checkin) and the
    achievement unlock-and-pay both happen in this one claim, in the same
    transaction as the check-in itself."""
    challenge_id = f"it-daily-checkin-{uuid4().hex[:8]}"
    achievement_id = f"it-streak-3-{uuid4().hex[:8]}"
    await add_challenge(database, challenge_id, "daily_checkin", "day", 1, 10)
    await add_achievement(database, achievement_id, "checkin_streak", 3, 20)
    try:
        user_id = await new_user_id(database)
        now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)  # D:2026-10-15 in Tehran
        service = make_service(database, now)
        await add_checkin_claim(database, challenge_id, user_id, "D:2026-10-13")
        await add_checkin_claim(database, challenge_id, user_id, "D:2026-10-14")

        result = await service.claim(user_id, challenge_id)

        assert result.streak == 3
        assert [u.id for u in result.achievements_unlocked] == [achievement_id]
        assert result.coin_balance == 10 + 20

        # Claiming again tomorrow (a 4th consecutive day) must not re-pay
        # the already-unlocked 3-day milestone.
        tomorrow = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
        service_tomorrow = make_service(database, tomorrow)
        result_tomorrow = await service_tomorrow.claim(user_id, challenge_id)
        assert result_tomorrow.streak == 4
        assert result_tomorrow.achievements_unlocked == []
        assert result_tomorrow.coin_balance == 10 + 20 + 10
    finally:
        await delete_achievement(database, achievement_id)
        await delete_challenge(database, challenge_id)


async def test_first_mini_game_and_tap_reflex_fast_kinds_are_allowed_rows(
    database: PostgreSQLAdapter,
) -> None:
    """W12: the widened ``ck_challenges_kind`` CHECK accepts both new kinds
    (the negative case -- an unknown kind is still rejected -- is already
    covered by ``test_challenge_checks_reject_bad_rows`` above)."""
    first_id = f"it-first-mini-game-{uuid4().hex[:8]}"
    fast_id = f"it-tap-reflex-fast-{uuid4().hex[:8]}"
    await add_challenge(database, first_id, "first_mini_game", "once", 1, 20)
    await add_challenge(database, fast_id, "tap_reflex_fast", "day", 1, 20)
    await delete_challenge(database, first_id)
    await delete_challenge(database, fast_id)


async def test_first_mini_game_claim_end_to_end(database: PostgreSQLAdapter) -> None:
    challenge_id = f"it-first-mini-game-{uuid4().hex[:8]}"
    await add_challenge(database, challenge_id, "first_mini_game", "once", 1, 20)
    try:
        user_id = await new_user_id(database)
        now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
        service = make_service(database, now)

        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED

        # A REJECTED run does not count, any mini-game id does.
        await add_mini_game_run(
            database,
            user_id,
            status="rejected",
            average_reaction_ms=180,
            finished_at=now,
        )
        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED

        await add_mini_game_run(
            database,
            user_id,
            status="accepted",
            average_reaction_ms=400,
            finished_at=now,
        )
        result = await service.claim(user_id, challenge_id)
        assert (result.coins_awarded, result.coin_balance) == (20, 20)

        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.ALREADY_CLAIMED
    finally:
        await delete_challenge(database, challenge_id)


async def test_tap_reflex_fast_claim_pays_only_for_a_fast_accepted_run_today(
    database: PostgreSQLAdapter,
) -> None:
    """A slow ACCEPTED run and a fast REJECTED run must both fail to
    unlock; only an ACCEPTED run under the threshold pays, once per
    Tehran day."""
    challenge_id = f"it-tap-reflex-fast-{uuid4().hex[:8]}"
    await add_challenge(database, challenge_id, "tap_reflex_fast", "day", 1, 20)
    try:
        user_id = await new_user_id(database)
        now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)  # D:2026-10-15 in Tehran
        service = make_service(database, now)

        # A slow ACCEPTED run (over the 250 ms threshold): not fast enough.
        await add_mini_game_run(
            database,
            user_id,
            status="accepted",
            average_reaction_ms=400,
            finished_at=now,
        )
        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED

        # A fast REJECTED run (implausible): plausibility beats speed.
        await add_mini_game_run(
            database,
            user_id,
            status="rejected",
            average_reaction_ms=120,
            finished_at=now,
        )
        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED

        # A genuinely fast, ACCEPTED run today: claimable, pays once.
        await add_mini_game_run(
            database,
            user_id,
            status="accepted",
            average_reaction_ms=210,
            finished_at=now,
        )
        result = await service.claim(user_id, challenge_id)
        assert (result.coins_awarded, result.coin_balance) == (20, 20)

        with pytest.raises(ChallengeClaimError) as caught:
            await service.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.ALREADY_CLAIMED

        # Yesterday's fast run must not count toward today's claim.
        yesterday = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
        await add_mini_game_run(
            database,
            user_id,
            status="accepted",
            average_reaction_ms=150,
            finished_at=yesterday,
        )
        tomorrow = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
        service_tomorrow = make_service(database, tomorrow)
        with pytest.raises(ChallengeClaimError) as caught:
            await service_tomorrow.claim(user_id, challenge_id)
        assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED
    finally:
        await delete_challenge(database, challenge_id)


def make_achievement_service(
    database: PostgreSQLAdapter, now: datetime
) -> AchievementService:
    return AchievementService(
        reader=PostgreSQLAchievementsReader(database.session_factory),
        challenges=PostgreSQLChallengesReader(database.session_factory),
        clock=FixedClock(now),
        zone=ZONE,
    )


async def test_achievement_progress_shows_locked_rows_before_the_first_unlock(
    database: PostgreSQLAdapter,
) -> None:
    """B44/W13: a new player sees every active achievement, not just the
    ones they have unlocked -- the gap ``GET /me/achievements`` (unlocked
    only) cannot close on its own."""
    challenge_id = f"it-daily-checkin-{uuid4().hex[:8]}"
    achievement_3 = f"it-streak-3-{uuid4().hex[:8]}"
    achievement_7 = f"it-streak-7-{uuid4().hex[:8]}"
    await add_challenge(database, challenge_id, "daily_checkin", "day", 1, 10)
    await add_achievement(database, achievement_3, "checkin_streak", 3, 20)
    await add_achievement(database, achievement_7, "checkin_streak", 7, 50)
    try:
        user_id = await new_user_id(database)
        now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)  # D:2026-10-15 in Tehran
        achievements = make_achievement_service(database, now)

        progress = await achievements.list_progress(user_id)
        by_id = {p.id: p for p in progress}
        assert (achievement_3 in by_id) and (achievement_7 in by_id)
        assert (by_id[achievement_3].have, by_id[achievement_3].unlocked) == (0, False)
        assert (by_id[achievement_7].have, by_id[achievement_7].unlocked) == (0, False)
        assert by_id[achievement_3].unlocked_at is None

        # Build a 3-day streak through the real claim path, same as the
        # end-to-end daily-checkin test above.
        service = make_service(database, now)
        await add_checkin_claim(database, challenge_id, user_id, "D:2026-10-13")
        await add_checkin_claim(database, challenge_id, user_id, "D:2026-10-14")
        result = await service.claim(user_id, challenge_id)
        assert [u.id for u in result.achievements_unlocked] == [achievement_3]

        progress = await achievements.list_progress(user_id)
        by_id = {p.id: p for p in progress}
        assert (by_id[achievement_3].have, by_id[achievement_3].unlocked) == (3, True)
        assert by_id[achievement_3].unlocked_at is not None
        # Still locked, but progress reflects the same streak, not 0 any more.
        assert (by_id[achievement_7].have, by_id[achievement_7].unlocked) == (3, False)
    finally:
        await delete_achievement(database, achievement_3)
        await delete_achievement(database, achievement_7)
        await delete_challenge(database, challenge_id)
