"""Pure helpers of the batch generator (scripts/generate_codes.py)."""

import itertools

import pytest

from app.domain.codes import CITY2_B9, V2_B10, format_printed, parse_code
from app.domain.passports import CityCode
from scripts.generate_codes import build_unique_codes, city_from_name, qr_url


def test_build_unique_codes_returns_the_requested_number_of_valid_codes() -> None:
    codes = build_unique_codes(CityCode.MOSCOW, 2_000)

    assert len(codes) == len(set(codes)) == 2_000
    assert all(parse_code(code).city is CityCode.MOSCOW for code in codes)


def test_build_unique_codes_survives_a_generator_that_repeats_itself() -> None:
    repeating = itertools.cycle(["TO0000000000A", "TO0000000000A", "TO1111111111B"])

    codes = build_unique_codes(CityCode.TOKYO, 2, lambda _: next(repeating))

    assert codes == ["TO0000000000A", "TO1111111111B"]


@pytest.mark.parametrize(
    ("name", "city"),
    [("tokyo", CityCode.TOKYO), ("Moscow", CityCode.MOSCOW), ("PR", CityCode.PARIS)],
)
def test_city_from_name_accepts_campaign_names_and_prefixes(
    name: str, city: CityCode
) -> None:
    assert city_from_name(name) is city


def test_city_from_name_rejects_unknown_cities() -> None:
    with pytest.raises(ValueError):
        city_from_name("london")


def test_qr_url_carries_the_printed_code_in_the_b_path() -> None:
    code = "TO7KQ2M9XH4R6"
    assert qr_url("HTTPS://Play.Example.ir/", code, V2_B10) == (
        f"https://play.example.ir/b/{format_printed(code, V2_B10)}"
    )


def test_qr_url_round_trips_through_parse_code() -> None:
    code = "TOHA1NQCC32"
    url = qr_url("https://torshx.com", code, CITY2_B9)
    assert url == "https://torshx.com/b/TO-HA1-NQC-C32"
    assert parse_code(url).canonical == code
