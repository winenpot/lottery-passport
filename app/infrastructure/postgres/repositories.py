from collections.abc import Callable
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.admin_users import UserCursor
from app.application.authentication import (
    AuthenticationChallengeRepository,
    SessionRepository,
    UserRepository,
)
from app.application.me import RawStats
from app.application.passports import PassportRepository
from app.application.profile import NicknameTaken
from app.application.wallets import WalletReader
from app.domain.achievements import Achievement, AchievementFact, UnlockedAchievement
from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.avatars import Avatar
from app.domain.challenges import Challenge, ChallengeKind, ChallengePeriod
from app.domain.ledger import LedgerEntry, LedgerReason, Wallet
from app.domain.legal import LegalDocument
from app.domain.mini_games import MiniGameId, MiniGameRunStatus
from app.domain.nickname import Nickname
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.teams import TeamMembership
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus
from app.domain.venues import Venue
from app.infrastructure.postgres.models import (
    AchievementModel,
    AuthenticationChallengeModel,
    AvatarModel,
    ChallengeClaimModel,
    ChallengeModel,
    CoinLedgerEntryModel,
    LegalDocumentModel,
    MiniGameRunModel,
    PassportProgressModel,
    RedemptionCodeModel,
    SessionModel,
    TeamMembershipModel,
    UserAchievementModel,
    UserModel,
    VenueModel,
    WalletModel,
)


def user_from_model(model: UserModel) -> User:
    return User(
        id=model.id,
        identifier=model.identifier,
        display_name=model.display_name,
        account_status=AccountStatus(model.account_status),
        verification_status=VerificationStatus(model.verification_status),
        role=UserRole(model.role),
        created_at=model.created_at,
        updated_at=model.updated_at,
        nickname=model.nickname,
        terms_version=model.terms_version,
        terms_accepted_at=model.terms_accepted_at,
        home_venue_id=model.home_venue_id,
        location_city=model.location_city,
        avatar_id=model.avatar_id,
        referral_code=model.referral_code,
    )


def challenge_from_model(
    model: AuthenticationChallengeModel,
) -> AuthenticationChallenge:
    return AuthenticationChallenge(
        id=model.id,
        user_id=model.user_id,
        code_hash=model.code_hash,
        code_salt=model.code_salt,
        expires_at=model.expires_at,
        attempts=model.attempts,
        max_attempts=model.max_attempts,
        consumed_at=model.consumed_at,
        created_at=model.created_at,
    )


def passport_progress_from_model(model: PassportProgressModel) -> PassportProgress:
    return PassportProgress(
        id=model.id,
        user_id=model.user_id,
        campaign=Campaign(model.campaign),
        points=model.points,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def session_from_model(model: SessionModel) -> AuthenticatedSession:
    return AuthenticatedSession(
        id=model.id,
        user_id=model.user_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        created_at=model.created_at,
        last_used_at=model.last_used_at,
        revoked_at=model.revoked_at,
    )


class PostgreSQLUserRepository(UserRepository):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def get_by_identifier(self, identifier: str) -> User | None:
        async with self._factory() as session:
            result = await session.scalar(
                select(UserModel).where(UserModel.identifier == identifier)
            )
            return user_from_model(result) if result else None

    async def get_by_id(self, user_id: UUID) -> User | None:
        async with self._factory() as session:
            result = await session.get(UserModel, user_id)
            return user_from_model(result) if result else None

    async def list_page(self, limit: int, after: UserCursor | None) -> list[User]:
        statement = (
            select(UserModel)
            .order_by(UserModel.created_at.desc(), UserModel.id.desc())
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                or_(
                    UserModel.created_at < after.created_at,
                    and_(
                        UserModel.created_at == after.created_at,
                        UserModel.id < after.id,
                    ),
                )
            )
        async with self._factory() as session:
            return [user_from_model(row) for row in await session.scalars(statement)]

    async def create(self, identifier: str, now: datetime) -> User:
        model = UserModel(
            identifier=identifier,
            account_status=AccountStatus.ACTIVE.value,
            verification_status=VerificationStatus.UNVERIFIED.value,
            role=UserRole.PLAYER.value,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._factory() as session:
                async with session.begin():
                    session.add(model)
            return user_from_model(model)
        except IntegrityError:
            existing = await self.get_by_identifier(identifier)
            if existing is None:
                raise
            return existing

    async def mark_verified(self, user_id: UUID, now: datetime) -> User:
        async with self._factory() as session:
            async with session.begin():
                await session.execute(
                    update(UserModel)
                    .where(UserModel.id == user_id)
                    .values(
                        verification_status=VerificationStatus.VERIFIED.value,
                        updated_at=now,
                    )
                )
            result = await session.get(UserModel, user_id)
            if result is None:
                raise LookupError("user not found")
            return user_from_model(result)

    async def update_display_name(
        self, user_id: UUID, display_name: str | None, now: datetime
    ) -> User | None:
        async with self._factory() as session:
            async with session.begin():
                await session.execute(
                    update(UserModel)
                    .where(UserModel.id == user_id)
                    .values(display_name=display_name, updated_at=now)
                )
            result = await session.get(UserModel, user_id)
            return user_from_model(result) if result else None

    async def update_profile(
        self,
        user_id: UUID,
        now: datetime,
        *,
        nickname: Nickname | None,
        terms_version: str | None,
        home_venue_id: str | None = None,
        location_city: str | None = None,
        avatar_id: str | None = None,
    ) -> User | None:
        values: dict[str, Any] = {"updated_at": now}
        if home_venue_id is not None:
            values["home_venue_id"] = home_venue_id
        if location_city is not None:
            values["location_city"] = location_city
        if avatar_id is not None:
            values["avatar_id"] = avatar_id
        if nickname is not None:
            values["nickname"] = nickname.display
            values["nickname_key"] = nickname.key
        if terms_version is not None:
            values["terms_version"] = terms_version
            values["terms_accepted_at"] = now
        try:
            async with self._factory() as session:
                async with session.begin():
                    await session.execute(
                        update(UserModel)
                        .where(UserModel.id == user_id)
                        .values(**values)
                    )
                result = await session.get(UserModel, user_id)
                return user_from_model(result) if result else None
        except IntegrityError as error:
            raise NicknameTaken(nickname.display if nickname else "") from error

    async def ensure_referral_code(
        self, user_id: UUID, candidate_generator: Callable[[], str]
    ) -> str:
        """The user's referral code, generating and storing one if absent.

        A fresh session per attempt, retried a handful of times: the
        candidate space (8 Crockford Base32 characters) is large enough
        that a collision with another user's code is rare, but the unique
        constraint (migration 0019) is the real guarantee -- this just
        retries past the rare case instead of surfacing it as an error.
        """
        async with self._factory() as session:
            existing = await session.scalar(
                select(UserModel.referral_code).where(UserModel.id == user_id)
            )
            if existing is not None:
                return existing
        for _ in range(5):
            candidate = candidate_generator()
            try:
                async with self._factory() as session:
                    async with session.begin():
                        await session.execute(
                            update(UserModel)
                            .where(
                                UserModel.id == user_id,
                                UserModel.referral_code.is_(None),
                            )
                            .values(referral_code=candidate)
                        )
                    result = await session.scalar(
                        select(UserModel.referral_code).where(UserModel.id == user_id)
                    )
                    if result is not None:
                        return result
            except IntegrityError:
                continue
        raise RuntimeError(f"could not allocate a referral code for user {user_id}")

    async def get_by_referral_code(self, referral_code: str) -> UUID | None:
        async with self._factory() as session:
            result: UUID | None = await session.scalar(
                select(UserModel.id).where(UserModel.referral_code == referral_code)
            )
            return result


def venue_from_model(model: VenueModel) -> Venue:
    return Venue(
        id=model.id,
        name=model.name,
        city=model.city,
        public_ip=model.public_ip,
        active=model.active,
        address=model.address,
    )


class PostgreSQLVenueRepository:
    """Implements ``VenueCatalogue``."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def list_active(self) -> list[Venue]:
        async with self._factory() as session:
            rows = await session.scalars(
                select(VenueModel)
                .where(VenueModel.active.is_(True))
                .order_by(VenueModel.name, VenueModel.id)
            )
            return [venue_from_model(row) for row in rows]

    async def exists_active(self, venue_id: str) -> bool:
        async with self._factory() as session:
            found = await session.scalar(
                select(VenueModel.id).where(
                    VenueModel.id == venue_id, VenueModel.active.is_(True)
                )
            )
            return found is not None


def avatar_from_model(model: AvatarModel) -> Avatar:
    return Avatar(id=model.id, image_url=model.image_url, locked=model.locked)


class PostgreSQLAvatarCatalogue:
    """Implements ``AvatarCatalogue``."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def list_active(self) -> list[Avatar]:
        async with self._factory() as session:
            rows = await session.scalars(
                select(AvatarModel)
                .where(AvatarModel.active.is_(True))
                .order_by(AvatarModel.sort, AvatarModel.id)
            )
            return [avatar_from_model(row) for row in rows]

    async def get_active(self, avatar_id: str) -> Avatar | None:
        async with self._factory() as session:
            model = await session.get(AvatarModel, avatar_id)
            if model is None or not model.active:
                return None
            return avatar_from_model(model)


class PostgreSQLLegalDocuments:
    """Implements ``LegalDocuments`` (app/application/legal.py)."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def get(self, version: str) -> LegalDocument | None:
        async with self._factory() as session:
            model = await session.get(LegalDocumentModel, version)
            if model is None:
                return None
            return LegalDocument(
                version=model.version, body=model.body, updated_at=model.updated_at
            )


def team_membership_from_model(model: TeamMembershipModel) -> TeamMembership:
    return TeamMembership(
        user_id=model.user_id,
        flavor=CityCode(model.flavor),
        switch_no=model.switch_no,
        joined_at=model.joined_at,
    )


async def current_team_membership(
    session: AsyncSession, user_id: UUID
) -> TeamMembership | None:
    """Shared by ``SqlTeams`` (unit of work) and ``PostgreSQLTeamsReader``
    (plain read, no wallet lock): the row with the highest ``switch_no``."""
    model = await session.scalar(
        select(TeamMembershipModel)
        .where(TeamMembershipModel.user_id == user_id)
        .order_by(TeamMembershipModel.switch_no.desc())
        .limit(1)
    )
    return team_membership_from_model(model) if model else None


async def count_flavor_codes(
    session: AsyncSession, user_id: UUID, flavor: CityCode
) -> int:
    """Shared by ``SqlTeams`` and ``PostgreSQLTeamsReader``: a user's
    lifetime count of redeemed codes of one flavor."""
    result = await session.scalar(
        select(func.count()).where(
            RedemptionCodeModel.redeemed_by_user_id == user_id,
            RedemptionCodeModel.city == flavor.value,
        )
    )
    return int(result or 0)


class PostgreSQLTeamsReader:
    """Implements ``TeamsReader`` (``GET /me/team``): no wallet lock, so it
    never serializes against a redemption or a team change in progress."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def current(self, user_id: UUID) -> TeamMembership | None:
        async with self._factory() as session:
            return await current_team_membership(session, user_id)

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        async with self._factory() as session:
            return await count_flavor_codes(session, user_id, flavor)


class PostgreSQLLastScanReader:
    """Implements ``LastScanReader`` (``GET /me``'s flavor mood hint)."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def last_scanned_flavor(self, user_id: UUID) -> CityCode | None:
        async with self._factory() as session:
            city = await session.scalar(
                select(RedemptionCodeModel.city)
                .where(
                    RedemptionCodeModel.redeemed_by_user_id == user_id,
                    RedemptionCodeModel.redeemed_at.is_not(None),
                )
                .order_by(RedemptionCodeModel.redeemed_at.desc())
                .limit(1)
            )
            return CityCode(city) if city is not None else None


class PostgreSQLStatsReader:
    """Implements ``StatsReader`` (``GET /me/stats``, B48).

    Deliberately NOT a SQL view. A plain view is just stored query text --
    Postgres inlines it and runs the same plan every time, so it buys
    nothing over calling these queries directly. A materialized view would
    cache a stale answer, wrong for a player who just scanned a code and
    expects their own count to move; refreshing it per user on every write
    would cost more than this already does. The actual speed comes from one
    round trip of independent, per-user-indexed scalar subqueries -- each
    hits its own small index (``ix_redemption_codes_redeemer_time``,
    ``ix_challenge_claims_user``, ``ix_user_achievements_user``,
    ``ix_mini_game_runs_user_status``) rather than scanning its table.
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def get_user_stats(self, user_id: UUID) -> RawStats:
        async with self._factory() as session:
            scans_total = (
                select(func.count())
                .select_from(RedemptionCodeModel)
                .where(RedemptionCodeModel.redeemed_by_user_id == user_id)
                .scalar_subquery()
            )
            flavors_discovered = (
                select(func.count(func.distinct(RedemptionCodeModel.city)))
                .select_from(RedemptionCodeModel)
                .where(RedemptionCodeModel.redeemed_by_user_id == user_id)
                .scalar_subquery()
            )
            challenges_completed = (
                select(func.count())
                .select_from(ChallengeClaimModel)
                .where(ChallengeClaimModel.user_id == user_id)
                .scalar_subquery()
            )
            achievements_unlocked = (
                select(func.count())
                .select_from(UserAchievementModel)
                .where(UserAchievementModel.user_id == user_id)
                .scalar_subquery()
            )
            accepted = (
                MiniGameRunModel.user_id == user_id,
                MiniGameRunModel.status == "accepted",
            )
            mini_game_runs_accepted = (
                select(func.count())
                .select_from(MiniGameRunModel)
                .where(*accepted)
                .scalar_subquery()
            )
            mini_game_best_reaction_ms = (
                select(func.min(MiniGameRunModel.average_reaction_ms))
                .select_from(MiniGameRunModel)
                .where(*accepted)
                .scalar_subquery()
            )
            row = (
                await session.execute(
                    select(
                        scans_total.label("scans_total"),
                        flavors_discovered.label("flavors_discovered"),
                        challenges_completed.label("challenges_completed"),
                        achievements_unlocked.label("achievements_unlocked"),
                        mini_game_runs_accepted.label("mini_game_runs_accepted"),
                        mini_game_best_reaction_ms.label("mini_game_best_reaction_ms"),
                    )
                )
            ).one()
            return RawStats(
                scans_total=row.scans_total,
                flavors_discovered=row.flavors_discovered,
                challenges_completed=row.challenges_completed,
                achievements_unlocked=row.achievements_unlocked,
                mini_game_runs_accepted=row.mini_game_runs_accepted,
                mini_game_best_reaction_ms=row.mini_game_best_reaction_ms,
            )


def challenge_definition_from_model(model: ChallengeModel) -> Challenge:
    return Challenge(
        id=model.id,
        kind=ChallengeKind(model.kind),
        period=ChallengePeriod(model.period),
        target=model.target,
        reward_coins=model.reward_coins,
        active=model.active,
    )


async def get_challenge_by_id(
    session: AsyncSession, challenge_id: str
) -> Challenge | None:
    """Shared by ``SqlChallenges`` and ``PostgreSQLChallengesReader``."""
    model = await session.get(ChallengeModel, challenge_id)
    if model is None or not model.active:
        return None
    return challenge_definition_from_model(model)


async def get_challenge_by_kind(
    session: AsyncSession, kind: ChallengeKind
) -> Challenge | None:
    """The active challenge of this kind, if any (assumed singleton per
    kind for the MVP -- see ``ChallengesInTransaction.get_by_kind``)."""
    model = await session.scalar(
        select(ChallengeModel).where(
            ChallengeModel.kind == kind.value, ChallengeModel.active.is_(True)
        )
    )
    return challenge_definition_from_model(model) if model else None


async def distinct_flavors_count_since(
    session: AsyncSession, user_id: UUID, since: datetime
) -> int:
    """Shared by ``SqlChallenges`` and ``PostgreSQLChallengesReader``: how
    many distinct flavors this user has redeemed a code of since ``since``."""
    result = await session.scalar(
        select(func.count(func.distinct(RedemptionCodeModel.city))).where(
            RedemptionCodeModel.redeemed_by_user_id == user_id,
            RedemptionCodeModel.redeemed_at >= since,
        )
    )
    return int(result or 0)


async def accepted_mini_game_run_count(session: AsyncSession, user_id: UUID) -> int:
    """Shared by ``SqlChallenges`` and ``PostgreSQLChallengesReader``:
    lifetime count of this user's ACCEPTED ``mini_game_runs`` rows, any
    mini-game id (``ChallengeKind.FIRST_MINI_GAME``)."""
    result = await session.scalar(
        select(func.count()).where(
            MiniGameRunModel.user_id == user_id,
            MiniGameRunModel.status == MiniGameRunStatus.ACCEPTED.value,
        )
    )
    return int(result or 0)


async def fast_tap_reflex_run_count_since(
    session: AsyncSession, user_id: UUID, since: datetime, max_average_ms: float
) -> int:
    """Shared by ``SqlChallenges`` and ``PostgreSQLChallengesReader``: how
    many of this user's ACCEPTED ``tap_reflex`` runs finished since
    ``since`` with ``average_reaction_ms`` under ``max_average_ms``
    (``ChallengeKind.TAP_REFLEX_FAST``)."""
    result = await session.scalar(
        select(func.count()).where(
            MiniGameRunModel.user_id == user_id,
            MiniGameRunModel.mini_game_id == MiniGameId.TAP_REFLEX.value,
            MiniGameRunModel.status == MiniGameRunStatus.ACCEPTED.value,
            MiniGameRunModel.finished_at >= since,
            MiniGameRunModel.average_reaction_ms < max_average_ms,
        )
    )
    return int(result or 0)


async def challenge_already_claimed(
    session: AsyncSession, challenge_id: str, user_id: UUID, period_key: str
) -> bool:
    """Shared by ``SqlChallenges`` and ``PostgreSQLChallengesReader``."""
    result = await session.scalar(
        select(ChallengeClaimModel.id).where(
            ChallengeClaimModel.challenge_id == challenge_id,
            ChallengeClaimModel.user_id == user_id,
            ChallengeClaimModel.period_key == period_key,
        )
    )
    return result is not None


async def checkin_dates(
    session: AsyncSession, challenge_id: str, user_id: UUID
) -> set[date]:
    """Shared by ``SqlChallenges`` and ``PostgreSQLChallengesReader``: every
    Tehran date this user has claimed a ``DAILY_CHECKIN`` challenge
    (``period_key`` is always ``D:<date>`` for that kind)."""
    rows = await session.scalars(
        select(ChallengeClaimModel.period_key).where(
            ChallengeClaimModel.challenge_id == challenge_id,
            ChallengeClaimModel.user_id == user_id,
        )
    )
    return {date.fromisoformat(key.removeprefix("D:")) for key in rows}


class PostgreSQLChallengesReader:
    """Implements ``ChallengesReader`` (``GET /challenges``): plain reads,
    no wallet lock, shares its queries with ``SqlChallenges`` (the claim's
    own unit of work)."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def list_active(self) -> list[Challenge]:
        async with self._factory() as session:
            rows = await session.scalars(
                select(ChallengeModel)
                .where(ChallengeModel.active.is_(True))
                .order_by(ChallengeModel.id)
            )
            return [challenge_definition_from_model(row) for row in rows]

    async def distinct_flavors_since(self, user_id: UUID, since: datetime) -> int:
        async with self._factory() as session:
            return await distinct_flavors_count_since(session, user_id, since)

    async def checkin_days(self, challenge_id: str, user_id: UUID) -> set[date]:
        async with self._factory() as session:
            return await checkin_dates(session, challenge_id, user_id)

    async def accepted_mini_game_runs_total(self, user_id: UUID) -> int:
        async with self._factory() as session:
            return await accepted_mini_game_run_count(session, user_id)

    async def fast_tap_reflex_runs_since(
        self, user_id: UUID, since: datetime, max_average_ms: float
    ) -> int:
        async with self._factory() as session:
            return await fast_tap_reflex_run_count_since(
                session, user_id, since, max_average_ms
            )

    async def has_claimed(
        self, challenge_id: str, user_id: UUID, period_key: str
    ) -> bool:
        async with self._factory() as session:
            return await challenge_already_claimed(
                session, challenge_id, user_id, period_key
            )


def achievement_definition_from_model(model: AchievementModel) -> Achievement:
    return Achievement(
        id=model.id,
        fact=AchievementFact(model.fact),
        threshold=model.threshold,
        reward_coins=model.reward_coins,
        active=model.active,
    )


async def list_active_achievements_by_fact(
    session: AsyncSession, fact: AchievementFact
) -> list[Achievement]:
    """Shared by ``SqlAchievements`` and ``PostgreSQLAchievementsReader``."""
    rows = await session.scalars(
        select(AchievementModel).where(
            AchievementModel.fact == fact.value, AchievementModel.active.is_(True)
        )
    )
    return [achievement_definition_from_model(row) for row in rows]


async def list_active_achievements(session: AsyncSession) -> list[Achievement]:
    """Every active achievement, any fact (B44/W13's progress view --
    ``list_active_achievements_by_fact`` stays for the claim-time unlock
    check, which only ever cares about one fact at a time)."""
    rows = await session.scalars(
        select(AchievementModel)
        .where(AchievementModel.active.is_(True))
        .order_by(AchievementModel.id)
    )
    return [achievement_definition_from_model(row) for row in rows]


async def achievement_already_unlocked(
    session: AsyncSession, achievement_id: str, user_id: UUID
) -> bool:
    """Shared by ``SqlAchievements`` and ``PostgreSQLAchievementsReader``."""
    result = await session.scalar(
        select(UserAchievementModel.id).where(
            UserAchievementModel.achievement_id == achievement_id,
            UserAchievementModel.user_id == user_id,
        )
    )
    return result is not None


class PostgreSQLAchievementsReader:
    """Implements a plain read for ``GET /me/achievements``: this player's
    unlocked achievements, newest first."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def list_active(self) -> list[Achievement]:
        async with self._factory() as session:
            return await list_active_achievements(session)

    async def list_unlocked(self, user_id: UUID) -> list[UnlockedAchievement]:
        async with self._factory() as session:
            rows = await session.execute(
                select(
                    UserAchievementModel.achievement_id,
                    AchievementModel.threshold,
                    AchievementModel.reward_coins,
                    UserAchievementModel.unlocked_at,
                )
                .join(
                    AchievementModel,
                    AchievementModel.id == UserAchievementModel.achievement_id,
                )
                .where(UserAchievementModel.user_id == user_id)
                .order_by(UserAchievementModel.unlocked_at.desc())
            )
            return [
                UnlockedAchievement(
                    id=row[0],
                    threshold=row[1],
                    reward_coins=row[2],
                    unlocked_at=row[3],
                )
                for row in rows
            ]


class PostgreSQLChallengeRepository(AuthenticationChallengeRepository):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create(self, challenge: AuthenticationChallenge) -> None:
        model = AuthenticationChallengeModel(
            id=challenge.id,
            user_id=challenge.user_id,
            code_hash=challenge.code_hash,
            code_salt=challenge.code_salt,
            expires_at=challenge.expires_at,
            attempts=challenge.attempts,
            max_attempts=challenge.max_attempts,
            consumed_at=challenge.consumed_at,
            created_at=challenge.created_at,
        )
        async with self._factory() as session:
            async with session.begin():
                session.add(model)

    async def get_active_for_user(
        self, user_id: UUID, now: datetime
    ) -> AuthenticationChallenge | None:
        async with self._factory() as session:
            result = await session.scalar(
                select(AuthenticationChallengeModel)
                .where(
                    AuthenticationChallengeModel.user_id == user_id,
                    AuthenticationChallengeModel.consumed_at.is_(None),
                    AuthenticationChallengeModel.expires_at > now,
                )
                .order_by(AuthenticationChallengeModel.created_at.desc())
                .limit(1)
            )
            return challenge_from_model(result) if result else None

    async def get_most_recent_for_user(
        self, user_id: UUID
    ) -> AuthenticationChallenge | None:
        async with self._factory() as session:
            result = await session.scalar(
                select(AuthenticationChallengeModel)
                .where(AuthenticationChallengeModel.user_id == user_id)
                .order_by(AuthenticationChallengeModel.created_at.desc())
                .limit(1)
            )
            return challenge_from_model(result) if result else None

    async def count_created_since(self, user_id: UUID, since: datetime) -> int:
        async with self._factory() as session:
            result = await session.scalar(
                select(func.count())
                .select_from(AuthenticationChallengeModel)
                .where(
                    AuthenticationChallengeModel.user_id == user_id,
                    AuthenticationChallengeModel.created_at >= since,
                )
            )
            return result or 0

    async def increment_attempts(self, challenge_id: UUID) -> int:
        async with self._factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(AuthenticationChallengeModel)
                    .where(AuthenticationChallengeModel.id == challenge_id)
                    .values(attempts=AuthenticationChallengeModel.attempts + 1)
                    .returning(AuthenticationChallengeModel.attempts)
                )
                return result.scalar_one()

    async def consume_if_matching(
        self, challenge_id: UUID, code_hash: str, now: datetime
    ) -> bool:
        async with self._factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(AuthenticationChallengeModel)
                    .where(
                        AuthenticationChallengeModel.id == challenge_id,
                        AuthenticationChallengeModel.code_hash == code_hash,
                        AuthenticationChallengeModel.consumed_at.is_(None),
                        AuthenticationChallengeModel.expires_at > now,
                        AuthenticationChallengeModel.attempts
                        < AuthenticationChallengeModel.max_attempts,
                    )
                    .values(consumed_at=now)
                )
                cursor_result = cast(CursorResult[Any], result)
                return cursor_result.rowcount == 1


class PostgreSQLSessionRepository(SessionRepository):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create(self, session: AuthenticatedSession) -> None:
        model = SessionModel(
            id=session.id,
            user_id=session.user_id,
            token_hash=session.token_hash,
            expires_at=session.expires_at,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            revoked_at=session.revoked_at,
        )
        async with self._factory() as db_session:
            async with db_session.begin():
                db_session.add(model)

    async def get_active_by_token_hash(
        self, token_hash: str, now: datetime
    ) -> AuthenticatedSession | None:
        async with self._factory() as session:
            result = await session.scalar(
                select(SessionModel).where(
                    SessionModel.token_hash == token_hash,
                    SessionModel.revoked_at.is_(None),
                    SessionModel.expires_at > now,
                )
            )
            return session_from_model(result) if result else None

    async def touch(self, session_id: UUID, now: datetime) -> None:
        async with self._factory() as session:
            async with session.begin():
                await session.execute(
                    update(SessionModel)
                    .where(SessionModel.id == session_id)
                    .values(last_used_at=now)
                )

    async def revoke_by_token_hash(self, token_hash: str, now: datetime) -> None:
        async with self._factory() as session:
            async with session.begin():
                await session.execute(
                    update(SessionModel)
                    .where(
                        SessionModel.token_hash == token_hash,
                        SessionModel.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )


class PostgreSQLPassportRepository(PassportRepository):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def list_for_user(self, user_id: UUID) -> list[PassportProgress]:
        async with self._factory() as session:
            result = await session.scalars(
                select(PassportProgressModel)
                .where(PassportProgressModel.user_id == user_id)
                .order_by(PassportProgressModel.campaign)
            )
            return [passport_progress_from_model(model) for model in result]


class PostgreSQLWalletReader(WalletReader):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def get(self, user_id: UUID) -> Wallet | None:
        async with self._factory() as session:
            model = await session.get(WalletModel, user_id)
            if model is None:
                return None
            return Wallet(
                user_id=model.user_id,
                balance=model.balance,
                lifetime_earned=model.lifetime_earned,
                updated_at=model.updated_at,
            )

    async def recent_entries(self, user_id: UUID, limit: int) -> list[LedgerEntry]:
        async with self._factory() as session:
            models = await session.scalars(
                select(CoinLedgerEntryModel)
                .where(CoinLedgerEntryModel.user_id == user_id)
                .order_by(CoinLedgerEntryModel.id.desc())
                .limit(limit)
            )
            return [
                LedgerEntry(
                    id=model.id,
                    user_id=model.user_id,
                    amount=model.amount,
                    reason=LedgerReason(model.reason),
                    source_id=model.source_id,
                    created_at=model.created_at,
                )
                for model in models
            ]
