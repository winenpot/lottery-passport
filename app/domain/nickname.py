"""Nickname rules (docs/SECURITY.md#user-generated-text, threat T11).

Nicknames are public on leaderboards, so the allowed alphabet is a short
whitelist: anything not listed (bidi controls, zero-width characters, emoji,
look-alike scripts, spaces) is rejected instead of being blacklisted.
"""

import unicodedata
from dataclasses import dataclass

NICKNAME_MIN_LENGTH = 3
NICKNAME_MAX_LENGTH = 16

ZWNJ = "\u200c"

# Names players may not take (compared on the folded key). Staff, brand and
# lounge names are added here; the profanity list is maintained by the owner.
RESERVED_KEYS = frozenset(
    {"admin", "administrator", "support", "staff", "system", "moderator", "torshx"}
)

_PERSIAN_LETTER_RANGES = (
    (0x0621, 0x063A),  # hamza .. ghain (includes Arabic yeh/kaf variants)
    (0x0641, 0x064A),  # feh .. yeh
    (0x067E, 0x067E),  # peh
    (0x0686, 0x0686),  # cheh
    (0x0698, 0x0698),  # jeh
    (0x06A9, 0x06A9),  # Persian kaf
    (0x06AF, 0x06AF),  # gaf
    (0x06CC, 0x06CC),  # Persian yeh
)
_PERSIAN_DIGITS = range(0x06F0, 0x06FA)
_ASCII_PUNCTUATION = "_.-"
_FOLD: dict[int, str] = {
    0x064A: "\u06cc",  # Arabic yeh -> Persian yeh
    0x0643: "\u06a9",  # Arabic kaf -> Persian kaf
    **{0x06F0 + i: str(i) for i in range(10)},  # Persian digits -> ASCII
}


class NicknameError(ValueError):
    """The nickname breaks a rule; ``str(error)`` is a short English reason."""


@dataclass(frozen=True, slots=True)
class Nickname:
    display: str  # what players see
    key: str  # case/variant-folded form the uniqueness check uses


def _is_allowed(char: str) -> bool:
    if char == ZWNJ or char in _ASCII_PUNCTUATION:
        return True
    if char.isascii():
        return char.isalnum()
    code = ord(char)
    if code in _PERSIAN_DIGITS:
        return True
    return any(low <= code <= high for low, high in _PERSIAN_LETTER_RANGES)


def parse_nickname(raw: str) -> Nickname:
    value = " ".join(unicodedata.normalize("NFC", raw).split())
    if not NICKNAME_MIN_LENGTH <= len(value) <= NICKNAME_MAX_LENGTH:
        raise NicknameError(
            f"must be {NICKNAME_MIN_LENGTH}-{NICKNAME_MAX_LENGTH} characters"
        )
    if any(not _is_allowed(char) for char in value):
        raise NicknameError(
            "may only contain letters, digits, '_', '.', '-' and Persian letters"
        )
    if value.startswith(ZWNJ) or value.endswith(ZWNJ) or ZWNJ * 2 in value:
        raise NicknameError("misplaced zero-width non-joiner")
    key = value.casefold().translate(_FOLD)
    if key in RESERVED_KEYS:
        raise NicknameError("this name is reserved")
    return Nickname(display=value, key=key)
