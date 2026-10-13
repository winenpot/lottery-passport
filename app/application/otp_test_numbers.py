"""Test phone numbers for frontend testing without SMS (demo/development only).

Every number starting 0969 (``+98969`` + 7 digits, 10^7 numbers) is a test
number. A sign-in request for one gets a normal random code, but the code is
returned in the ``POST /auth/request`` response instead of being sent by SMS.
Every other number goes through the real OTP path untouched.

0969 is not assigned to any Iranian operator as far as we know (2026-10-13,
from public prefix lists, not an official CRA list). That can change; the real
safety is the environment switch below, not the prefix.

TODO: remove this on production. It is also switched off by environment
(``AuthenticationSettings.test_numbers_enabled`` is false on staging and
production, see app/app.py), so a forgotten check cannot open accounts there.
Tracked in docs/SECURITY.md (pre-launch checklist).
"""

TEST_PHONE_PREFIX = "+98969"


def is_test_phone_number(phone: str) -> bool:
    """``phone`` must already be normalized (``+989XXXXXXXXX``)."""
    return phone.startswith(TEST_PHONE_PREFIX)
