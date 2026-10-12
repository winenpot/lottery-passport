from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.authentication import AuthenticationError, Clock
from app.domain.nickname import Nickname, parse_nickname
from app.domain.users import User


class NicknameTaken(Exception):
    """Another account already uses this nickname (after folding)."""


class TermsVersionMismatch(Exception):
    """The client accepted a terms version that is not the current one."""


class ProfileStore(Protocol):
    async def update_profile(
        self,
        user_id: UUID,
        now: datetime,
        *,
        nickname: Nickname | None,
        terms_version: str | None,
    ) -> User | None:
        """Apply the given fields in one statement; ``None`` for no such user.

        Raises ``NicknameTaken`` when the nickname key is already used.
        """
        ...


class ProfileService:
    def __init__(
        self, store: ProfileStore, clock: Clock, current_terms_version: str
    ) -> None:
        self._store = store
        self._clock = clock
        self._terms_version = current_terms_version

    async def update(
        self,
        user_id: UUID,
        *,
        nickname: str | None,
        accept_terms_version: str | None,
    ) -> User:
        """Raises ``NicknameError``, ``NicknameTaken`` or ``TermsVersionMismatch``."""
        parsed = parse_nickname(nickname) if nickname is not None else None
        if (
            accept_terms_version is not None
            and accept_terms_version != self._terms_version
        ):
            raise TermsVersionMismatch(accept_terms_version)
        user = await self._store.update_profile(
            user_id,
            self._clock.now(),
            nickname=parsed,
            terms_version=accept_terms_version,
        )
        if user is None:
            raise AuthenticationError("authentication required")
        return user
