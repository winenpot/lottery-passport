"""Normalize an Iranian mobile number to one canonical E.164 form.

Players type a phone number every way a keyboard allows: Persian or Arabic
digits, spaces, dashes, a leading ``0``, ``98``, ``0098`` or ``+98``. This
turns any of those into ``+989XXXXXXXXX`` or raises.
"""

import re

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "0123456789"
_DIGIT_TRANSLATION = str.maketrans(_PERSIAN_DIGITS + _ARABIC_DIGITS, _ASCII_DIGITS * 2)

# After every prefix is stripped, an Iranian mobile subscriber number is
# exactly 9 digits starting with 9 (e.g. "912 345 6789").
_SUBSCRIBER_NUMBER = re.compile(r"^9\d{9}$")

# Longest prefix first, so "0098" isn't matched as "0" + "098...".
_COUNTRY_PREFIXES = ("+98", "0098", "98", "0")


class PhoneNumberError(ValueError):
    """Not an Iranian mobile number, after every normalization attempted."""


# Publicly known allocated Iranian mobile ranges (subscriber prefix, i.e. the
# 3 digits right after the leading 0/+98: "0912..." -> 912). Sourced from
# public prefix lists, not an official CRA list (no list is official; the
# CRA can allocate a new one at any time). This is a SOFT warning signal for
# "does this look like a real carrier number", never a hard validity gate:
# a legitimate new range would otherwise get permanently misclassified.
# 0969 (the test-number range, app/application/otp_test_numbers.py) is
# deliberately NOT in this set.
KNOWN_MOBILE_PREFIXES: frozenset[int] = frozenset(
    [
        *range(900, 906),
        *range(910, 920),
        *range(920, 924),
        *range(930, 940),
        941,
        955,
        971,
        *range(990, 995),
        998,
        999,
    ]
)


def has_known_mobile_prefix(phone: str) -> bool:
    """Best-effort check that ``phone`` (already ``+989XXXXXXXXX``) is on a
    publicly known allocated range. False does not mean the number is
    invalid, only unusual: callers decide what to do with that (e.g. warn
    without sending SMS, rather than reject outright)."""
    prefix = phone.removeprefix("+98")[:3]
    return prefix.isdigit() and int(prefix) in KNOWN_MOBILE_PREFIXES


def normalize_iranian_mobile(raw: str) -> str:
    """Return ``+989XXXXXXXXX``, or raise :class:`PhoneNumberError`."""
    ascii_digits_and_plus = raw.translate(_DIGIT_TRANSLATION)
    cleaned = re.sub(r"[^\d+]", "", ascii_digits_and_plus)
    if not cleaned:
        raise PhoneNumberError("empty phone number")

    for prefix in _COUNTRY_PREFIXES:
        if cleaned.startswith(prefix):
            remainder = cleaned[len(prefix) :]
            break
    else:
        remainder = cleaned

    if not _SUBSCRIBER_NUMBER.match(remainder):
        raise PhoneNumberError(f"not an Iranian mobile number: {raw!r}")
    return f"+98{remainder}"


def mask_phone(phone: str) -> str:
    """``+989121234567`` -> ``+98912***4567``: for logs, never the full number."""
    if len(phone) <= 8:
        return "***"
    return f"{phone[:6]}***{phone[-4:]}"
