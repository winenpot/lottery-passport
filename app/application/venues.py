from typing import Protocol

from app.domain.venues import Venue


class VenueCatalogue(Protocol):
    async def list_active(self) -> list[Venue]:
        """Active venues ordered by name."""
        ...

    async def exists_active(self, venue_id: str) -> bool: ...
