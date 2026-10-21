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

# Names players may not take (compared on the folded key). Staff, brand,
# lounge and trademarked/franchise names are added here; the owner maintains
# this list (a set, so a repeated addition is still just one entry). Used two
# ways: `parse_nickname` below checks the exact folded key (nicknames never
# contain spaces, so write multi-word entries only for `is_reserved_name`'s
# benefit); `is_reserved_name` checks the collapsed (whitespace/punctuation
# stripped) form, for free-text fields such as `display_name` that have no
# charset restriction of their own.
RESERVED_KEYS = frozenset(
    {
        "admin",
        "administrator",
        "support",
        "staff",
        "system",
        "moderator",
        "torshx",
        "lich king",  # trademarked (World of Warcraft); collapses to "lichking"
    }
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
    if key in RESERVED_KEYS or is_reserved_name(value):
        raise NicknameError("this name is reserved")
    return Nickname(display=value, key=key)


def _collapse(text: str) -> str:
    """Case/variant-folded, alphanumeric-only: letters only, no spaces,
    punctuation or Persian digits (already ASCII-folded by ``_FOLD``)."""
    folded = unicodedata.normalize("NFC", text).casefold().translate(_FOLD)
    return "".join(char for char in folded if char.isalnum())


_RESERVED_COLLAPSED = frozenset(_collapse(key) for key in RESERVED_KEYS)


def is_reserved_name(raw: str) -> bool:
    """``True`` if ``raw`` collapses to a reserved key.

    Looser than the nickname charset: for free-text fields such as
    ``display_name`` that allow spaces and punctuation the nickname rules
    reject outright, so "Lich King", "lich_king" and "LichKing" all match.
    """
    return _collapse(raw) in _RESERVED_COLLAPSED
