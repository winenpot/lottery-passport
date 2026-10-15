"""Flavor team membership: ``GET/POST /me/team`` (P1.5).

``change`` locks the player's wallet row first, the same per-user
serialization ``RedemptionService`` uses, so two concurrent team-change
requests from one player cannot both succeed (app/domain/teams.py has the
actual join/switch/lock rule).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.application.authentication import Clock
from app.application.unit_of_work import UnitOfWorkFactory
from app.domain.passports import CityCode
from app.domain.teams import (
    TEAM_LOCK,
    TeamMembership,
    change_team,
    is_unlocked,
)


class TeamsReader(Protocol):
    """Plain read side (no wallet lock): implemented by
    ``PostgreSQLTeamsReader``, shares its queries with the unit of work's
    ``teams`` port."""

    async def current(self, user_id: UUID) -> TeamMembership | None: ...

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int: ...


@dataclass(frozen=True, slots=True)
class FlavorProgress:
    flavor: CityCode
    codes: int
    unlocked: bool


@dataclass(frozen=True, slots=True)
class TeamStatus:
    team: TeamMembership | None
    switch_allowed_at: datetime | None
    flavors: list[FlavorProgress]


class TeamService:
    def __init__(
        self,
        reader: TeamsReader,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        lock: timedelta = TEAM_LOCK,
    ) -> None:
        self._reader = reader
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._lock = lock

    async def status(self, user_id: UUID) -> TeamStatus:
        current = await self._reader.current(user_id)
        flavors = []
        for flavor in CityCode:
            codes = await self._reader.count_codes(user_id, flavor)
            flavors.append(
                FlavorProgress(flavor=flavor, codes=codes, unlocked=is_unlocked(codes))
            )
        return TeamStatus(
            team=current,
            switch_allowed_at=(
                current.switch_allowed_at(self._lock) if current is not None else None
            ),
            flavors=flavors,
        )

    async def change(self, user_id: UUID, flavor: CityCode) -> TeamMembership:
        """Raises ``TeamChangeError``."""
        now = self._clock.now()
        async with self._unit_of_work() as uow:
            await uow.ledger.lock_wallet(user_id, now)  # per-user serialization
            current = await uow.teams.current(user_id)
            target_codes = await uow.teams.count_codes(user_id, flavor)
            membership = change_team(
                user_id, current, flavor, target_codes, now, self._lock
            )
            await uow.teams.add(membership)
            await uow.commit()
        return membership
