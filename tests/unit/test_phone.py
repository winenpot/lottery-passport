from app.domain.phone import has_known_mobile_prefix, normalize_iranian_mobile


def test_a_known_prefix_passes() -> None:
    assert has_known_mobile_prefix(normalize_iranian_mobile("0912 345 6789"))


def test_an_unallocated_prefix_is_flagged_unusual() -> None:
    # 940 is shape-valid (9 followed by 9 digits) but not a known range.
    assert not has_known_mobile_prefix(normalize_iranian_mobile("0940 123 4567"))


def test_the_test_number_range_is_not_a_known_carrier_prefix() -> None:
    # Deliberately unassigned (app/application/otp_test_numbers.py): callers
    # must check is_test_phone_number BEFORE treating this as "unusual".
    assert not has_known_mobile_prefix(normalize_iranian_mobile("0969 123 4567"))
