from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class City:
    """A city the campaign runs in. ``id`` is a lowercase slug, ``name`` Persian."""

    id: str
    name: str


# The cities the campaign supports. A venue's ``city`` must be one of these ids.
# Adding a city is a code change on purpose: the frontend shows this list.
SUPPORTED_CITIES: tuple[City, ...] = (
    City("tehran", "تهران"),
    City("ahvaz", "اهواز"),
    City("mashhad", "مشهد"),
    City("isfahan", "اصفهان"),
)
SUPPORTED_CITY_IDS = frozenset(city.id for city in SUPPORTED_CITIES)


@dataclass(frozen=True, slots=True)
class Venue:
    """A partner lounge. ``id`` is a short stable slug (``parsa``), never a UUID."""

    id: str
    name: str
    city: str
    public_ip: str | None = None
    active: bool = True
    address: str | None = None
