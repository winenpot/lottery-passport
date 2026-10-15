from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.authentication import AuthenticationError, Clock
from app.application.avatars import AvatarCatalogue
from app.application.venues import VenueCatalogue
from app.domain.nickname import Nickname, parse_nickname
from app.domain.users import User
from app.domain.venues import SUPPORTED_CITY_IDS


class NicknameTaken(Exception):
    """Another account already uses this nickname (after folding)."""


class TermsVersionMismatch(Exception):
    """The client accepted a terms version that is not the current one."""


class VenueUnknown(Exception):
    """The picked home lounge does not exist or is no longer active."""


class LocationCityUnknown(Exception):
    """The picked home city is not one of the supported location cities."""


class AvatarUnknown(Exception):
    """The picked avatar does not exist or is inactive."""


class AvatarLocked(Exception):
    """The picked avatar exists but is locked for every player right now."""


class ProfileStore(Protocol):
    async def update_profile(
        self,
        user_id: UUID,
        now: datetime,
        *,
        nickname: Nickname | None,
        terms_version: str | None,
        home_venue_id: str | None = None,
        location_city: str | None = None,
        avatar_id: str | None = None,
    ) -> User | None:
        """Apply the given fields in one statement; ``None`` for no such user.

        Raises ``NicknameTaken`` when the nickname key is already used.
        """
        ...


class ProfileService:
    def __init__(
        self,
        store: ProfileStore,
        clock: Clock,
        current_terms_version: str,
        venues: VenueCatalogue,
        avatars: AvatarCatalogue | None = None,
    ) -> None:
        self._store = store
        self._venues = venues
        self._avatars = avatars
        self._clock = clock
        self._terms_version = current_terms_version

    async def update(
        self,
        user_id: UUID,
        *,
        nickname: str | None,
        accept_terms_version: str | None,
        home_venue_id: str | None = None,
        location_city: str | None = None,
        avatar_id: str | None = None,
    ) -> User:
        """Raises ``NicknameError``, ``NicknameTaken``, ``TermsVersionMismatch``,
        ``VenueUnknown``, ``LocationCityUnknown``, ``AvatarUnknown`` or
        ``AvatarLocked``."""
        parsed = parse_nickname(nickname) if nickname is not None else None
        if (
            accept_terms_version is not None
            and accept_terms_version != self._terms_version
        ):
            raise TermsVersionMismatch(accept_terms_version)
        if home_venue_id is not None and not await self._venues.exists_active(
            home_venue_id
        ):
            raise VenueUnknown(home_venue_id)
        if location_city is not None and location_city not in SUPPORTED_CITY_IDS:
            raise LocationCityUnknown(location_city)
        if avatar_id is not None:
            await self._check_avatar(avatar_id)
        user = await self._store.update_profile(
            user_id,
            self._clock.now(),
            nickname=parsed,
            terms_version=accept_terms_version,
            home_venue_id=home_venue_id,
            location_city=location_city,
            avatar_id=avatar_id,
        )
        if user is None:
            raise AuthenticationError("authentication required")
        return user

    async def _check_avatar(self, avatar_id: str) -> None:
        if self._avatars is None:
            raise AvatarUnknown(avatar_id)
        avatar = await self._avatars.get_active(avatar_id)
        if avatar is None:
            raise AvatarUnknown(avatar_id)
        if avatar.locked:
            raise AvatarLocked(avatar_id)
