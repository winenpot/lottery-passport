from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.authentication import (
    AdminTotpRecord,
    AuthenticationError,
    AuthenticationService,
    AuthenticationSettings,
    DailyLimitError,
    DisplayNameReserved,
    PhoneInvalidError,
    PhoneUnusualError,
    ResendCooldownError,
)
from app.domain.authentication import AuthenticatedSession, AuthenticationChallenge
from app.domain.totp import generate_code
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus
from app.infrastructure.authentication import SecureAuthenticationCodeGenerator

PHONE = "+989123456789"


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
            role=UserRole.PLAYER,
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

    async def get_most_recent_for_user(
        self, user_id: UUID
    ) -> AuthenticationChallenge | None:
        mine = [c for c in self.items.values() if c.user_id == user_id]
        return max(mine, key=lambda challenge: challenge.created_at) if mine else None

    async def count_created_since(self, user_id: UUID, since: datetime) -> int:
        return sum(
            1
            for challenge in self.items.values()
            if challenge.user_id == user_id and challenge.created_at >= since
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


class FakeSms:
    def __init__(self, *, fail: bool = False) -> None:
        self.code: str | None = None
        self.purpose: str | None = None
        self.phone: str | None = None
        self.fail = fail
        self.send_count = 0

    async def send_otp(self, phone: str, code: str, purpose: str) -> None:
        self.send_count += 1
        if self.fail:
            from app.application.authentication import SmsError

            raise SmsError("simulated delivery failure")
        self.phone = phone
        self.code = code
        self.purpose = purpose


class FakeAdminTotp:
    """In-memory stand-in for AdminTotpRepository: plaintext, no crypto --
    encryption at rest is an infrastructure concern (app/infrastructure/
    crypto.py), irrelevant to AuthenticationService's own behavior."""

    def __init__(self) -> None:
        self.items: dict[UUID, AdminTotpRecord] = {}

    async def get(self, user_id: UUID) -> AdminTotpRecord | None:
        return self.items.get(user_id)

    async def save_pending(self, user_id: UUID, secret: str, now: datetime) -> None:
        self.items[user_id] = AdminTotpRecord(secret=secret, confirmed_at=None)

    async def confirm(self, user_id: UUID, now: datetime) -> None:
        record = self.items[user_id]
        self.items[user_id] = AdminTotpRecord(secret=record.secret, confirmed_at=now)

    async def clear(self, user_id: UUID) -> None:
        self.items.pop(user_id, None)


def build_service(
    *,
    daily_limit: int = 5,
    resend_cooldown: timedelta = timedelta(seconds=60),
    test_numbers_enabled: bool = False,
    allowed_phones: frozenset[str] = frozenset(),
) -> tuple[AuthenticationService, FakeClock, FakeSms, FakeUsers]:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    sms = FakeSms()
    users = FakeUsers()
    service = AuthenticationService(
        users=users,
        challenges=FakeChallenges(),
        sessions=FakeSessions(),
        code_generator=FixedCodeGenerator(),
        clock=clock,
        sms_sender=sms,
        settings=AuthenticationSettings(
            challenge_ttl=timedelta(minutes=10),
            session_ttl=timedelta(hours=1),
            max_verification_attempts=2,
            resend_cooldown=resend_cooldown,
            daily_limit=daily_limit,
            test_numbers_enabled=test_numbers_enabled,
            allowed_phones=allowed_phones,
        ),
        admin_totp=FakeAdminTotp(),
    )
    return service, clock, sms, users


@pytest.mark.asyncio
async def test_authentication_verifies_once_and_logout_revokes_session() -> None:
    service, _, sms, _ = build_service()

    await service.request_challenge("0912 345 6789")
    result = await service.verify_challenge(PHONE, sms.code or "")
    current_user = await service.get_current_user(result.session_token)

    assert current_user.identifier == PHONE
    with pytest.raises(AuthenticationError):
        await service.verify_challenge(PHONE, sms.code or "")

    await service.logout(result.session_token)
    with pytest.raises(AuthenticationError):
        await service.get_current_user(result.session_token)


@pytest.mark.asyncio
async def test_authentication_rejects_expired_challenge() -> None:
    service, clock, sms, _ = build_service()

    await service.request_challenge(PHONE)
    clock.current += timedelta(minutes=11)

    with pytest.raises(AuthenticationError):
        await service.verify_challenge(PHONE, sms.code or "")


@pytest.mark.asyncio
async def test_authentication_limits_failed_verification_attempts() -> None:
    service, _, _, _ = build_service()

    await service.request_challenge(PHONE)
    for _ in range(2):
        with pytest.raises(AuthenticationError):
            await service.verify_challenge(PHONE, "000000")

    with pytest.raises(AuthenticationError):
        await service.verify_challenge(PHONE, "123456")


@pytest.mark.asyncio
async def test_inactive_user_cannot_verify() -> None:
    service, _, sms, users = build_service()

    await service.request_challenge(PHONE)
    user = await users.get_by_identifier(PHONE)
    assert user is not None
    user.account_status = AccountStatus.INACTIVE

    with pytest.raises(AuthenticationError):
        await service.verify_challenge(PHONE, sms.code or "")


@pytest.mark.asyncio
async def test_request_challenge_rejects_a_non_iranian_number() -> None:
    service, _, _, _ = build_service()

    with pytest.raises(PhoneInvalidError):
        await service.request_challenge("+1 212 555 0100")


@pytest.mark.asyncio
async def test_request_challenge_rejects_an_unusual_prefix_without_sending_sms() -> (
    None
):
    service, _, sms, _ = build_service()

    # 940 is shape-valid (9 followed by 9 digits) but not a known range.
    with pytest.raises(PhoneUnusualError):
        await service.request_challenge("0940 123 4567")

    assert sms.send_count == 0


@pytest.mark.asyncio
async def test_a_test_number_bypasses_the_unusual_prefix_check() -> None:
    service, _, sms, _ = build_service(test_numbers_enabled=True)

    # 969 is deliberately not a known carrier range, but test numbers must
    # still work when enabled: they never reach the SMS sender anyway.
    result = await service.request_challenge("0969 123 4567")

    assert result.test_code is not None
    assert sms.send_count == 0


@pytest.mark.asyncio
async def test_request_challenge_returns_the_contract_shape() -> None:
    service, _, _, _ = build_service(resend_cooldown=timedelta(seconds=60))

    result = await service.request_challenge(PHONE)

    assert result.resend_after_seconds == 60
    assert result.expires_in_seconds == 600
    assert result.code_length == 6


@pytest.mark.asyncio
async def test_resend_before_the_cooldown_is_rejected() -> None:
    service, clock, _, _ = build_service(resend_cooldown=timedelta(seconds=60))

    await service.request_challenge(PHONE)
    clock.current += timedelta(seconds=10)

    with pytest.raises(ResendCooldownError) as excinfo:
        await service.request_challenge(PHONE)
    assert excinfo.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_resend_after_the_cooldown_succeeds() -> None:
    service, clock, sms, _ = build_service(resend_cooldown=timedelta(seconds=60))

    await service.request_challenge(PHONE)
    clock.current += timedelta(seconds=61)
    await service.request_challenge(PHONE)

    assert sms.send_count == 2


@pytest.mark.asyncio
async def test_daily_limit_is_enforced() -> None:
    service, clock, _, _ = build_service(
        daily_limit=2, resend_cooldown=timedelta(seconds=0)
    )

    await service.request_challenge(PHONE)
    clock.current += timedelta(seconds=1)
    await service.request_challenge(PHONE)
    clock.current += timedelta(seconds=1)

    with pytest.raises(DailyLimitError):
        await service.request_challenge(PHONE)


@pytest.mark.asyncio
async def test_a_delivery_failure_does_not_start_the_cooldown() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    sms = FakeSms(fail=True)
    users = FakeUsers()
    service = AuthenticationService(
        users=users,
        challenges=FakeChallenges(),
        sessions=FakeSessions(),
        code_generator=FixedCodeGenerator(),
        clock=clock,
        sms_sender=sms,
        settings=AuthenticationSettings(
            challenge_ttl=timedelta(minutes=10),
            session_ttl=timedelta(hours=1),
            max_verification_attempts=2,
            resend_cooldown=timedelta(seconds=60),
            daily_limit=5,
        ),
        admin_totp=FakeAdminTotp(),
    )

    with pytest.raises(AuthenticationError):
        await service.request_challenge(PHONE)

    # Immediately retrying must not hit the cooldown: nothing was persisted.
    sms.fail = False
    await service.request_challenge(PHONE)
    assert sms.send_count == 2


@pytest.mark.asyncio
async def test_a_test_number_gets_its_code_in_the_response_without_sms() -> None:
    service, _, sms, _ = build_service(test_numbers_enabled=True)

    result = await service.request_challenge("0969 000 0007")
    signed_in = await service.verify_challenge("+989690000007", result.test_code or "")

    assert result.test_code == "123456"
    assert sms.send_count == 0
    assert signed_in.user.identifier == "+989690000007"


@pytest.mark.asyncio
async def test_real_numbers_use_sms_regardless_of_test_mode() -> None:
    enabled, _, enabled_sms, _ = build_service(test_numbers_enabled=True)
    disabled, _, disabled_sms, _ = build_service(test_numbers_enabled=False)

    real = await enabled.request_challenge("0912 345 6789")
    also_real = await disabled.request_challenge("0913 345 6789")

    assert real.test_code is None and enabled_sms.send_count == 1
    assert also_real.test_code is None and disabled_sms.send_count == 1


@pytest.mark.asyncio
async def test_a_969_number_is_unusual_when_test_mode_is_disabled() -> None:
    # 969 is not an allocated carrier range: with the test-number shortcut
    # off, it must be rejected as unusual, never silently treated as a real
    # number and sent to Kavenegar (the previous behavior, before the
    # unusual-prefix guard existed).
    disabled, _, disabled_sms, _ = build_service(test_numbers_enabled=False)

    with pytest.raises(PhoneUnusualError):
        await disabled.request_challenge("0969 000 0007")

    assert disabled_sms.send_count == 0


@pytest.mark.asyncio
async def test_first_request_sends_the_signup_purpose_later_ones_login() -> None:
    service, clock, sms, _ = build_service(resend_cooldown=timedelta(seconds=0))

    await service.request_challenge(PHONE)
    assert sms.purpose == "signup"

    clock.current += timedelta(seconds=1)
    await service.request_challenge(PHONE)
    assert sms.purpose == "login"


@pytest.mark.asyncio
async def test_reserved_display_names_are_rejected_unlike_the_old_demo_field() -> None:
    # display_name has no charset restriction of its own (legacy field), so
    # without this check "Lich King" -- which the nickname rules already
    # reject outright, charset and reserved list both -- would slip through.
    service, _, _, users = build_service()
    user = await users.create(PHONE, datetime(2026, 1, 1, tzinfo=UTC))

    with pytest.raises(DisplayNameReserved):
        await service.update_display_name(user.id, "Lich King")

    unchanged = await users.get_by_id(user.id)
    assert unchanged is not None and unchanged.display_name is None


@pytest.mark.asyncio
async def test_a_non_reserved_display_name_is_still_accepted() -> None:
    service, _, _, users = build_service()
    user = await users.create(PHONE, datetime(2026, 1, 1, tzinfo=UTC))

    updated = await service.update_display_name(user.id, "Phase Two")

    assert updated.display_name == "Phase Two"


async def _admin_user(service: AuthenticationService, users: FakeUsers) -> User:
    admin = await users.create(PHONE, datetime(2026, 1, 1, tzinfo=UTC))
    admin.role = UserRole.ADMIN
    return admin


@pytest.mark.asyncio
async def test_enrollment_confirms_with_a_real_code_and_then_gates_sign_in() -> None:
    service, _, _, users = build_service()
    admin = await _admin_user(service, users)

    secret = await service.begin_admin_totp_enrollment(admin.id)
    assert not await service.has_confirmed_admin_totp(admin.id)

    await service.confirm_admin_totp_enrollment(admin.id, generate_code(secret))

    assert await service.has_confirmed_admin_totp(admin.id)
    # And the same secret now gates sign-in verification too.
    await service.verify_admin_totp(admin.id, generate_code(secret))


@pytest.mark.asyncio
async def test_a_wrong_code_does_not_confirm_enrollment() -> None:
    service, _, _, users = build_service()
    admin = await _admin_user(service, users)
    await service.begin_admin_totp_enrollment(admin.id)

    with pytest.raises(AuthenticationError):
        await service.confirm_admin_totp_enrollment(admin.id, "000000")

    assert not await service.has_confirmed_admin_totp(admin.id)


@pytest.mark.asyncio
async def test_reloading_mid_enrollment_returns_the_same_pending_secret() -> None:
    service, _, _, users = build_service()
    admin = await _admin_user(service, users)

    first = await service.begin_admin_totp_enrollment(admin.id)
    second = await service.begin_admin_totp_enrollment(admin.id)

    assert first == second


@pytest.mark.asyncio
async def test_cannot_re_enroll_once_confirmed() -> None:
    from app.application.authentication import AdminTotpAlreadyEnrolledError

    service, _, _, users = build_service()
    admin = await _admin_user(service, users)
    secret = await service.begin_admin_totp_enrollment(admin.id)
    await service.confirm_admin_totp_enrollment(admin.id, generate_code(secret))

    with pytest.raises(AdminTotpAlreadyEnrolledError):
        await service.begin_admin_totp_enrollment(admin.id)


@pytest.mark.asyncio
async def test_verify_admin_totp_rejects_an_admin_who_never_enrolled() -> None:
    service, _, _, users = build_service()
    admin = await _admin_user(service, users)

    with pytest.raises(AuthenticationError):
        await service.verify_admin_totp(admin.id, "123456")


@pytest.mark.asyncio
async def test_reset_admin_totp_clears_an_enrolled_secret() -> None:
    service, _, _, users = build_service()
    admin = await _admin_user(service, users)
    secret = await service.begin_admin_totp_enrollment(admin.id)
    await service.confirm_admin_totp_enrollment(admin.id, generate_code(secret))

    assert await service.reset_admin_totp(PHONE)

    assert not await service.has_confirmed_admin_totp(admin.id)
    # And enrollment can start fresh afterwards.
    await service.begin_admin_totp_enrollment(admin.id)


@pytest.mark.asyncio
async def test_reset_admin_totp_on_an_unknown_identifier_returns_false() -> None:
    service, _, _, _ = build_service()

    assert not await service.reset_admin_totp("+989000000000")
