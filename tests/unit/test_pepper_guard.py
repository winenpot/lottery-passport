"""Pure pepper-guard logic: fingerprint, mismatch detection, PepperGuard.

Integration coverage (real batches, real startup crash, real /ready 503) is
in tests/integration/test_code_batch_lifecycle.py.
"""

from uuid import UUID, uuid4

from app.application.redemption_codes import (
    PepperGuard,
    PepperMismatch,
    PepperMismatchError,
    find_pepper_mismatches,
    pepper_fingerprint,
    verify_active_batch_peppers,
)
from app.domain.passports import CityCode


class FakeActiveBatchPeppers:
    def __init__(self, rows: list[tuple[UUID, str, str | None]]) -> None:
        self._rows = rows

    async def active_batch_peppers(self) -> list[tuple[UUID, str, str | None]]:
        return self._rows


def test_fingerprint_is_deterministic_for_the_same_pepper() -> None:
    assert pepper_fingerprint("pepper-a") == pepper_fingerprint("pepper-a")


def test_fingerprint_differs_for_different_peppers() -> None:
    assert pepper_fingerprint("pepper-a") != pepper_fingerprint("pepper-b")


def test_fingerprint_is_not_the_hash_of_a_real_code() -> None:
    # Domain separation in practice: a real code's hash under the same
    # pepper must never equal that pepper's fingerprint, or a stored
    # fingerprint could be mistaken for (or misused as) a code hash.
    from app.application.redemption_codes import hash_redemption_code
    from app.domain.codes import generate_code

    pepper = "pepper-a"
    code = generate_code(CityCode.TOKYO)

    assert pepper_fingerprint(pepper) != hash_redemption_code(code, pepper)


def test_no_mismatch_when_every_fingerprint_matches() -> None:
    expected = pepper_fingerprint("current-pepper")
    rows = [(uuid4(), CityCode.TOKYO.value, expected)]

    assert find_pepper_mismatches(rows, expected) == []


def test_no_mismatch_for_a_legacy_batch_with_no_fingerprint() -> None:
    expected = pepper_fingerprint("current-pepper")
    rows: list[tuple[UUID, str, str | None]] = [(uuid4(), CityCode.TOKYO.value, None)]

    assert find_pepper_mismatches(rows, expected) == []


def test_flags_a_batch_generated_under_a_different_pepper() -> None:
    expected = pepper_fingerprint("current-pepper")
    stale_batch_id = uuid4()
    rows = [(stale_batch_id, CityCode.PARIS.value, pepper_fingerprint("old-pepper"))]

    mismatches = find_pepper_mismatches(rows, expected)

    assert mismatches == [PepperMismatch(stale_batch_id, CityCode.PARIS.value)]


def test_flags_only_the_mismatched_batches_among_several() -> None:
    expected = pepper_fingerprint("current-pepper")
    ok_batch, stale_batch, legacy_batch = uuid4(), uuid4(), uuid4()
    rows: list[tuple[UUID, str, str | None]] = [
        (ok_batch, CityCode.TOKYO.value, expected),
        (stale_batch, CityCode.PARIS.value, pepper_fingerprint("old-pepper")),
        (legacy_batch, CityCode.BERLIN.value, None),
    ]

    mismatches = find_pepper_mismatches(rows, expected)

    assert [m.batch_id for m in mismatches] == [stale_batch]


def test_verify_raises_naming_every_mismatched_batch() -> None:
    expected = pepper_fingerprint("current-pepper")
    batch_id = uuid4()
    rows = [(batch_id, CityCode.MADRID.value, pepper_fingerprint("old-pepper"))]

    try:
        verify_active_batch_peppers(rows, expected)
    except PepperMismatchError as error:
        assert str(batch_id) in str(error)
        assert CityCode.MADRID.value in str(error)
    else:
        raise AssertionError("expected PepperMismatchError")


def test_verify_accepts_an_empty_list() -> None:
    verify_active_batch_peppers([], pepper_fingerprint("current-pepper"))


async def test_pepper_guard_passes_when_nothing_mismatches() -> None:
    expected = pepper_fingerprint("current-pepper")
    dependency = FakeActiveBatchPeppers([(uuid4(), CityCode.TOKYO.value, expected)])

    guard = PepperGuard(dependency, expected)

    assert await guard.check() is True


async def test_pepper_guard_fails_on_a_mismatch() -> None:
    expected = pepper_fingerprint("current-pepper")
    dependency = FakeActiveBatchPeppers(
        [(uuid4(), CityCode.PARIS.value, pepper_fingerprint("old-pepper"))]
    )

    guard = PepperGuard(dependency, expected)

    assert await guard.check() is False


async def test_pepper_guard_passes_when_no_pepper_is_configured() -> None:
    # development: nothing to check against, so never block readiness on it.
    dependency = FakeActiveBatchPeppers(
        [(uuid4(), CityCode.PARIS.value, pepper_fingerprint("whatever"))]
    )

    guard = PepperGuard(dependency, None)

    assert await guard.check() is True
