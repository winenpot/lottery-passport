from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.authentication import (
    AuthenticationChallengeRepository,
    SessionRepository,
    UserRepository,
)
from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.users import AccountStatus, User, VerificationStatus
from app.infrastructure.postgres.models import (
    AuthenticationChallengeModel,
    SessionModel,
    UserModel,
)


def user_from_model(model: UserModel) -> User:
    return User(
        id=model.id,
        identifier=model.identifier,
        display_name=model.display_name,
        account_status=AccountStatus(model.account_status),
        verification_status=VerificationStatus(model.verification_status),
        created_at=model.created_at,
        updated_at=model.updated_at,
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

    async def create(self, identifier: str, now: datetime) -> User:
        model = UserModel(
            identifier=identifier,
            account_status=AccountStatus.ACTIVE.value,
            verification_status=VerificationStatus.UNVERIFIED.value,
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
