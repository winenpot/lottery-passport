"""Admin image upload (W10): magic-byte sniffing, size ceiling, naming.

SVG is refused on purpose -- it can carry a <script> tag, so trusting the
client-sent Content-Type or the filename would make "image upload" a
stored-XSS vector for anyone with /admin write access.
"""

import pytest

from app.domain.media import (
    MAX_BYTES,
    MediaContentType,
    MediaError,
    MediaRefusal,
    extension_for,
    sniff_content_type,
    validate_upload,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 20
WEBP_MAGIC = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20
SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG_MAGIC, MediaContentType.PNG),
        (JPEG_MAGIC, MediaContentType.JPEG),
        (WEBP_MAGIC, MediaContentType.WEBP),
    ],
)
def test_sniffs_the_real_type_from_magic_bytes(
    data: bytes, expected: MediaContentType
) -> None:
    assert sniff_content_type(data) == expected


def test_svg_is_refused_even_though_it_is_a_text_image_format() -> None:
    """An SVG can carry a <script> tag -- refusing it is the point, not a gap."""
    with pytest.raises(MediaError) as caught:
        sniff_content_type(SVG_BYTES)
    assert caught.value.reason is MediaRefusal.UNSUPPORTED_TYPE


def test_a_spoofed_extension_does_not_fool_the_sniffer() -> None:
    """The caller never gets to say what type this is -- only the bytes do."""
    fake_png_bytes_that_are_actually_text = b"not a real image, just text"
    with pytest.raises(MediaError) as caught:
        sniff_content_type(fake_png_bytes_that_are_actually_text)
    assert caught.value.reason is MediaRefusal.UNSUPPORTED_TYPE


def test_empty_upload_is_refused() -> None:
    with pytest.raises(MediaError) as caught:
        validate_upload(b"")
    assert caught.value.reason is MediaRefusal.EMPTY


def test_upload_right_at_the_ceiling_is_accepted() -> None:
    data = PNG_MAGIC + b"\x00" * (MAX_BYTES - len(PNG_MAGIC))
    assert len(data) == MAX_BYTES
    assert validate_upload(data) == MediaContentType.PNG


def test_upload_one_byte_over_the_ceiling_is_refused() -> None:
    data = PNG_MAGIC + b"\x00" * (MAX_BYTES - len(PNG_MAGIC) + 1)
    with pytest.raises(MediaError) as caught:
        validate_upload(data)
    assert caught.value.reason is MediaRefusal.TOO_LARGE


def test_extension_for_round_trips_every_content_type() -> None:
    assert extension_for(MediaContentType.PNG) == "png"
    assert extension_for(MediaContentType.JPEG) == "jpg"
    assert extension_for(MediaContentType.WEBP) == "webp"
