"""The demo smoke script's helpers (the script itself runs against a live API)."""

import random

from app.application.otp_test_numbers import is_test_phone_number
from app.domain.phone import normalize_iranian_mobile
from scripts.smoke_demo import Reply, first_header_values, random_test_phone


def test_random_test_numbers_are_valid_and_inside_the_test_prefix() -> None:
    rng = random.Random(7)

    numbers = {random_test_phone(rng) for _ in range(50)}

    assert len(numbers) > 40
    for number in numbers:
        assert is_test_phone_number(normalize_iranian_mobile(number))


def test_reply_reads_the_error_code_from_the_envelope() -> None:
    reply = Reply(404, {}, '{"error": {"code": "NOT_FOUND", "message": "x"}}', 0.1)

    assert reply.error_code() == "NOT_FOUND"
    assert Reply(500, {}, "<html>", 0.1).error_code() is None


def test_a_repeated_header_keeps_the_first_value() -> None:
    # The shape mirrors ArvanCloud appending its own X-Request-Id after
    # ours: httpx/urllib's response.headers yields BOTH occurrences, in
    # the order they appeared on the wire.
    headers = [("X-Request-Id", "origin-id"), ("x-request-id", "arvan-id")]

    assert first_header_values(headers) == {"x-request-id": "origin-id"}


def test_an_unrepeated_header_is_unaffected() -> None:
    headers = [("Content-Type", "application/json")]

    assert first_header_values(headers) == {"content-type": "application/json"}
