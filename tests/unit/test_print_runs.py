"""Weighted print-run allocation and the per-flavor quota guard."""

import random
from fractions import Fraction

import pytest

from app.domain.passports import CityCode
from app.domain.print_runs import (
    QUOTA_PER_SKU,
    SKU_ORDER,
    PrintRunError,
    QuotaExceededError,
    allocate,
    check_quota,
    equal_weights,
    parse_weights,
    plan_run,
    remaining_quota,
)


def test_the_pool_is_split_evenly_and_drops_the_remainder() -> None:
    assert QUOTA_PER_SKU == 142_857
    assert QUOTA_PER_SKU * len(SKU_ORDER) == 999_999


def test_weights_accept_prefixes_names_decimals_and_fractions() -> None:
    weights = parse_weights("TO=0.5, paris=1/4, be=0.25")

    assert weights[CityCode.TOKYO] == Fraction(1, 2)
    assert weights[CityCode.PARIS] == Fraction(1, 4)
    assert weights[CityCode.BERLIN] == Fraction(1, 4)
    assert weights[CityCode.MOSCOW] == 0
    assert list(weights) == list(SKU_ORDER)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("TO=0.5,PR=0.4", "add up to exactly 1"),
        ("TO=0.142857,PR=0.857142", "add up to exactly 1"),
        ("TO=1.5,PR=-0.5", "negative"),
        ("TO=1,TO=0", "twice"),
        ("XX=1", "unknown flavor"),
        ("TO", "FLAVOR=WEIGHT"),
        ("TO=abc", "bad weight"),
        ("TO=1/0", "bad weight"),
    ],
)
def test_bad_weights_are_refused_with_a_reason(text: str, message: str) -> None:
    with pytest.raises(PrintRunError, match=message):
        parse_weights(text)


def test_equal_weights_split_7000_into_1000_each() -> None:
    assert allocate(7000, equal_weights()) == dict.fromkeys(SKU_ORDER, 1000)


def test_leftovers_go_to_the_largest_fractional_parts() -> None:
    weights = parse_weights("TO=0.45,PR=0.35,BE=0.2")

    # 10 x weights = 4.5, 3.5, 2.0 -> floors 4, 3, 2, one left over. TO and
    # PR tie at .5; ties go in SKU_ORDER, where PR (index 1) precedes TO (6).
    counts = allocate(10, weights)
    expected = dict.fromkeys(SKU_ORDER, 0)
    expected.update({CityCode.PARIS: 4, CityCode.TOKYO: 4, CityCode.BERLIN: 2})
    assert counts == expected

    # 11 x weights = 4.95, 3.85, 2.2 -> floors 4, 3, 2, two left: TO and PR.
    counts = allocate(11, weights)
    assert (counts[CityCode.TOKYO], counts[CityCode.PARIS]) == (5, 4)
    assert counts[CityCode.BERLIN] == 2


def test_allocation_always_sums_to_k_and_stays_within_one_of_the_exact_share() -> None:
    rng = random.Random(20261021)
    for _ in range(500):
        raw = [rng.randint(0, 50) for _ in SKU_ORDER]
        if not any(raw):
            continue
        weights = {
            city: Fraction(value, sum(raw))
            for city, value in zip(SKU_ORDER, raw, strict=True)
        }
        k = rng.randint(1, 200_000)

        counts = allocate(k, weights)

        assert sum(counts.values()) == k
        for city in SKU_ORDER:
            assert abs(counts[city] - weights[city] * k) < 1
            if weights[city] == 0:
                assert counts[city] == 0


def test_k_must_be_positive() -> None:
    with pytest.raises(PrintRunError, match="at least 1"):
        allocate(0, equal_weights())


def test_remaining_quota_subtracts_what_was_already_issued() -> None:
    remaining = remaining_quota({CityCode.TOKYO: 100}, quota_per_sku=1000)

    assert remaining[CityCode.TOKYO] == 900
    assert remaining[CityCode.PARIS] == 1000


def test_taking_the_last_code_of_a_flavor_is_allowed() -> None:
    check_quota({CityCode.TOKYO: 5}, {CityCode.TOKYO: 5})


def test_a_flavor_the_run_does_not_touch_never_blocks_it() -> None:
    allocation = dict.fromkeys(SKU_ORDER, 0) | {CityCode.TOKYO: 5}
    remaining = dict.fromkeys(SKU_ORDER, 10) | {CityCode.PARIS: -3, CityCode.BERLIN: 0}

    check_quota(allocation, remaining)


def test_the_whole_run_is_refused_naming_every_short_flavor() -> None:
    weights = parse_weights("TO=0.5,PR=0.3,BE=0.2")
    issued = {CityCode.TOKYO: 990, CityCode.PARIS: 995}

    with pytest.raises(QuotaExceededError) as caught:
        plan_run(20, weights, issued, quota_per_sku=1000)  # wants 10, 6, 4

    shortages = {(s.city, s.wanted, s.remaining) for s in caught.value.shortages}
    assert shortages == {(CityCode.PARIS, 6, 5)}
    assert "PR wants 6 but has 5 left" in str(caught.value)


def test_repeated_runs_succeed_until_a_flavor_would_run_out() -> None:
    weights = parse_weights("TO=1/2,PR=1/2")
    issued = dict.fromkeys(SKU_ORDER, 0)
    runs = 0
    while True:
        try:
            allocation = plan_run(30, weights, issued, quota_per_sku=100)
        except QuotaExceededError:
            break
        for city, count in allocation.items():
            issued[city] += count
        runs += 1

    assert runs == 6  # 6 x 15 = 90; a 7th run would need 105 of 100
    assert issued[CityCode.TOKYO] == 90
    assert issued[CityCode.MOSCOW] == 0
