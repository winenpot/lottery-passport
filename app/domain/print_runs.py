"""Weighted print runs drawn from a fixed per-flavor code pool.

The campaign's pool is 1,000,000 codes split evenly over the seven flavors
(:data:`QUOTA_PER_SKU` each). A print run asks for ``k`` codes with one
weight per flavor (weights add up to exactly 1); flavor ``i`` gets
``n_i ~= w_i * k`` codes. A run happens only if every flavor still has
``n_i`` codes left in its quota (all or nothing), so runs can repeat until a
flavor is used up.

The pool is a quota, not stored codes: drawing ``n_i`` codes from a pile of
random codes is the same as generating ``n_i`` fresh random codes, and this
way no plaintext pool ever has to be kept to sample from later.

Weights are exact fractions (``"0.3"`` or ``"1/7"``), so "adds up to 1" is an
exact test, not a float tolerance. Everything here is pure.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from app.domain.codes import CITY_CHECK_INDEX
from app.domain.passports import Campaign, CityCode

POOL_SIZE = 1_000_000
# 7 x 142,857 = 999,999: the pool does not divide evenly; one code is dropped.
QUOTA_PER_SKU = POOL_SIZE // len(CityCode)

# Fixed order for output and for breaking rounding ties: the frozen city index.
SKU_ORDER: tuple[CityCode, ...] = tuple(
    sorted(CityCode, key=lambda city: CITY_CHECK_INDEX[city])
)


class PrintRunError(ValueError):
    """The requested run is not valid (bad weights, bad k, quota exceeded)."""


@dataclass(frozen=True, slots=True)
class Shortage:
    city: CityCode
    wanted: int
    remaining: int


class QuotaExceededError(PrintRunError):
    """At least one flavor does not have enough codes left for this run."""

    def __init__(self, shortages: list[Shortage]) -> None:
        details = ", ".join(
            f"{s.city.value} wants {s.wanted} but has {s.remaining} left"
            for s in shortages
        )
        super().__init__(f"run refused, quota exceeded: {details}")
        self.shortages = tuple(shortages)


def parse_sku(name: str) -> CityCode:
    """Accept the prefix (``TO``) or the campaign name (``tokyo``)."""
    text = name.strip()
    try:
        return CityCode(text.upper())
    except ValueError:
        pass
    try:
        return CityCode[Campaign(text.lower()).name]
    except ValueError:
        raise PrintRunError(f"unknown flavor {name!r}") from None


def parse_weights(text: str) -> dict[CityCode, Fraction]:
    """Parse ``"TO=0.3,PR=1/5,..."``; missing flavors weigh 0; sum must be 1."""
    weights: dict[CityCode, Fraction] = {}
    for item in text.split(","):
        if not item.strip():
            continue
        name, separator, value = item.partition("=")
        if not separator:
            raise PrintRunError(f"expected FLAVOR=WEIGHT, got {item.strip()!r}")
        city = parse_sku(name)
        if city in weights:
            raise PrintRunError(f"{city.value} is given twice")
        try:
            weight = Fraction(value.strip())
        except (ValueError, ZeroDivisionError):
            raise PrintRunError(
                f"bad weight {value.strip()!r} for {city.value}"
            ) from None
        weights[city] = weight
    validate_weights(weights)
    return {city: weights.get(city, Fraction(0)) for city in SKU_ORDER}


def equal_weights() -> dict[CityCode, Fraction]:
    return {city: Fraction(1, len(SKU_ORDER)) for city in SKU_ORDER}


def validate_weights(weights: Mapping[CityCode, Fraction]) -> None:
    if any(weight < 0 for weight in weights.values()):
        raise PrintRunError("weights must not be negative")
    total = sum(weights.values(), Fraction(0))
    if total != 1:
        raise PrintRunError(f"weights must add up to exactly 1, they add up to {total}")


def allocate(k: int, weights: Mapping[CityCode, Fraction]) -> dict[CityCode, int]:
    """Split ``k`` codes by weight; the counts add up to exactly ``k``.

    Largest remainder: every flavor gets ``floor(w_i * k)``, and the codes
    left over go one each to the flavors with the largest fractional part
    (ties in :data:`SKU_ORDER`). So ``|n_i - w_i * k| < 1`` and a flavor
    with weight 0 always gets 0.
    """
    if k < 1:
        raise PrintRunError("k must be at least 1")
    validate_weights(weights)
    exact = {city: weights.get(city, Fraction(0)) * k for city in SKU_ORDER}
    counts = {city: int(share) for city, share in exact.items()}  # floor, share >= 0
    leftover = k - sum(counts.values())
    by_remainder = sorted(
        SKU_ORDER, key=lambda city: exact[city] - counts[city], reverse=True
    )
    for city in by_remainder[:leftover]:
        counts[city] += 1
    return counts


def remaining_quota(
    issued: Mapping[CityCode, int], quota_per_sku: int = QUOTA_PER_SKU
) -> dict[CityCode, int]:
    """Codes left per flavor, given how many were already issued (any status)."""
    return {city: quota_per_sku - issued.get(city, 0) for city in SKU_ORDER}


def check_quota(
    allocation: Mapping[CityCode, int], remaining: Mapping[CityCode, int]
) -> None:
    """Refuse the whole run if any flavor wants more than it has left.

    Taking a flavor's last code is allowed (``n_i == remaining_i``). A flavor
    this run takes nothing from never blocks it, even if it is already over
    its quota.
    """
    shortages = [
        Shortage(city, allocation[city], remaining.get(city, 0))
        for city in SKU_ORDER
        if allocation.get(city, 0) > max(remaining.get(city, 0), 0)
    ]
    if shortages:
        raise QuotaExceededError(shortages)


def plan_run(
    k: int,
    weights: Mapping[CityCode, Fraction],
    issued: Mapping[CityCode, int],
    quota_per_sku: int = QUOTA_PER_SKU,
) -> dict[CityCode, int]:
    """Allocation for a run, or :class:`QuotaExceededError` if it cannot happen."""
    allocation = allocate(k, weights)
    check_quota(allocation, remaining_quota(issued, quota_per_sku))
    return allocation
