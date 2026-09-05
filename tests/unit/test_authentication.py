from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.authentication import (
    AuthenticationError,
    AuthenticationService,
    AuthenticationSettings,
)
from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.users import AccountStatus, User, VerificationStatus
from app.infrastructure.authentication import SecureAuthenticationCodeGenerator


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class FakeUsers:
    def __init__(self) -> None:
        self.items: dict[UUID, User] = {}

    async def get_by_identifier(self, identifier: str) -> User | None:
        return next(
            (user for user in self.items.values() if user.identifier == identifier),
            None,
        )

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.items.get(user_id)

    async def create(self, identifier: str, now: datetime) -> User:
        user = User(
            id=uuid4(),
            identifier=identifier,
            display_name=None,
            account_status=AccountStatus.ACTIVE,
            verification_status=VerificationStatus.UNVERIFIED,
            created_at=now,
            updated_at=now,
        )
        self.items[user.id] = user
        return user

    async def mark_verified(self, user_id: UUID, now: datetime) -> User:
        user = self.items[user_id]
        user.verification_status = VerificationStatus.VERIFIED
        user.updated_at = now
        return user

    async def update_display_name(
        self, user_id: UUID, display_name: str | None, now: datetime
    ) -> User | None:
        user = self.items.get(user_id)
        if user:
            user.display_name = display_name
            user.updated_at = now
        return user


class FakeChallenges:
    def __init__(self) -> None:
        self.items: dict[UUID, AuthenticationChallenge] = {}

    async def create(self, challenge: AuthenticationChallenge) -> None:
        self.items[challenge.id] = challenge

    async def get_active_for_user(
        self, user_id: UUID, now: datetime
    ) -> AuthenticationChallenge | None:
        active = [
            challenge
            for challenge in self.items.values()
            if challenge.user_id == user_id
            and challenge.consumed_at is None
            and challenge.expires_at > now
        ]
        return (
            max(active, key=lambda challenge: challenge.created_at) if active else None
        )

    async def increment_attempts(self, challenge_id: UUID) -> int:
        challenge = self.items[challenge_id]
        challenge.attempts += 1
        return challenge.attempts

    async def consume_if_matching(
        self, challenge_id: UUID, code_hash: str, now: datetime
    ) -> bool:
        challenge = self.items[challenge_id]
        if (
            challenge.code_hash != code_hash
            or challenge.consumed_at is not None
            or challenge.expires_at <= now
            or challenge.attempts >= challenge.max_attempts
        ):
            return False
        challenge.consumed_at = now
        return True


class FakeSessions:
    def __init__(self) -> None:
        self.items: dict[UUID, AuthenticatedSession] = {}

    async def create(self, session: AuthenticatedSession) -> None:
        self.items[session.id] = session

    async def get_active_by_token_hash(
        self, token_hash: str, now: datetime
    ) -> AuthenticatedSession | None:
        return next(
            (
                session
                for session in self.items.values()
                if session.token_hash == token_hash
                and session.revoked_at is None
                and session.expires_at > now
            ),
            None,
        )

    async def touch(self, session_id: UUID, now: datetime) -> None:
        self.items[session_id].last_used_at = now

    async def revoke_by_token_hash(self, token_hash: str, now: datetime) -> None:
        for session in self.items.values():
            if session.token_hash == token_hash:
                session.revoked_at = now


class FixedCodeGenerator(SecureAuthenticationCodeGenerator):
    def generate(self) -> tuple[str, str, str]:
        code = "123456"
        salt = "fixed-salt"
        return code, salt, self.hash_code(code, salt)


class FakeEmailSender:
    def __init__(self) -> None:
        self.code: str | None = None

    async def send_verification_code(self, identifier: str, code: str) -> None:
        self.code = code


def build_service() -> tuple[
    AuthenticationService, FakeClock, FakeEmailSender, FakeUsers
]:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    email = FakeEmailSender()
    users = FakeUsers()
    service = AuthenticationService(
        users=users,
        challenges=FakeChallenges(),
        sessions=FakeSessions(),
        code_generator=FixedCodeGenerator(),
        clock=clock,
        email_sender=email,
        settings=AuthenticationSettings(
            challenge_ttl=timedelta(minutes=10),
            session_ttl=timedelta(hours=1),
            max_verification_attempts=2,
        ),
    )
    return service, clock, email, users


@pytest.mark.asyncio
async def test_authentication_verifies_once_and_logout_revokes_session() -> None:
    service, _, email, _ = build_service()

    await service.request_challenge(" User@Example.com ")
    result = await service.verify_challenge("user@example.com", email.code or "")
    current_user = await service.get_current_user(result.session_token)

    assert current_user.identifier == "user@example.com"
    with pytest.raises(AuthenticationError):
        await service.verify_challenge("user@example.com", email.code or "")

    await service.logout(result.session_token)
    with pytest.raises(AuthenticationError):
        await service.get_current_user(result.session_token)


@pytest.mark.asyncio
async def test_authentication_rejects_expired_challenge() -> None:
    service, clock, email, _ = build_service()

    await service.request_challenge("user@example.com")
    clock.current += timedelta(minutes=11)

    with pytest.raises(AuthenticationError):
        await service.verify_challenge("user@example.com", email.code or "")


@pytest.mark.asyncio
async def test_authentication_limits_failed_verification_attempts() -> None:
    service, _, _, _ = build_service()

    await service.request_challenge("user@example.com")
    for _ in range(2):
        with pytest.raises(AuthenticationError):
            await service.verify_challenge("user@example.com", "000000")

    with pytest.raises(AuthenticationError):
        await service.verify_challenge("user@example.com", "123456")


@pytest.mark.asyncio
async def test_inactive_user_cannot_verify() -> None:
    service, _, email, users = build_service()

    await service.request_challenge("user@example.com")
    user = await users.get_by_identifier("user@example.com")
    assert user is not None
    user.account_status = AccountStatus.INACTIVE

    with pytest.raises(AuthenticationError):
        await service.verify_challenge("user@example.com", email.code or "")
