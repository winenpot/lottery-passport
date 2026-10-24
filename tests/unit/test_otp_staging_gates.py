"""Staging SMS gates (S5): OTP_TEST_NUMBERS and OTP_ALLOWED_PHONES.

A public staging server that texts any number is an SMS relay. Staging sends real
SMS only to the team's numbers; 0969 test numbers still work without SMS.
Production refuses both knobs.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_authentication_service
from app.app import create_app
from app.application.authentication import PhoneNotAllowedError
from app.core.config import Settings
from tests.unit.test_authentication import build_service

TEAM = "+989120000001"  # fake; FakeSms never sends anything
STRANGER = "+989120000002"
TEST_NUMBER = "+989690000003"
DB = "postgresql+asyncpg://app:secret@postgres:5432/db"


# --- service --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_listed_number_gets_a_real_sms() -> None:
    service, _, sms, _ = build_service(allowed_phones=frozenset({TEAM}))

    await service.request_challenge("0912 000 0001")

    assert sms.send_count == 1 and sms.phone == TEAM


@pytest.mark.asyncio
async def test_an_unlisted_number_is_refused_before_anything_is_written() -> None:
    service, _, sms, users = build_service(allowed_phones=frozenset({TEAM}))

    with pytest.raises(PhoneNotAllowedError):
        await service.request_challenge(STRANGER)

    assert sms.send_count == 0
    assert users.items == {}  # no account created for a stranger


@pytest.mark.asyncio
async def test_test_numbers_bypass_the_list_without_sms() -> None:
    service, _, sms, _ = build_service(
        allowed_phones=frozenset({TEAM}), test_numbers_enabled=True
    )

    result = await service.request_challenge(TEST_NUMBER)

    assert result.test_code is not None
    assert sms.send_count == 0


@pytest.mark.asyncio
async def test_test_numbers_are_refused_when_test_numbers_are_off() -> None:
    service, _, sms, _ = build_service(allowed_phones=frozenset({TEAM}))

    with pytest.raises(PhoneNotAllowedError):
        await service.request_challenge(TEST_NUMBER)

    assert sms.send_count == 0


@pytest.mark.asyncio
async def test_an_empty_list_lets_anyone_in() -> None:
    service, _, sms, _ = build_service()

    await service.request_challenge(STRANGER)

    assert sms.send_count == 1


# --- settings -------------------------------------------------------------


def staging(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "staging",
        "database_url": DB,
        "redemption_code_pepper": "p" * 48,
        "admin_session_secret": "a" * 48,
        "admin_totp_encryption_key": "k" * 48,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_the_list_is_normalized() -> None:
    settings = staging(otp_allowed_phones="0912 000 0001, +989120000002")

    assert settings.allowed_otp_phones == frozenset({TEAM, STRANGER})


def test_a_malformed_number_stops_startup_without_echoing_it() -> None:
    with pytest.raises(ValidationError, match="OTP_ALLOWED_PHONES has an invalid"):
        staging(otp_allowed_phones="0912, nonsense")


def test_test_numbers_default_to_development_and_demo_only() -> None:
    assert staging().test_numbers_enabled is False
    assert staging(environment="demo").test_numbers_enabled is True
    assert staging(otp_test_numbers=True).test_numbers_enabled is True


@pytest.mark.parametrize(
    "overrides",
    [{"otp_test_numbers": True}, {"otp_allowed_phones": "09120000001"}],
)
def test_production_refuses_both_knobs(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="not allowed in production"):
        staging(environment="production", **overrides)


# --- HTTP -----------------------------------------------------------------


def test_an_unlisted_number_gets_403_phone_not_allowed() -> None:
    service, _, sms, _ = build_service(allowed_phones=frozenset({TEAM}))
    application = create_app(Settings(database_url=DB))
    application.dependency_overrides[get_authentication_service] = lambda: service

    response = TestClient(application).post(
        "/api/v1/auth/request", json={"identifier": STRANGER}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PHONE_NOT_ALLOWED"
    assert sms.send_count == 0
