import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.users import AccountStatus, User, VerificationStatus


class AuthenticationError(Exception):
    """Raised for any invalid authentication attempt."""


class UserRepository(Protocol):
    async def get_by_identifier(self, identifier: str) -> User | None: ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def create(self, identifier: str, now: datetime) -> User: ...

    async def mark_verified(self, user_id: UUID, now: datetime) -> User: ...

    async def update_display_name(
        self, user_id: UUID, display_name: str | None, now: datetime
    ) -> User | None: ...


class AuthenticationChallengeRepository(Protocol):
    async def create(self, challenge: AuthenticationChallenge) -> None: ...

    async def get_active_for_user(
        self, user_id: UUID, now: datetime
    ) -> AuthenticationChallenge | None: ...

    async def increment_attempts(self, challenge_id: UUID) -> int: ...

    async def consume_if_matching(
        self, challenge_id: UUID, code_hash: str, now: datetime
    ) -> bool: ...


class SessionRepository(Protocol):
    async def create(self, session: AuthenticatedSession) -> None: ...

    async def get_active_by_token_hash(
        self, token_hash: str, now: datetime
    ) -> AuthenticatedSession | None: ...

    async def touch(self, session_id: UUID, now: datetime) -> None: ...

    async def revoke_by_token_hash(self, token_hash: str, now: datetime) -> None: ...


class AuthenticationCodeGenerator(Protocol):
    def generate(self) -> tuple[str, str, str]: ...

    def hash_code(self, code: str, salt: str) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class EmailSender(Protocol):
    async def send_verification_code(self, identifier: str, code: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthenticationSettings:
    challenge_ttl: timedelta
    session_ttl: timedelta
    max_verification_attempts: int


@dataclass(frozen=True, slots=True)
class VerificationResult:
    user: User
    session_token: str


class AuthenticationService:
    def __init__(
        self,
        users: UserRepository,
        challenges: AuthenticationChallengeRepository,
        sessions: SessionRepository,
        code_generator: AuthenticationCodeGenerator,
        clock: Clock,
        email_sender: EmailSender,
        settings: AuthenticationSettings,
    ) -> None:
        self._users = users
        self._challenges = challenges
        self._sessions = sessions
        self._code_generator = code_generator
        self._clock = clock
        self._email_sender = email_sender
        self._settings = settings

    async def request_challenge(self, identifier: str) -> None:
        normalized_identifier = self.normalize_identifier(identifier)
        now = self._clock.now()
        user = await self._users.get_by_identifier(normalized_identifier)
        if user is None:
            user = await self._users.create(normalized_identifier, now)
        elif user.account_status is AccountStatus.INACTIVE:
            return

        code, salt, code_hash = self._code_generator.generate()
        challenge = AuthenticationChallenge(
            id=uuid4(),
            user_id=user.id,
            code_hash=code_hash,
            code_salt=salt,
            expires_at=now + self._settings.challenge_ttl,
            attempts=0,
            max_attempts=self._settings.max_verification_attempts,
            consumed_at=None,
            created_at=now,
        )
        await self._challenges.create(challenge)
        await self._email_sender.send_verification_code(normalized_identifier, code)

    async def verify_challenge(self, identifier: str, code: str) -> VerificationResult:
        normalized_identifier = self.normalize_identifier(identifier)
        now = self._clock.now()
        user = await self._users.get_by_identifier(normalized_identifier)
        if user is None or user.account_status is AccountStatus.INACTIVE:
            raise AuthenticationError("invalid authentication challenge")

        challenge = await self._challenges.get_active_for_user(user.id, now)
        if challenge is None or challenge.attempts >= challenge.max_attempts:
            raise AuthenticationError("invalid authentication challenge")

        supplied_hash = self._code_generator.hash_code(code, challenge.code_salt)
        if not hmac.compare_digest(supplied_hash, challenge.code_hash):
            await self._challenges.increment_attempts(challenge.id)
            raise AuthenticationError("invalid authentication challenge")

        consumed = await self._challenges.consume_if_matching(
            challenge.id, supplied_hash, now
        )
        if not consumed:
            raise AuthenticationError("invalid authentication challenge")

        if user.verification_status is not VerificationStatus.VERIFIED:
            user = await self._users.mark_verified(user.id, now)
        session_token = secrets.token_urlsafe(32)
        session = AuthenticatedSession(
            id=uuid4(),
            user_id=user.id,
            token_hash=self.hash_secret(session_token),
            expires_at=now + self._settings.session_ttl,
            created_at=now,
            last_used_at=now,
            revoked_at=None,
        )
        await self._sessions.create(session)
        return VerificationResult(user=user, session_token=session_token)

    async def get_current_user(self, session_token: str | None) -> User:
        if not session_token:
            raise AuthenticationError("authentication required")
        now = self._clock.now()
        session = await self._sessions.get_active_by_token_hash(
            self.hash_secret(session_token), now
        )
        if session is None:
            raise AuthenticationError("authentication required")
        user = await self._users.get_by_id(session.user_id)
        if user is None or user.account_status.value != "active":
            raise AuthenticationError("authentication required")
        await self._sessions.touch(session.id, now)
        return user

    async def logout(self, session_token: str | None) -> None:
        if session_token:
            await self._sessions.revoke_by_token_hash(
                self.hash_secret(session_token), self._clock.now()
            )

    async def update_display_name(
        self, user_id: UUID, display_name: str | None
    ) -> User:
        user = await self._users.update_display_name(
            user_id, display_name, self._clock.now()
        )
        if user is None:
            raise AuthenticationError("authentication required")
        return user

    @staticmethod
    def normalize_identifier(identifier: str) -> str:
        normalized = identifier.strip().casefold()
        if not normalized or "@" not in normalized:
            raise AuthenticationError("invalid authentication identifier")
        return normalized

    @staticmethod
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()
