"""SQLAlchemy implementation of the application's UnitOfWork port.

Every repository here shares one ``AsyncSession`` and therefore one
PostgreSQL transaction (READ COMMITTED). Correctness does not rely on the
isolation level; it relies on:

* a conditional ``UPDATE ... WHERE redeemed_at IS NULL`` per code
  (a blocked rival re-checks the predicate after the winner commits),
* ``SELECT ... FOR UPDATE`` on the user's wallet row (per-user ordering),
* constraints: unique ``code_hash``, unique ledger ``idempotency_key``,
  ``CHECK (balance >= 0)`` and an append-only trigger on the ledger.

Lock order is always wallet row first, then code row, so two users racing
for one code cannot deadlock.
"""

from datetime import date, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.unit_of_work import (
    ClaimedCode,
    CodeLookup,
    InsufficientCoinsError,
)
from app.domain.achievements import Achievement, AchievementFact
from app.domain.audit import NewAuditEntry
from app.domain.challenges import Challenge, ChallengeKind
from app.domain.code_batches import BatchStatus
from app.domain.ledger import NewLedgerEntry
from app.domain.mini_games import (
    MiniGameId,
    MiniGameRun,
    MiniGameRunStatus,
    NewMiniGameRun,
)
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.reward_rules import Cadence, RewardRule
from app.domain.teams import TeamMembership
from app.infrastructure.postgres.models import (
    AuditLogModel,
    ChallengeClaimModel,
    CodeBatchModel,
    CoinLedgerEntryModel,
    MiniGameRunModel,
    PassportProgressModel,
    RedemptionCodeModel,
    RewardRuleModel,
    TeamMembershipModel,
    UserAchievementModel,
    WalletModel,
)
from app.infrastructure.postgres.repositories import (
    achievement_already_unlocked,
    challenge_already_claimed,
    checkin_dates,
    count_flavor_codes,
    current_team_membership,
    distinct_flavors_count_since,
    get_challenge_by_id,
    get_challenge_by_kind,
    list_active_achievements_by_fact,
)


def _progress_from_model(model: PassportProgressModel) -> PassportProgress:
    return PassportProgress(
        id=model.id,
        user_id=model.user_id,
        campaign=Campaign(model.campaign),
        points=model.points,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlRedemptionCodes:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self, code_hash: str, user_id: UUID, now: datetime
    ) -> ClaimedCode | None:
        statement = (
            update(RedemptionCodeModel)
            .where(
                RedemptionCodeModel.code_hash == code_hash,
                RedemptionCodeModel.redeemed_at.is_(None),
                RedemptionCodeModel.batch_id == CodeBatchModel.id,
                CodeBatchModel.status == BatchStatus.ACTIVE.value,
            )
            .values(redeemed_at=now, redeemed_by_user_id=user_id)
            .returning(
                RedemptionCodeModel.id,
                RedemptionCodeModel.city,
                CodeBatchModel.coins_per_code,
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        return ClaimedCode(
            code_id=row[0], city=CityCode(row[1]), coins_per_code=int(row[2])
        )

    async def lookup(self, code_hash: str) -> CodeLookup | None:
        statement = (
            select(
                RedemptionCodeModel.id,
                RedemptionCodeModel.city,
                RedemptionCodeModel.redeemed_by_user_id,
                CodeBatchModel.status,
            )
            .outerjoin(
                CodeBatchModel, RedemptionCodeModel.batch_id == CodeBatchModel.id
            )
            .where(RedemptionCodeModel.code_hash == code_hash)
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        return CodeLookup(
            code_id=row[0],
            city=CityCode(row[1]),
            redeemed_by_user_id=row[2],
            batch_active=row[3] == BatchStatus.ACTIVE.value,
        )

    async def count_redeemed_since(self, user_id: UUID, since: datetime) -> int:
        statement = select(func.count()).where(
            RedemptionCodeModel.redeemed_by_user_id == user_id,
            RedemptionCodeModel.redeemed_at >= since,
        )
        return int((await self._session.execute(statement)).scalar_one())


class SqlPassports:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_entries(
        self, user_id: UUID, campaign: Campaign, amount: int, now: datetime
    ) -> PassportProgress:
        insert_statement = pg_insert(PassportProgressModel).values(
            id=uuid4(),
            user_id=user_id,
            campaign=campaign.value,
            points=amount,
            created_at=now,
            updated_at=now,
        )
        upsert = insert_statement.on_conflict_do_update(
            index_elements=[
                PassportProgressModel.user_id,
                PassportProgressModel.campaign,
            ],
            set_={
                "points": PassportProgressModel.points
                + insert_statement.excluded.points,
                "updated_at": insert_statement.excluded.updated_at,
            },
        ).returning(PassportProgressModel)
        model = (await self._session.execute(upsert)).scalar_one()
        return _progress_from_model(model)

    async def get(self, user_id: UUID, campaign: Campaign) -> PassportProgress | None:
        model = await self._session.scalar(
            select(PassportProgressModel).where(
                PassportProgressModel.user_id == user_id,
                PassportProgressModel.campaign == campaign.value,
            )
        )
        return _progress_from_model(model) if model else None


class SqlLedger:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_wallet(self, user_id: UUID, now: datetime) -> int:
        await self._session.execute(
            pg_insert(WalletModel)
            .values(user_id=user_id, balance=0, lifetime_earned=0, updated_at=now)
            .on_conflict_do_nothing(index_elements=[WalletModel.user_id])
        )
        balance = await self._session.scalar(
            select(WalletModel.balance)
            .where(WalletModel.user_id == user_id)
            .with_for_update()
        )
        return int(balance or 0)

    async def record(self, entry: NewLedgerEntry) -> int:
        await self._session.execute(
            pg_insert(CoinLedgerEntryModel).values(
                user_id=entry.user_id,
                amount=entry.amount,
                reason=entry.reason.value,
                source_id=entry.source_id,
                idempotency_key=entry.idempotency_key,
                actor_id=entry.actor_id,
                note=entry.note,
                asset=entry.asset.value,
                created_at=entry.created_at,
            )
        )
        earned = max(entry.amount, 0)
        result = await self._session.execute(
            update(WalletModel)
            .where(
                WalletModel.user_id == entry.user_id,
                WalletModel.balance + entry.amount >= 0,
            )
            .values(
                balance=WalletModel.balance + entry.amount,
                lifetime_earned=WalletModel.lifetime_earned + earned,
                updated_at=entry.created_at,
            )
            .returning(WalletModel.balance)
        )
        balance = result.scalar_one_or_none()
        if balance is None:
            raise InsufficientCoinsError(str(entry.user_id))
        return int(balance)

    async def amount_for_key(self, idempotency_key: str) -> int | None:
        amount = await self._session.scalar(
            select(CoinLedgerEntryModel.amount).where(
                CoinLedgerEntryModel.idempotency_key == idempotency_key
            )
        )
        return int(amount) if amount is not None else None


class SqlAudit:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, entry: NewAuditEntry) -> None:
        await self._session.execute(
            pg_insert(AuditLogModel).values(
                actor_user_id=entry.actor_user_id,
                action=entry.action.value,
                entity=entry.entity,
                entity_id=entry.entity_id,
                changes=entry.changes,
                ip=entry.ip,
                created_at=entry.created_at,
            )
        )


class SqlRewardRules:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> RewardRule | None:
        model = await self._session.get(RewardRuleModel, key)
        if model is None:
            return None
        return RewardRule(
            key=model.key,
            amount=model.amount,
            cadence=Cadence(model.cadence),
            active=model.active,
            note=model.note,
        )


class SqlTeams:
    """Implements ``TeamsInTransaction``; shares its queries with the plain
    ``PostgreSQLTeamsReader`` used by ``GET /me/team`` (repositories.py)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current(self, user_id: UUID) -> TeamMembership | None:
        return await current_team_membership(self._session, user_id)

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        return await count_flavor_codes(self._session, user_id, flavor)

    async def add(self, membership: TeamMembership) -> None:
        await self._session.execute(
            insert(TeamMembershipModel).values(
                user_id=membership.user_id,
                flavor=membership.flavor.value,
                switch_no=membership.switch_no,
                joined_at=membership.joined_at,
            )
        )


class SqlChallenges:
    """Implements ``ChallengesInTransaction``; shares its queries with the
    plain ``PostgreSQLChallengesReader`` used by ``GET /challenges``
    (repositories.py)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, challenge_id: str) -> Challenge | None:
        return await get_challenge_by_id(self._session, challenge_id)

    async def get_by_kind(self, kind: ChallengeKind) -> Challenge | None:
        return await get_challenge_by_kind(self._session, kind)

    async def distinct_flavors_since(self, user_id: UUID, since: datetime) -> int:
        return await distinct_flavors_count_since(self._session, user_id, since)

    async def checkin_days(self, challenge_id: str, user_id: UUID) -> set[date]:
        return await checkin_dates(self._session, challenge_id, user_id)

    async def has_claimed(
        self, challenge_id: str, user_id: UUID, period_key: str
    ) -> bool:
        return await challenge_already_claimed(
            self._session, challenge_id, user_id, period_key
        )

    async def claim(
        self, challenge_id: str, user_id: UUID, period_key: str, now: datetime
    ) -> None:
        await self._session.execute(
            insert(ChallengeClaimModel).values(
                challenge_id=challenge_id,
                user_id=user_id,
                period_key=period_key,
                claimed_at=now,
            )
        )


class SqlAchievements:
    """Implements ``AchievementsInTransaction``; shares its queries with the
    plain ``PostgreSQLAchievementsReader`` used by ``GET /me/achievements``
    (repositories.py)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_by_fact(self, fact: AchievementFact) -> list[Achievement]:
        return await list_active_achievements_by_fact(self._session, fact)

    async def already_unlocked(self, achievement_id: str, user_id: UUID) -> bool:
        return await achievement_already_unlocked(
            self._session, achievement_id, user_id
        )

    async def unlock(self, achievement_id: str, user_id: UUID, now: datetime) -> None:
        await self._session.execute(
            insert(UserAchievementModel).values(
                achievement_id=achievement_id,
                user_id=user_id,
                unlocked_at=now,
            )
        )


def _mini_game_run_from_model(model: MiniGameRunModel) -> MiniGameRun:
    return MiniGameRun(
        id=model.id,
        user_id=model.user_id,
        mini_game_id=MiniGameId(model.mini_game_id),
        round_delays_ms=tuple(model.round_delays_ms),
        issued_at=model.issued_at,
        expires_at=model.expires_at,
        status=MiniGameRunStatus(model.status),
    )


class SqlMiniGames:
    """Implements ``MiniGamesInTransaction`` (app/domain/mini_games.py, G1).
    No plain reader exists yet (no GET endpoint reads mini-game runs
    directly today) -- add one alongside its queries here if a second
    caller shows up."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open(self, run: NewMiniGameRun) -> None:
        await self._session.execute(
            insert(MiniGameRunModel).values(
                id=run.id,
                user_id=run.user_id,
                mini_game_id=run.mini_game_id.value,
                round_delays_ms=list(run.round_delays_ms),
                issued_at=run.issued_at,
                expires_at=run.expires_at,
                status=MiniGameRunStatus.OPEN.value,
            )
        )

    async def get_open(
        self, user_id: UUID, mini_game_id: MiniGameId
    ) -> MiniGameRun | None:
        model = await self._session.scalar(
            select(MiniGameRunModel).where(
                MiniGameRunModel.user_id == user_id,
                MiniGameRunModel.mini_game_id == mini_game_id.value,
                MiniGameRunModel.status == MiniGameRunStatus.OPEN.value,
            )
        )
        return _mini_game_run_from_model(model) if model else None

    async def get(self, run_id: UUID) -> MiniGameRun | None:
        model = await self._session.get(MiniGameRunModel, run_id)
        return _mini_game_run_from_model(model) if model else None

    async def finish(
        self,
        run_id: UUID,
        status: MiniGameRunStatus,
        finished_at: datetime,
        average_reaction_ms: float,
    ) -> None:
        await self._session.execute(
            update(MiniGameRunModel)
            .where(MiniGameRunModel.id == run_id)
            .values(
                status=status.value,
                finished_at=finished_at,
                average_reaction_ms=average_reaction_ms,
            )
        )

    async def count_rejected_since(self, user_id: UUID, since: datetime) -> int:
        result = await self._session.scalar(
            select(func.count()).where(
                MiniGameRunModel.user_id == user_id,
                MiniGameRunModel.status == MiniGameRunStatus.REJECTED.value,
                MiniGameRunModel.finished_at >= since,
            )
        )
        return int(result or 0)


class SqlAlchemyUnitOfWork:
    """``async with SqlAlchemyUnitOfWork(factory) as uow: ...; await uow.commit()``."""

    codes: SqlRedemptionCodes
    passports: SqlPassports
    ledger: SqlLedger
    audit: SqlAudit
    rules: SqlRewardRules
    teams: SqlTeams
    challenges: SqlChallenges
    achievements: SqlAchievements
    mini_games: SqlMiniGames

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        self._session = self._factory()
        self._committed = False
        self.codes = SqlRedemptionCodes(self._session)
        self.passports = SqlPassports(self._session)
        self.ledger = SqlLedger(self._session)
        self.audit = SqlAudit(self._session)
        self.rules = SqlRewardRules(self._session)
        self.teams = SqlTeams(self._session)
        self.challenges = SqlChallenges(self._session)
        self.achievements = SqlAchievements(self._session)
        self.mini_games = SqlMiniGames(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if not self._committed:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        await self._require_session().commit()
        self._committed = True

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work used outside 'async with'")
        return self._session
