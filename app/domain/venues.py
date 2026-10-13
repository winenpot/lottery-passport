from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Venue:
    """A partner lounge. ``id`` is a short stable slug (``parsa``), never a UUID."""

    id: str
    name: str
    city: str
    public_ip: str | None = None
    active: bool = True
