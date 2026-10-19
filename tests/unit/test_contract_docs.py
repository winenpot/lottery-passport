"""FX2: printed-code examples in the docs must actually be valid codes.

A stale example (wrong grouping, wrong check character) looks fine to a
human reviewer but fails ``parse_code`` the moment a frontend developer
pastes it in -- which is exactly how F-5 (2026-10-15 plan) was found.
"""

import re
from pathlib import Path

import pytest

from app.domain.codes import CodeFormatError, parse_code

REPO_ROOT = Path(__file__).resolve().parents[2]

# Loose enough to catch both the current (3-3-3) and the older (4-4-3)
# printed groupings; a plain two-letter city prefix followed by dashed
# alphanumeric groups.
_CODE_PATTERN = re.compile(r"\b[A-Z]{2}-[A-Z0-9]{3,4}-[A-Z0-9]{3,4}-[A-Z0-9]{2,3}\b")

# Deliberately-invalid examples that must NOT be "fixed" (they illustrate a
# rejection case). None today; keep the set so a future one has a home.
_DELIBERATE_BAD_EXAMPLES: frozenset[str] = frozenset()

_DOCS_WITH_CODE_EXAMPLES = (
    "docs/API_CONTRACT.md",
    "docs/CODES.md",
)


def _code_examples(text: str) -> set[str]:
    return {
        match
        for match in _CODE_PATTERN.findall(text)
        if match not in _DELIBERATE_BAD_EXAMPLES
    }


@pytest.mark.parametrize("relative_path", _DOCS_WITH_CODE_EXAMPLES)
def test_every_printed_code_example_in_the_docs_is_actually_valid(
    relative_path: str,
) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    examples = _code_examples(text)

    assert examples, f"no code-shaped example found in {relative_path}"
    for example in examples:
        try:
            parse_code(example)
        except CodeFormatError as error:
            pytest.fail(f"{example!r} in {relative_path} does not parse: {error}")


def test_redemption_daily_limit_is_the_documented_error_code() -> None:
    """2026-10-18 doc note said SCAN_DAILY_LIMIT; the code only ever emitted
    REDEMPTION_DAILY_LIMIT. Catch a re-introduced stale name early."""
    contract = (REPO_ROOT / "docs/API_CONTRACT.md").read_text(encoding="utf-8")

    assert "`REDEMPTION_DAILY_LIMIT`" in contract
