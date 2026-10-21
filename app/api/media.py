"""``GET /media/{sha256}.{ext}`` (W10): serves an admin-uploaded image.

Same page-not-API-resource pattern as ``app/api/legal.py``: mounted with
no ``/api/v1`` prefix, since the URL itself is what ``image_url`` on an
avatar/badge/prize-art row actually points at (same-origin, so the PWA's
CSP and avatar policy need no change).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response

from app.api.deps import get_media_service
from app.application.media import MediaService
from app.domain.media import extension_for

router = APIRouter(tags=["media"])


@router.get(
    "/media/{sha256}.{extension}",
    summary="A previously uploaded image",
    description=(
        "No sign-in needed. Immutable (content-addressed by sha256): cached "
        "forever at the edge, so Postgres serves each image about once per "
        "edge location, not once per view."
    ),
)
async def get_media(
    sha256: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    extension: Annotated[str, Path(pattern=r"^(png|jpg|webp)$")],
    service: Annotated[MediaService, Depends(get_media_service)],
) -> Response:
    asset = await service.get(sha256)
    if asset is None or extension_for(asset.content_type) != extension:
        return Response(status_code=404)
    return Response(
        content=asset.data,
        media_type=asset.content_type.value,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
