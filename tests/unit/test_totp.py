import base64
import time

import pytest

from app.domain.totp import (
    TIME_STEP_SECONDS,
    TotpSecretError,
    generate_code,
    generate_secret,
    verify_code,
)

# RFC 6238 Appendix B's SHA-1 vector uses an 8-digit truncation of the same
# HOTP/TOTP algorithm over a secret whose bytes are literally
# "12345678901234567890" (not base32 of that text). Re-deriving it here
# pins this implementation to the standard, not just to itself.
_RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii").rstrip("=")


def test_matches_the_rfc_6238_vector_at_59_seconds() -> None:
    # RFC 6238 Appendix B, T=59s: full 8-digit code is 94287082; we only
    # produce 6 digits (Google Authenticator's format), so compare the tail.
    assert generate_code(_RFC_SECRET, at=59) == "287082"


def test_matches_the_rfc_6238_vector_at_a_later_time() -> None:
    # T=1111111109s: full 8-digit code is 07081804.
    assert generate_code(_RFC_SECRET, at=1_111_111_109) == "081804"


def test_a_fresh_secret_round_trips_through_generate_and_verify() -> None:
    secret = generate_secret()
    now = time.time()
    assert verify_code(secret, generate_code(secret, at=now), at=now)


def test_verify_accepts_one_step_of_clock_drift() -> None:
    secret = generate_secret()
    now = 1_000_000.0
    code_one_step_ago = generate_code(secret, at=now - TIME_STEP_SECONDS)
    assert verify_code(secret, code_one_step_ago, at=now)


def test_verify_rejects_two_steps_of_drift() -> None:
    secret = generate_secret()
    now = 1_000_000.0
    code_two_steps_ago = generate_code(secret, at=now - 2 * TIME_STEP_SECONDS)
    assert not verify_code(secret, code_two_steps_ago, at=now)


def test_verify_rejects_a_wrong_code() -> None:
    secret = generate_secret()
    now = time.time()
    real_code = generate_code(secret, at=now)
    wrong_code = f"{(int(real_code) + 1) % 1_000_000:06d}"
    assert not verify_code(secret, wrong_code, at=now)


def test_a_malformed_secret_raises_totp_secret_error() -> None:
    with pytest.raises(TotpSecretError):
        generate_code("not valid base32 !!!")


def test_lowercase_and_spaces_in_the_secret_are_tolerated() -> None:
    # Apps and admins type/paste secrets inconsistently; matches
    # app/domain/phone.py's leniency for human-entered values.
    secret = generate_secret()
    now = time.time()
    code = generate_code(secret, at=now)
    spaced = " ".join(secret.lower()[i : i + 4] for i in range(0, len(secret), 4))
    assert verify_code(spaced, code, at=now)
