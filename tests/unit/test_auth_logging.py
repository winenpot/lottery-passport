"""Auth events are logged for debugging, never with codes, tokens or full numbers."""

import logging

import pytest

from app.application.authentication import AuthenticationError, ResendCooldownError
from tests.unit.test_authentication import build_service

FULL_PHONE_DIGITS = "9123456789"
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


def logged_text(caplog: pytest.LogCaptureFixture) -> str:
    """Messages plus our extra fields (not timestamps or pids, which can collide)."""
    parts = []
    for record in caplog.records:
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD}
        parts.append(f"{record.getMessage()} {extras}")
    return " ".join(parts)


def lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "lottery_passport.auth"]


async def test_a_sign_in_logs_events_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    service, _, sms, _ = build_service()

    await service.request_challenge("0912 345 6789")
    code = sms.code or ""
    with pytest.raises(AuthenticationError):
        await service.verify_challenge("09123456789", "000000")
    result = await service.verify_challenge("09123456789", code)

    records = lines(caplog)
    assert [r.getMessage() for r in records] == [
        "otp_issued",
        "otp_verify_failed",
        "sign_in_succeeded",
    ]
    assert records[0].delivery == "sms"  # type: ignore[attr-defined]
    assert records[0].purpose == "signup"  # type: ignore[attr-defined]
    assert records[1].reason == "wrong_code"  # type: ignore[attr-defined]
    everything = logged_text(caplog)
    assert code not in everything
    assert result.session_token not in everything
    assert FULL_PHONE_DIGITS not in everything
    assert records[0].phone == "+98912***6789"  # type: ignore[attr-defined]


async def test_test_numbers_are_flagged_and_the_code_is_still_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    service, _, _, _ = build_service(test_numbers_enabled=True)

    result = await service.request_challenge("0969 000 0007")

    record = lines(caplog)[0]
    assert record.delivery == "test_number"  # type: ignore[attr-defined]
    assert result.test_code is not None
    assert result.test_code not in logged_text(caplog)


async def test_blocked_requests_say_why(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    service, _, _, _ = build_service()
    await service.request_challenge("0912 345 6789")

    with pytest.raises(ResendCooldownError):
        await service.request_challenge("0912 345 6789")

    assert lines(caplog)[-1].reason == "cooldown"  # type: ignore[attr-defined]
