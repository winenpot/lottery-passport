import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.application.otp_test_numbers import is_test_phone_number
from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.nickname import is_reserved_name
from app.domain.phone import (
    PhoneNumberError,
    has_known_mobile_prefix,
    mask_phone,
    normalize_iranian_mobile,
)
from app.domain.totp import TotpSecretError, generate_secret, verify_code
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus


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


class DisplayNameReserved(AuthenticationError):
    """``display_name`` collapses to a reserved key (brand/staff/profanity).

    ``display_name`` has no charset restriction (legacy field, see
    docs/API_CONTRACT.md "Demo to contract migration"), so it needs its own
    reserved-name check; `nickname` already rejects these through
    `app.domain.nickname.parse_nickname`.
    """


class PhoneNotAllowedError(AuthenticationError):
    """This environment sends real SMS only to an allow-list (staging).

    A public test server that texts any number is an SMS relay that burns
    credit; production never sets the list (config validator).
    """


class AdminTotpAlreadyEnrolledError(AuthenticationError):
    """The admin already has a confirmed TOTP secret.

    Re-enrolling over an active secret would let a hijacked admin session
    silently swap the second factor to one the real admin doesn't hold;
    recovery (lost phone) goes through ``scripts.admins reset-totp``
    instead, a deliberate CLI action, not a panel click.
    """


class AdminTotpNotPendingError(AuthenticationError):
    """No enrollment is in progress to confirm."""


class PhoneUnusualError(AuthenticationError):
    """The number's prefix is not on any publicly known allocated range.

    A soft warning, not a hard "invalid number" verdict (ranges change), but
    the vendor (Kavenegar) is never called for it: an unusual number is the
    exact shape of a typo or a throwaway/fraud number, and every call costs
    SMS credit whether or not it is deliverable. The caller must tell the
    player to double-check the number, not silently drop the request.
    """


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
class AdminTotpRecord:
    secret: str
    confirmed_at: datetime | None


class AdminTotpRepository(Protocol):
    """Plaintext in, plaintext out: encryption at rest is an infrastructure
    detail (app/infrastructure/crypto.py), invisible here."""

    async def get(self, user_id: UUID) -> AdminTotpRecord | None: ...

    async def save_pending(self, user_id: UUID, secret: str, now: datetime) -> None: ...

    async def confirm(self, user_id: UUID, now: datetime) -> None: ...

    async def clear(self, user_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthenticationSettings:
    challenge_ttl: timedelta
    session_ttl: timedelta
    max_verification_attempts: int
    resend_cooldown: timedelta
    daily_limit: int
    # TODO: remove this on production (see app/application/otp_test_numbers.py).
    test_numbers_enabled: bool = False
    # Non-empty: real SMS only to these E.164 numbers (staging). Empty: anyone.
    allowed_phones: frozenset[str] = frozenset()


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


logger = logging.getLogger("lottery_passport.auth")


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
        admin_totp: AdminTotpRepository,
    ) -> None:
        self._users = users
        self._challenges = challenges
        self._sessions = sessions
        self._code_generator = code_generator
        self._clock = clock
        self._sms_sender = sms_sender
        self._settings = settings
        self._admin_totp = admin_totp

    async def request_challenge(self, identifier: str) -> RequestChallengeResult:
        try:
            phone = normalize_iranian_mobile(identifier)
        except PhoneNumberError as error:
            raise PhoneInvalidError(str(error)) from error
        now = self._clock.now()
        # TODO: remove this on production (test numbers, otp_test_numbers.py).
        test_number = self._settings.test_numbers_enabled and is_test_phone_number(
            phone
        )
        if (
            self._settings.allowed_phones
            and not test_number
            and phone not in self._settings.allowed_phones
        ):
            # Before any lookup or write: no account, no challenge, no SMS.
            logger.warning(
                "otp_request_blocked",
                extra={"phone": mask_phone(phone), "reason": "not_allowed"},
            )
            raise PhoneNotAllowedError("this number is not on the allow-list")
        if not test_number and not has_known_mobile_prefix(phone):
            # Same principle: never call Kavenegar for a number that doesn't
            # look like a real carrier number. Warn instead of silently
            # failing or silently burning SMS credit on a typo.
            logger.warning(
                "otp_request_blocked",
                extra={"phone": mask_phone(phone), "reason": "unusual_prefix"},
            )
            raise PhoneUnusualError(
                "this number's prefix is not a known Iranian mobile range"
            )
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
            logger.warning(
                "otp_request_blocked",
                extra={"phone": mask_phone(phone), "reason": "inactive_account"},
            )
            return result

        recent = await self._challenges.get_most_recent_for_user(user.id)
        if recent is not None:
            elapsed_seconds = (now - recent.created_at).total_seconds()
            remaining = self._settings.resend_cooldown.total_seconds() - elapsed_seconds
            if remaining > 0:
                logger.info(
                    "otp_request_blocked",
                    extra={"phone": mask_phone(phone), "reason": "cooldown"},
                )
                raise ResendCooldownError(int(remaining) + 1)

        sent_in_last_24h = await self._challenges.count_created_since(
            user.id, now - timedelta(hours=24)
        )
        if sent_in_last_24h >= self._settings.daily_limit:
            logger.warning(
                "otp_request_blocked",
                extra={"phone": mask_phone(phone), "reason": "daily_limit"},
            )
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
        if test_number:
            await self._challenges.create(challenge)
            logger.info(
                "otp_issued",
                extra={
                    "phone": mask_phone(phone),
                    "purpose": purpose,
                    "delivery": "test_number",
                },
            )
            return replace(result, test_code=code)
        # Send before persisting: a delivery failure must not start the
        # resend cooldown or count against the daily limit for a code the
        # user never received.
        try:
            await self._sms_sender.send_otp(phone, code, purpose)
        except SmsError as error:
            logger.warning(
                "otp_delivery_failed",
                extra={"phone": mask_phone(phone), "purpose": purpose},
            )
            raise AuthenticationError("could not send verification code") from error
        await self._challenges.create(challenge)
        logger.info(
            "otp_issued",
            extra={"phone": mask_phone(phone), "purpose": purpose, "delivery": "sms"},
        )
        return result

    async def request_admin_challenge(self, identifier: str) -> RequestChallengeResult:
        """Send a sign-in code for the admin panel, but only to an active admin.

        Anyone else gets the same response and no SMS: the panel's sign-in form
        must not reveal who is an admin, nor spend SMS credit on strangers.
        """
        try:
            phone = normalize_iranian_mobile(identifier)
        except PhoneNumberError as error:
            raise PhoneInvalidError(str(error)) from error
        user = await self._users.get_by_identifier(phone)
        if not _is_active_admin(user):
            logger.warning(
                "admin_sign_in_refused",
                extra={"phone": mask_phone(phone), "reason": "not_an_admin"},
            )
            return RequestChallengeResult(
                resend_after_seconds=int(
                    self._settings.resend_cooldown.total_seconds()
                ),
                expires_in_seconds=int(self._settings.challenge_ttl.total_seconds()),
                code_length=self._code_generator.code_length,
            )
        return await self.request_challenge(phone)

    async def verify_admin_challenge(self, identifier: str, code: str) -> User:
        """Check a code for the admin panel. Creates no player session."""
        user, now, masked = await self._consume_code(identifier, code)
        if not _is_active_admin(user):
            logger.warning(
                "admin_sign_in_refused",
                extra={"phone": masked, "reason": "not_an_admin"},
            )
            raise AuthenticationError("invalid authentication challenge")
        if user.verification_status is not VerificationStatus.VERIFIED:
            user = await self._users.mark_verified(user.id, now)
        logger.info(
            "admin_sign_in_succeeded", extra={"phone": masked, "user_id": str(user.id)}
        )
        return user

    async def get_active_admin(self, user_id: UUID) -> User | None:
        """The admin behind an admin-panel session, re-checked on every request."""
        user = await self._users.get_by_id(user_id)
        return user if _is_active_admin(user) else None

    async def has_confirmed_admin_totp(self, user_id: UUID) -> bool:
        """True once this admin has confirmed a TOTP secret -- the signal the
        sign-in flow uses to decide whether a third (TOTP) step is required.
        Not enrolled is not an error: TOTP is opt-in per admin until the
        owner decides otherwise (docs/SECURITY.md T13)."""
        record = await self._admin_totp.get(user_id)
        return record is not None and record.confirmed_at is not None

    async def begin_admin_totp_enrollment(self, user_id: UUID) -> str:
        """Start (or resume) enrollment. Returns the base32 secret to show
        for manual entry in an authenticator app. Reusing a still-pending
        secret across reloads (rather than minting a new one each time)
        means scanning twice during one setup session doesn't desync."""
        user = await self._users.get_by_id(user_id)
        if not _is_active_admin(user):
            raise AuthenticationError("authentication required")
        existing = await self._admin_totp.get(user_id)
        if existing is not None and existing.confirmed_at is not None:
            raise AdminTotpAlreadyEnrolledError(
                "already enrolled; use scripts.admins reset-totp to start over"
            )
        if existing is not None:
            return existing.secret
        secret = generate_secret()
        await self._admin_totp.save_pending(user_id, secret, self._clock.now())
        logger.info("admin_totp_enrollment_started", extra={"user_id": str(user_id)})
        return secret

    async def confirm_admin_totp_enrollment(self, user_id: UUID, code: str) -> None:
        """Check one real code against the pending secret, and only then
        turn TOTP on for this admin. Raises on anything wrong; the pending
        secret is left untouched on a bad code so the admin can retry."""
        record = await self._admin_totp.get(user_id)
        if record is None or record.confirmed_at is not None:
            raise AdminTotpNotPendingError("no enrollment is in progress")
        try:
            matches = verify_code(record.secret, code)
        except TotpSecretError as error:
            raise AuthenticationError("invalid authentication challenge") from error
        if not matches:
            logger.warning(
                "admin_totp_enrollment_failed", extra={"user_id": str(user_id)}
            )
            raise AuthenticationError("invalid authentication challenge")
        await self._admin_totp.confirm(user_id, self._clock.now())
        logger.info("admin_totp_enrollment_confirmed", extra={"user_id": str(user_id)})

    async def verify_admin_totp(self, user_id: UUID, code: str) -> None:
        """Check a code for an already-confirmed secret (the sign-in gate).
        Raises on anything wrong; callers throttle repeated failures
        themselves (the admin session's own attempt counter), since this
        call has no challenge row of its own to rate-limit against."""
        record = await self._admin_totp.get(user_id)
        if record is None or record.confirmed_at is None:
            raise AuthenticationError("invalid authentication challenge")
        try:
            matches = verify_code(record.secret, code)
        except TotpSecretError as error:
            raise AuthenticationError("invalid authentication challenge") from error
        if not matches:
            logger.warning("admin_totp_verify_failed", extra={"user_id": str(user_id)})
            raise AuthenticationError("invalid authentication challenge")
        logger.info("admin_totp_verify_succeeded", extra={"user_id": str(user_id)})

    async def reset_admin_totp(self, identifier: str) -> bool:
        """CLI-only recovery (``scripts.admins reset-totp``) for a lost
        phone. Returns False if no such user exists."""
        user = await self._users.get_by_identifier(identifier)
        if user is None:
            return False
        await self._admin_totp.clear(user.id)
        return True

    async def verify_challenge(self, identifier: str, code: str) -> VerificationResult:
        user, now, masked = await self._consume_code(identifier, code)
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
        logger.info(
            "sign_in_succeeded",
            extra={"phone": masked, "user_id": str(user.id)},
        )
        return VerificationResult(user=user, session_token=session_token)

    async def _consume_code(
        self, identifier: str, code: str
    ) -> tuple[User, datetime, str]:
        """Check and use up a sign-in code. Returns the user, now, masked phone."""
        try:
            phone = normalize_iranian_mobile(identifier)
        except PhoneNumberError as error:
            raise AuthenticationError("invalid authentication challenge") from error
        now = self._clock.now()
        masked = mask_phone(phone)
        user = await self._users.get_by_identifier(phone)
        if user is None or user.account_status is AccountStatus.INACTIVE:
            self._log_verify_failed(masked, "unknown_or_inactive_user")
            raise AuthenticationError("invalid authentication challenge")

        challenge = await self._challenges.get_active_for_user(user.id, now)
        if challenge is None:
            self._log_verify_failed(masked, "no_active_code")
            raise AuthenticationError("invalid authentication challenge")
        if challenge.attempts >= challenge.max_attempts:
            self._log_verify_failed(masked, "attempts_exhausted")
            raise AuthenticationError("invalid authentication challenge")

        supplied_hash = self._code_generator.hash_code(code, challenge.code_salt)
        if not hmac.compare_digest(supplied_hash, challenge.code_hash):
            await self._challenges.increment_attempts(challenge.id)
            self._log_verify_failed(masked, "wrong_code")
            raise AuthenticationError("invalid authentication challenge")

        consumed = await self._challenges.consume_if_matching(
            challenge.id, supplied_hash, now
        )
        if not consumed:
            self._log_verify_failed(masked, "code_already_used")
            raise AuthenticationError("invalid authentication challenge")
        return user, now, masked

    @staticmethod
    def _log_verify_failed(masked_phone: str, reason: str) -> None:
        logger.warning(
            "otp_verify_failed", extra={"phone": masked_phone, "reason": reason}
        )

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
        if display_name is not None and is_reserved_name(display_name):
            raise DisplayNameReserved(display_name)
        user = await self._users.update_display_name(
            user_id, display_name, self._clock.now()
        )
        if user is None:
            raise AuthenticationError("authentication required")
        return user

    @staticmethod
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _is_active_admin(user: User | None) -> bool:
    return (
        user is not None
        and user.role is UserRole.ADMIN
        and user.account_status is AccountStatus.ACTIVE
    )
