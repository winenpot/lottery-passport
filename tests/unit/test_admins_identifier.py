"""scripts.admins accepts a phone number the way an operator types it.

Accounts are stored as ``+989XXXXXXXXX``; before this, ``reset-totp 0912...``
answered "no user" during a lost-phone recovery.
"""

import pytest

from scripts.admins import resolve_identifier


@pytest.mark.parametrize(
    "typed",
    ["09123456789", "0912 345 6789", "+989123456789", "989123456789", "00989123456789"],
)
def test_a_typed_phone_number_resolves_to_the_stored_form(typed: str) -> None:
    assert resolve_identifier(typed) == "+989123456789"


def test_a_test_number_resolves_too() -> None:
    assert resolve_identifier("09690001234") == "+989690001234"


def test_anything_else_is_matched_as_typed() -> None:
    assert resolve_identifier(" admin@example.com ") == "admin@example.com"
