from app.application.redemption_codes import hash_redemption_code
from app.domain.passports import CityCode
from scripts.generate_redemption_codes import CODE_NUMBER_SPACE, generate_codes_for_city


def test_hash_redemption_code_is_deterministic_and_keyed() -> None:
    first = hash_redemption_code("PR0000001", "pepper-a")
    second = hash_redemption_code("PR0000001", "pepper-a")
    different_pepper = hash_redemption_code("PR0000001", "pepper-b")

    assert first == second
    assert first != different_pepper


def test_generate_codes_for_city_produces_unique_well_formed_codes() -> None:
    codes = generate_codes_for_city(CityCode.PARIS, 1_000)

    assert len(codes) == len(set(codes))
    assert all(len(code) == 9 for code in codes)
    assert all(code.startswith("PR") for code in codes)
    assert all(0 <= int(code[2:]) < CODE_NUMBER_SPACE for code in codes)
