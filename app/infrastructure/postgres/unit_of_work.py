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

from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.unit_of_work import (
    ClaimedCode,
    CodeLookup,
    InsufficientCoinsError,
)
from app.domain.audit import NewAuditEntry
from app.domain.code_batches import BatchStatus
from app.domain.ledger import NewLedgerEntry
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.reward_rules import Cadence, RewardRule
from app.infrastructure.postgres.models import (
    AuditLogModel,
    CodeBatchModel,
    CoinLedgerEntryModel,
    PassportProgressModel,
    RedemptionCodeModel,
    RewardRuleModel,
    WalletModel,
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


class SqlAlchemyUnitOfWork:
    """``async with SqlAlchemyUnitOfWork(factory) as uow: ...; await uow.commit()``."""

    codes: SqlRedemptionCodes
    passports: SqlPassports
    ledger: SqlLedger
    audit: SqlAudit
    rules: SqlRewardRules

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
