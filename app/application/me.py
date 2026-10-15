"""Composes the ``GET/PATCH /me`` response from several read ports (P1.6).

Thin on purpose: no business rule lives here, just gathering ``team`` and
``last_scanned_flavor`` next to the ``User`` the route already has.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.application.teams import TeamsReader
from app.domain.passports import CityCode


class LastScanReader(Protocol):
    async def last_scanned_flavor(self, user_id: UUID) -> CityCode | None:
        """The flavor of the user's most recently redeemed code, or ``None``."""
        ...


@dataclass(frozen=True, slots=True)
class MeExtras:
    team: CityCode | None
    last_scanned_flavor: CityCode | None


class MeService:
    def __init__(self, teams: TeamsReader, last_scans: LastScanReader) -> None:
        self._teams = teams
        self._last_scans = last_scans

    async def extras(self, user_id: UUID) -> MeExtras:
        current = await self._teams.current(user_id)
        last = await self._last_scans.last_scanned_flavor(user_id)
        return MeExtras(
            team=current.flavor if current is not None else None,
            last_scanned_flavor=last,
        )
