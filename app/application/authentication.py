import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.application.otp_test_numbers import is_test_phone_number
from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.phone import PhoneNumberError, normalize_iranian_mobile
from app.domain.users import AccountStatus, User, VerificationStatus


class AuthenticationError(Exception):
    """Raised for any invalid authentication attempt."""


class PhoneInvalidError(AuthenticationError):
    """Not an Iranian mobile number, in any shape we try."""


class ResendCooldownError(AuthenticationError):
    """A code was already sent to this number less than the cooldown ago."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("resend cooldown active")
        self.retry_after_seconds = retry_after_seconds


class DailyLimitError(AuthenticationError):
    """Too many codes requested for this number in the last 24 hours."""


class SmsError(Exception):
    """Raised by an SmsSender when delivery fails for any reason."""


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

    async def get_most_recent_for_user(
        self, user_id: UUID
    ) -> AuthenticationChallenge | None: ...

    async def count_created_since(self, user_id: UUID, since: datetime) -> int: ...

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
    code_length: int

    def generate(self) -> tuple[str, str, str]: ...

    def hash_code(self, code: str, salt: str) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class SmsSender(Protocol):
    async def send_otp(self, phone: str, code: str, purpose: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthenticationSettings:
    challenge_ttl: timedelta
    session_ttl: timedelta
    max_verification_attempts: int
    resend_cooldown: timedelta
    daily_limit: int
    # TODO: remove this on production (see app/application/otp_test_numbers.py).
    test_numbers_enabled: bool = False


@dataclass(frozen=True, slots=True)
class RequestChallengeResult:
    resend_after_seconds: int
    expires_in_seconds: int
    code_length: int
    # Only for TEST_PHONE_NUMBERS outside production; None for real numbers.
    test_code: str | None = None


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
        sms_sender: SmsSender,
        settings: AuthenticationSettings,
    ) -> None:
        self._users = users
        self._challenges = challenges
        self._sessions = sessions
        self._code_generator = code_generator
        self._clock = clock
        self._sms_sender = sms_sender
        self._settings = settings

    async def request_challenge(self, identifier: str) -> RequestChallengeResult:
        try:
            phone = normalize_iranian_mobile(identifier)
        except PhoneNumberError as error:
            raise PhoneInvalidError(str(error)) from error
        now = self._clock.now()
        result = RequestChallengeResult(
            resend_after_seconds=int(self._settings.resend_cooldown.total_seconds()),
            expires_in_seconds=int(self._settings.challenge_ttl.total_seconds()),
            code_length=self._code_generator.code_length,
        )

        user = await self._users.get_by_identifier(phone)
        is_new_user = user is None
        if user is None:
            user = await self._users.create(phone, now)
        elif user.account_status is AccountStatus.INACTIVE:
            # Same response as a real send: an inactive account must not be
            # distinguishable from a fresh number by response shape alone.
            return result

        recent = await self._challenges.get_most_recent_for_user(user.id)
        if recent is not None:
            elapsed_seconds = (now - recent.created_at).total_seconds()
            remaining = self._settings.resend_cooldown.total_seconds() - elapsed_seconds
            if remaining > 0:
                raise ResendCooldownError(int(remaining) + 1)

        sent_in_last_24h = await self._challenges.count_created_since(
            user.id, now - timedelta(hours=24)
        )
        if sent_in_last_24h >= self._settings.daily_limit:
            raise DailyLimitError("too many codes requested for this number today")

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
        purpose = "signup" if is_new_user else "login"
        # TODO: remove this on production. Test numbers: same random code and
        # limits, but no SMS; the code goes back in the response instead.
        if self._settings.test_numbers_enabled and is_test_phone_number(phone):
            await self._challenges.create(challenge)
            return replace(result, test_code=code)
        # Send before persisting: a delivery failure must not start the
        # resend cooldown or count against the daily limit for a code the
        # user never received.
        try:
            await self._sms_sender.send_otp(phone, code, purpose)
        except SmsError as error:
            raise AuthenticationError("could not send verification code") from error
        await self._challenges.create(challenge)
        return result

    async def verify_challenge(self, identifier: str, code: str) -> VerificationResult:
        try:
            phone = normalize_iranian_mobile(identifier)
        except PhoneNumberError as error:
            raise AuthenticationError("invalid authentication challenge") from error
        now = self._clock.now()
        user = await self._users.get_by_identifier(phone)
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
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()
