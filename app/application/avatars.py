from typing import Protocol

from app.domain.avatars import Avatar


class AvatarCatalogue(Protocol):
    async def list_active(self) -> list[Avatar]:
        """Active avatars ordered for display (catalogue ``sort``, then id)."""
        ...

    async def get_active(self, avatar_id: str) -> Avatar | None:
        """An active avatar by id, or ``None`` if unknown/inactive."""
        ...


class AvatarService:
    """Read side of the avatar catalogue (``GET /avatars``)."""

    def __init__(self, catalogue: AvatarCatalogue) -> None:
        self._catalogue = catalogue

    async def list(self) -> list[Avatar]:
        return await self._catalogue.list_active()
