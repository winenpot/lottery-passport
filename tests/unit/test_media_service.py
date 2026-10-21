"""``MediaService`` against a fake ``MediaAssets`` port: hashing, content-
addressed dedup, and that domain refusals (app/domain/media.py) propagate
unchanged -- the real sniffing/size-limit logic is tested there, not
duplicated here.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.media import MediaService
from app.domain.media import (
    MediaAsset,
    MediaError,
    MediaRefusal,
    NewMediaAsset,
    StoredMedia,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
NOW = datetime(2026, 10, 21, tzinfo=UTC)


class FakeMediaAssets:
    def __init__(self) -> None:
        self.stored: dict[str, MediaAsset] = {}
        self.put_calls: list[NewMediaAsset] = []

    async def put_if_absent(self, asset: NewMediaAsset) -> MediaAsset:
        self.put_calls.append(asset)
        existing = self.stored.get(asset.sha256)
        if existing is not None:
            return existing
        created = MediaAsset(
            sha256=asset.sha256,
            content_type=asset.content_type,
            byte_size=len(asset.data),
            created_at=NOW,
            created_by_user_id=asset.created_by_user_id,
        )
        self.stored[asset.sha256] = created
        return created

    async def get(self, sha256: str) -> StoredMedia | None:
        asset = self.stored.get(sha256)
        if asset is None:
            return None
        return StoredMedia(content_type=asset.content_type, data=PNG_BYTES)


async def test_upload_stores_the_sniffed_type_and_sha256_of_the_bytes() -> None:
    assets = FakeMediaAssets()
    service = MediaService(assets)

    asset = await service.upload(PNG_BYTES, created_by_user_id=None)

    assert asset.sha256 == assets.put_calls[0].sha256
    assert len(asset.sha256) == 64
    assert asset.byte_size == len(PNG_BYTES)


async def test_uploading_the_same_bytes_twice_is_a_no_op_second_time() -> None:
    """Content-addressed: no duplicate row, no audit noise for a re-upload."""
    assets = FakeMediaAssets()
    service = MediaService(assets)
    actor = uuid4()

    first = await service.upload(PNG_BYTES, created_by_user_id=actor)
    second = await service.upload(PNG_BYTES, created_by_user_id=actor)

    assert first == second
    assert len(assets.stored) == 1
    assert len(assets.put_calls) == 2  # both calls reach the port; dedup is its job


async def test_a_refused_upload_never_reaches_the_port() -> None:
    assets = FakeMediaAssets()
    service = MediaService(assets)

    with pytest.raises(MediaError) as caught:
        await service.upload(b"not an image", created_by_user_id=None)

    assert caught.value.reason is MediaRefusal.UNSUPPORTED_TYPE
    assert assets.put_calls == []


async def test_get_returns_none_for_an_unknown_hash() -> None:
    service = MediaService(FakeMediaAssets())

    assert await service.get("0" * 64) is None


async def test_get_returns_the_stored_bytes_and_type() -> None:
    assets = FakeMediaAssets()
    service = MediaService(assets)
    asset = await service.upload(PNG_BYTES, created_by_user_id=None)

    stored = await service.get(asset.sha256)

    assert stored is not None
    assert stored.content_type == asset.content_type
    assert stored.data == PNG_BYTES
