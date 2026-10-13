"""Fixed phone numbers for frontend testing without SMS (demo/development only).

A sign-in request for one of these numbers gets a normal random code, but the
code is returned in the ``POST /auth/request`` response instead of being sent
by SMS. Every other number goes through the real OTP path untouched.

TODO: remove this on production. It is also switched off by environment
(``AuthenticationSettings.test_numbers_enabled`` is false on staging and
production, see app/app.py), so a forgotten list cannot open accounts there.

The numbers are 0900 000 0001 .. 0900 000 0040 (+98 900 000 00xx).
"""

TEST_PHONE_NUMBERS: frozenset[str] = frozenset(
    f"+98900000{n:04d}" for n in range(1, 41)
)
