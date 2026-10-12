from datetime import datetime
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
from app.application.passports import PassportRepository
from app.application.profile import NicknameTaken
from app.application.wallets import WalletReader
from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.ledger import LedgerEntry, LedgerReason, Wallet
from app.domain.nickname import Nickname
from app.domain.passports import Campaign, PassportProgress
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus
from app.infrastructure.postgres.models import (
    AuthenticationChallengeModel,
    CoinLedgerEntryModel,
    PassportProgressModel,
    SessionModel,
    UserModel,
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
    ) -> User | None:
        values: dict[str, Any] = {"updated_at": now}
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
