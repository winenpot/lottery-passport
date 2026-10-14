"""Printed product codes: a city prefix + random body + one check character.

The shape of a code is described by a :class:`CodeFormat` (alphabet, body
length, printed grouping, look-alike aliases). Formats are registered in
:data:`FORMATS` by id; new batches use :data:`DEFAULT_FORMAT_ID` unless told
otherwise. Adding a format is one ``register_format`` call (see
``docs/CODES.md``).

Layout of a canonical code in the default ``v2-b10`` format (13 characters)::

    TO 7KQ2M9XH4R 6
    ^^ ^^^^^^^^^^ ^
    |  |          +-- check character (Luhn mod N over city index + body)
    |  +------------- 10 random Crockford Base32 characters = 50 bits
    +---------------- city prefix, one per SKU (see ``CityCode``)

Printed form groups the characters for humans: ``TO-7KQ2-M9XH-4R6``.

Why this shape (details in ``docs/CODES.md``):

* Enough random bits make guessing hopeless; ``CodeFormat.entropy_bits``
  states how many a format has.
* Crockford Base32 has no I, L, O or U, so the characters people confuse on
  a printed cap are folded together on input (O->0, I/L->1).
* The check character lets the client and server say "you mistyped a
  character" without a database lookup, and it reveals nothing an attacker
  could not compute anyway.

Everything in this module is pure and framework-free. A format's spec and the
city indexes are part of every printed code: once a batch is exported its
format is frozen by :meth:`CodeFormat.fingerprint`, and a changed spec is
refused at startup.
"""

import hashlib
import json
import math
import secrets
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.passports import CityCode

PREFIX_LENGTH = 2

# Frozen: the check character mixes in the city, so these numbers are part of
# every printed code. Never renumber; only append new cities.
CITY_CHECK_INDEX: dict[CityCode, int] = {
    CityCode.PARIS: 1,
    CityCode.BERLIN: 2,
    CityCode.PATTAYA: 3,
    CityCode.MEXICO: 4,
    CityCode.MADRID: 5,
    CityCode.TOKYO: 6,
    CityCode.MOSCOW: 7,
}

_CITY_BY_PREFIX = {city.value: city for city in CityCode}

# Persian (U+06F0..U+06F9) and Arabic-Indic (U+0660..U+0669) digits are not
# folded to ASCII by NFKC, and Iranian keyboards produce them by default.
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# Characters people type for the ones Crockford Base32 leaves out.
CROCKFORD_ALIASES = {"O": "0", "I": "1", "L": "1"}


class CodeProblem(StrEnum):
    """Why a typed code was rejected before any database lookup."""

    MALFORMED = "malformed"
    MISTYPED = "mistyped"


class CodeFormatError(ValueError):
    """Raised when user input cannot be a valid code."""

    def __init__(self, problem: CodeProblem) -> None:
        super().__init__(problem.value)
        self.problem = problem


class FormatRegistryError(ValueError):
    """Raised when a format spec is invalid, unknown or clashes with another."""


@dataclass(frozen=True, slots=True, eq=True)
class CodeFormat:
    """Everything that decides how a code looks and is checked.

    ``grouping`` splits the characters after the prefix for printing, e.g.
    ``(4, 4, 3)`` gives ``TO-7KQ2-M9XH-4R6``; it must add up to
    ``body_length + 1`` (the body plus the check character). ``aliases``
    maps characters people type to the alphabet characters they mean.
    """

    format_id: str
    body_length: int
    grouping: tuple[int, ...]
    alphabet: str = CROCKFORD_BASE32
    aliases: dict[str, str] = field(default_factory=lambda: dict(CROCKFORD_ALIASES))
    check_scheme: str = "luhn-mod-n"

    __hash__ = None  # type: ignore[assignment]  # holds a dict; never hashed

    def __post_init__(self) -> None:
        if not self.format_id or not self.format_id.isascii():
            raise FormatRegistryError("format_id must be non-empty ASCII")
        alphabet = self.alphabet
        if len(alphabet) < 2 or len(set(alphabet)) != len(alphabet):
            raise FormatRegistryError("alphabet needs 2+ distinct characters")
        if not alphabet.isascii() or alphabet != alphabet.upper():
            raise FormatRegistryError("alphabet must be upper-case ASCII")
        if self.body_length < 1:
            raise FormatRegistryError("body_length must be positive")
        if not self.grouping or min(self.grouping) < 1:
            raise FormatRegistryError("grouping needs positive group sizes")
        if sum(self.grouping) != self.body_length + 1:
            raise FormatRegistryError("grouping must add up to body_length + 1")
        for typed, meant in self.aliases.items():
            if typed in alphabet or meant not in alphabet:
                raise FormatRegistryError(f"bad alias {typed!r} -> {meant!r}")
        if self.check_scheme != "luhn-mod-n":
            raise FormatRegistryError(f"unknown check scheme {self.check_scheme!r}")
        if max(CITY_CHECK_INDEX.values()) >= len(alphabet):
            raise FormatRegistryError("alphabet too small for the city indexes")

    @property
    def base(self) -> int:
        return len(self.alphabet)

    @property
    def canonical_length(self) -> int:
        return PREFIX_LENGTH + self.body_length + 1

    @property
    def entropy_bits(self) -> float:
        """Random bits per code: what a guesser is up against."""
        return self.body_length * math.log2(self.base)

    def spec(self) -> dict[str, object]:
        """The frozen part of the format, as plain JSON-able data."""
        return {
            "format_id": self.format_id,
            "alphabet": self.alphabet,
            "body_length": self.body_length,
            "grouping": list(self.grouping),
            "aliases": dict(sorted(self.aliases.items())),
            "check_scheme": self.check_scheme,
            "prefix_length": PREFIX_LENGTH,
            "city_check_index": {c.value: i for c, i in CITY_CHECK_INDEX.items()},
        }

    def fingerprint(self) -> str:
        """SHA-256 of :meth:`spec`; stored on a batch when it is frozen."""
        encoded = json.dumps(self.spec(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


V2_B10 = CodeFormat(format_id="v2-b10", body_length=10, grouping=(4, 4, 3))

# Current default (decision 2026-10-10): 2-letter city + 9 characters printed
# as 3-3-3 (8 random characters + 1 check character). The QR carries it in
# the path, ``https://torshx.com/b/TO-ABC-DEF-GHJ`` (decision 2026-10-14;
# the fragment form ``/r#CODE`` is still parsed). v2-b10 stays registered:
# nothing has been printed in either format yet, but the registry never
# un-registers a format once real codes could exist under it.
CITY2_B9 = CodeFormat(format_id="city2-b9", body_length=8, grouping=(3, 3, 3))

FORMATS: dict[str, CodeFormat] = {}
DEFAULT_FORMAT_ID = CITY2_B9.format_id


def register_format(code_format: CodeFormat) -> CodeFormat:
    """Add a format. Parsing picks the format by length, so lengths differ."""
    existing = FORMATS.get(code_format.format_id)
    if existing is not None:
        if existing == code_format:
            return existing
        raise FormatRegistryError(f"{code_format.format_id} is already registered")
    for other in FORMATS.values():
        if other.canonical_length == code_format.canonical_length:
            raise FormatRegistryError(
                f"{code_format.format_id} has the same length as {other.format_id}"
            )
    FORMATS[code_format.format_id] = code_format
    return code_format


def unregister_format(format_id: str) -> None:
    """Remove a format. For tests only: never unregister a printed format."""
    if format_id == DEFAULT_FORMAT_ID:
        raise FormatRegistryError("the default format cannot be unregistered")
    FORMATS.pop(format_id, None)


def get_format(format_id: str = "") -> CodeFormat:
    """Return a registered format; empty means the default one."""
    try:
        return FORMATS[format_id or DEFAULT_FORMAT_ID]
    except KeyError:
        raise FormatRegistryError(f"unknown code format {format_id!r}") from None


register_format(V2_B10)
register_format(CITY2_B9)

# Names kept for callers written before formats were pluggable (default format).
ALPHABET = V2_B10.alphabet
BASE = V2_B10.base
BODY_LENGTH = V2_B10.body_length
CANONICAL_LENGTH = V2_B10.canonical_length


def verify_frozen_formats(frozen: list[tuple[str, str]]) -> None:
    """Fail loudly if a frozen batch's format no longer matches the code.

    ``frozen`` is a list of ``(format_id, format_fingerprint)`` pairs read
    from already-frozen batches (codes have left the database as printer
    plaintext). Once frozen, a format's spec is contractually unchangeable;
    call this at startup so an accidental edit to a registered
    ``CodeFormat`` is caught before the app serves a single request,
    instead of silently misjudging printed codes.
    """
    for format_id, expected_fingerprint in frozen:
        actual_fingerprint = get_format(format_id).fingerprint()
        if actual_fingerprint != expected_fingerprint:
            raise FormatRegistryError(
                f"format {format_id!r} has changed since it was frozen "
                f"(expected fingerprint {expected_fingerprint}, "
                f"code now computes {actual_fingerprint}); printed codes "
                "under this format can no longer be trusted"
            )


@dataclass(frozen=True, slots=True)
class ParsedCode:
    """A syntactically valid code whose check character matches."""

    city: CityCode
    canonical: str
    format_id: str = DEFAULT_FORMAT_ID

    @property
    def printed(self) -> str:
        """Human-friendly grouping used on packaging, e.g. ``TO-7KQ2-M9XH-4R6``."""
        return format_printed(self.canonical, get_format(self.format_id))


def _luhn_mod_n_sum(values: list[int], start_factor: int, base: int) -> int:
    factor = start_factor
    total = 0
    for value in reversed(values):
        addend = factor * value
        addend = addend // base + addend % base
        total += addend
        factor = 1 if factor == 2 else 2
    return total


def _values(code_format: CodeFormat, characters: str) -> list[int]:
    return [code_format.alphabet.index(c) for c in characters]


def compute_check_value(
    city: CityCode, body: str, code_format: CodeFormat = V2_B10
) -> int:
    """Return the Luhn mod N check value for ``city`` + ``body``.

    The city index is mixed in as a leading symbol so that a typo in the
    prefix (``MO`` instead of ``TO``) is also caught.
    """
    base = code_format.base
    values = [CITY_CHECK_INDEX[city], *_values(code_format, body)]
    return (base - _luhn_mod_n_sum(values, 2, base) % base) % base


def check_is_valid(
    city: CityCode, body: str, check: str, code_format: CodeFormat = V2_B10
) -> bool:
    """True when ``check`` is the correct check character for the code."""
    values = [CITY_CHECK_INDEX[city], *_values(code_format, body + check)]
    return _luhn_mod_n_sum(values, 1, code_format.base) % code_format.base == 0


def generate_code(city: CityCode, code_format: CodeFormat | None = None) -> str:
    """Return a new canonical code using the OS CSPRNG."""
    fmt = code_format or get_format()
    body = "".join(secrets.choice(fmt.alphabet) for _ in range(fmt.body_length))
    check = fmt.alphabet[compute_check_value(city, body, fmt)]
    return f"{city.value}{body}{check}"


def format_printed(canonical: str, code_format: CodeFormat | None = None) -> str:
    """Group a canonical code for printing, e.g. ``PP-XXXX-XXXX-XXX``."""
    fmt = code_format or get_format()
    parts = [canonical[:PREFIX_LENGTH]]
    position = PREFIX_LENGTH
    for size in fmt.grouping:
        parts.append(canonical[position : position + size])
        position += size
    return "-".join(parts)


def _strip_separators(text: str) -> str:
    kept: list[str] = []
    for character in text:
        category = unicodedata.category(character)
        # Zs: spaces incl. NBSP; Pd: every dash; Cf: ZWNJ, ZWJ, BOM, bidi marks.
        if category in {"Zs", "Pd", "Cf"} or character in "\t\r\n_.":
            continue
        kept.append(character)
    return "".join(kept)


def normalize_input(raw: str) -> str:
    """Fold whatever a person typed or scanned into canonical characters.

    The result is not guaranteed to be valid; use :func:`parse_code`.
    """
    text = unicodedata.normalize("NFKC", raw).translate(_DIGIT_TRANSLATION)
    return _strip_separators(text).upper()


def _strip_qr_wrapper(raw: str) -> str:
    """Drop a scanned QR's URL, keeping only the code it carries.

    The printed QR puts the code in the path,
    ``https://torshx.com/b/TO-ABC-DEF-GHJ``: the text after the last ``/``.
    The fragment form (``https://torshx.com/r#TO-ABC-DEF-GHJ``) is still
    accepted: the text after ``#``. A bare typed code (no ``#`` or ``://``)
    passes through unchanged.
    """
    text = raw.strip()
    if "#" in text:
        return text.rsplit("#", 1)[1]
    if "://" in text:
        return text.rsplit("/", 1)[1]
    return text


def parse_code(raw: str) -> ParsedCode:
    """Parse user input into a :class:`ParsedCode` or raise ``CodeFormatError``.

    The format is picked by length (registered lengths are unique).
    ``MALFORMED`` means the input cannot be a code at all (wrong length,
    unknown city, characters outside the alphabet). ``MISTYPED`` means the
    shape is right but the check character does not match, which almost
    always means one character was misread from the packaging.
    """
    text = normalize_input(_strip_qr_wrapper(raw))
    fmt = next((f for f in FORMATS.values() if f.canonical_length == len(text)), None)
    if fmt is None or not text.isascii():
        raise CodeFormatError(CodeProblem.MALFORMED)

    # "0" in the prefix is a typo for "O" (TO, MO); prefixes are letters only.
    prefix = text[:PREFIX_LENGTH].replace("0", "O")
    city = _CITY_BY_PREFIX.get(prefix)
    if city is None:
        raise CodeFormatError(CodeProblem.MALFORMED)

    tail = "".join(fmt.aliases.get(c, c) for c in text[PREFIX_LENGTH:])
    if any(c not in fmt.alphabet for c in tail):
        raise CodeFormatError(CodeProblem.MALFORMED)

    body, check = tail[: fmt.body_length], tail[fmt.body_length :]
    if not check_is_valid(city, body, check, fmt):
        raise CodeFormatError(CodeProblem.MISTYPED)
    return ParsedCode(
        city=city, canonical=f"{prefix}{body}{check}", format_id=fmt.format_id
    )
