"""RFC 6238 TOTP: the algorithm only, no storage, no encoding choices for
secrets at rest (that belongs to infrastructure, see
app/infrastructure/admin_totp.py).

Used for the admin panel's second factor (docs/launch-reports/2026-10-23-
handoff.md decision 8; docs/SECURITY.md T13). Deliberately stdlib-only, like
app/domain/phone.py: this is pure, framework-free arithmetic, not a vendor
integration.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
import time

# Google Authenticator's own defaults, and what every "scan this" app expects:
# 30-second steps, 6 digits, SHA-1. Changing any of these breaks compatibility
# with apps already enrolled, so they are constants, not settings.
TIME_STEP_SECONDS = 30
DIGITS = 6
_DIGITS_MOD = 10**DIGITS


class TotpSecretError(ValueError):
    """``secret`` is not valid base32 (RFC 4648, with or without padding)."""


def generate_secret() -> str:
    """A fresh random base32 secret (RFC 4648, no padding): 160 bits, the
    size `pyotp`-compatible apps and RFC 6238's own test vectors use."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    # Google Authenticator and most apps show/accept base32 without padding
    # and are tolerant of lowercase and stray spaces; match that leniency.
    cleaned = secret.strip().replace(" ", "").upper()
    padded = cleaned + "=" * (-len(cleaned) % 8)
    try:
        return base64.b32decode(padded)
    except binascii.Error as error:
        raise TotpSecretError(f"not a valid base32 secret: {secret!r}") from error


def generate_code(secret: str, *, at: float | None = None) -> str:
    """The code valid for the current (or ``at``) time step."""
    key = _decode_secret(secret)
    counter = int((at if at is not None else time.time()) // TIME_STEP_SECONDS)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{truncated % _DIGITS_MOD:0{DIGITS}d}"


def verify_code(
    secret: str, code: str, *, at: float | None = None, window: int = 1
) -> bool:
    """True if ``code`` matches the current time step or up to ``window``
    steps on either side (clock drift / the few seconds it takes to type it
    in). ``window=1`` is +/-30s, generous for a human, narrow enough that a
    brute-force guess still has to land in a 90-second, 1-in-a-million slot.
    """
    now = at if at is not None else time.time()
    for step in range(-window, window + 1):
        candidate = generate_code(secret, at=now + step * TIME_STEP_SECONDS)
        if hmac.compare_digest(candidate, code.strip()):
            return True
    return False
