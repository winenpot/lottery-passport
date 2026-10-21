"""Admin image upload (W10): ``MediaAssets`` port, two callers -- the
admin "Images" page (write, via ``MediaService.upload``) and
``GET /media/{sha256}.{ext}`` (read, via ``MediaService.get``) -- shared
storage is why this earns a port rather than a one-off query each.
"""

import hashlib
from typing import Protocol
from uuid import UUID

from app.domain.media import MediaAsset, NewMediaAsset, StoredMedia, validate_upload


class MediaAssets(Protocol):
    """Implemented by ``PostgreSQLMediaAssets``."""

    async def put_if_absent(self, asset: NewMediaAsset) -> MediaAsset:
        """Content-addressed: if this exact sha256 already exists, returns
        the existing row unchanged -- no duplicate upload, no audit noise
        for re-uploading the same file."""
        ...

    async def get(self, sha256: str) -> StoredMedia | None: ...


class MediaService:
    def __init__(self, assets: MediaAssets) -> None:
        self._assets = assets

    async def upload(self, data: bytes, created_by_user_id: UUID | None) -> MediaAsset:
        """Raises ``MediaError`` (app/domain/media.py) for anything that is
        not a real PNG/JPEG/WebP under the size ceiling."""
        content_type = validate_upload(data)
        sha256 = hashlib.sha256(data).hexdigest()
        return await self._assets.put_if_absent(
            NewMediaAsset(
                sha256=sha256,
                content_type=content_type,
                data=data,
                created_by_user_id=created_by_user_id,
            )
        )

    async def get(self, sha256: str) -> StoredMedia | None:
        return await self._assets.get(sha256)
