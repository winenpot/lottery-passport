"""The test suite must never reach the SMS provider, whatever the shell exports."""

import os

from app.core.config import Settings


def test_the_sms_key_is_not_visible_to_tests() -> None:
    assert "KAVENEGAR_OTP_API_KEY" not in os.environ
    assert Settings(_env_file=None).kavenegar_otp_api_key is None  # type: ignore[call-arg]
