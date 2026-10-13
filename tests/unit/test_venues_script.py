"""The venues script only accepts supported cities and valid ids."""

import argparse

import pytest

from app.domain.venues import SUPPORTED_CITIES
from scripts.venues import _city, _venue_id


def test_the_supported_cities_are_the_four_campaign_cities() -> None:
    assert [c.id for c in SUPPORTED_CITIES] == [
        "tehran",
        "ahvaz",
        "mashhad",
        "isfahan",
    ]
    assert [c.name for c in SUPPORTED_CITIES] == ["تهران", "اهواز", "مشهد", "اصفهان"]


@pytest.mark.parametrize("city", ["tehran", "ahvaz", "mashhad", "isfahan"])
def test_supported_cities_are_accepted(city: str) -> None:
    assert _city(city) == city


@pytest.mark.parametrize("city", ["Tehran", "shiraz", "", "تهران"])
def test_other_cities_are_refused(city: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _city(city)


def test_venue_ids_are_short_lowercase_slugs() -> None:
    assert _venue_id("ahvaz-golestan") == "ahvaz-golestan"
    for bad in ("A", "Upper", "has space", "-lead"):
        with pytest.raises(argparse.ArgumentTypeError):
            _venue_id(bad)
