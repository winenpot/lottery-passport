"""Admin image upload (W10): sniff a real image type from magic bytes,
enforce a size ceiling, derive a content-addressed name. First caller:
the admin "Images" page; reusable later for badges and prize art
(app/domain/achievements.py's "no badge/image field yet" note).

SVG is refused on purpose: an SVG can carry a ``<script>`` tag, so "image
upload" would otherwise be a stored-XSS vector for anyone with /admin
write access. PNG/JPEG/WebP are checked by their own magic bytes, never
by the filename or the client-sent Content-Type header -- both are
trivially spoofable.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

MAX_BYTES = 512 * 1024


class MediaContentType(StrEnum):
    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"


_EXTENSION_BY_TYPE: dict[MediaContentType, str] = {
    MediaContentType.PNG: "png",
    MediaContentType.JPEG: "jpg",
    MediaContentType.WEBP: "webp",
}


class MediaRefusal(StrEnum):
    EMPTY = "empty"
    TOO_LARGE = "too_large"
    UNSUPPORTED_TYPE = "unsupported_type"


class MediaError(Exception):
    def __init__(self, reason: MediaRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


def sniff_content_type(data: bytes) -> MediaContentType:
    """Raises ``MediaError(UNSUPPORTED_TYPE)`` for anything that is not a
    real PNG, JPEG or WebP by its own magic bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaContentType.PNG
    if data.startswith(b"\xff\xd8\xff"):
        return MediaContentType.JPEG
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return MediaContentType.WEBP
    raise MediaError(MediaRefusal.UNSUPPORTED_TYPE)


def extension_for(content_type: MediaContentType) -> str:
    return _EXTENSION_BY_TYPE[content_type]


def validate_upload(data: bytes) -> MediaContentType:
    """Raises ``MediaError`` (EMPTY, TOO_LARGE or UNSUPPORTED_TYPE)."""
    if not data:
        raise MediaError(MediaRefusal.EMPTY)
    if len(data) > MAX_BYTES:
        raise MediaError(MediaRefusal.TOO_LARGE)
    return sniff_content_type(data)


@dataclass(frozen=True, slots=True)
class NewMediaAsset:
    sha256: str
    content_type: MediaContentType
    data: bytes
    created_by_user_id: UUID | None


@dataclass(frozen=True, slots=True)
class MediaAsset:
    sha256: str
    content_type: MediaContentType
    byte_size: int
    created_at: datetime
    created_by_user_id: UUID | None


@dataclass(frozen=True, slots=True)
class StoredMedia:
    """``MediaAsset`` plus its bytes -- only ``GET /media/...`` needs the
    bytes; the Images page and the audit row only need the summary."""

    content_type: MediaContentType
    data: bytes
