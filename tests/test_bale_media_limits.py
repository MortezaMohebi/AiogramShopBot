"""Offline checks for documented Bale multipart limits and bot-scoped IDs.

The test suite does not upload any file to Telegram, Bale or Cloudflare.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from channels.media_policy import (
    BALE_OTHER_UPLOAD_LIMIT,
    BALE_PHOTO_UPLOAD_LIMIT,
    BALE_VOICE_LIMIT,
    MediaLimitError,
    bale_media_method,
    upload_limit,
)
from dashboard.media_storage import (
    UnsupportedMediaError, safe_media_path, save_media,
)
from services.shop_media_delivery import bot_fingerprint


def test_official_bale_multipart_limits_are_decimal_megabytes() -> None:
    """Bale documents 10 MB photo and 50 MB other multipart uploads."""
    assert BALE_PHOTO_UPLOAD_LIMIT == 10_000_000
    assert BALE_OTHER_UPLOAD_LIMIT == 50_000_000
    assert upload_limit("photo", 50_000_000) == 10_000_000
    assert upload_limit("document", 50_000_000) == 50_000_000
    assert upload_limit("video", 18_000_000) == 18_000_000


@pytest.mark.parametrize(
    ("kind", "mime", "size", "expected"),
    [
        ("photo", "image/jpeg", 10_000_000, "sendPhoto"),
        ("video", "video/mp4", 50_000_000, "sendVideo"),
        ("document", "application/pdf", 50_000_000, "sendDocument"),
        ("audio", "audio/mpeg", 50_000_000, "sendAudio"),
        ("audio", "audio/ogg", BALE_VOICE_LIMIT, "sendVoice"),
        ("audio", "audio/ogg", BALE_VOICE_LIMIT + 1, "sendDocument"),
    ],
)
def test_bale_compatible_method_is_selected_before_upload(
    kind: str, mime: str, size: int, expected: str
) -> None:
    """Keep voice, audio, images and documents within the right endpoint."""
    method = bale_media_method(kind, mime, size)
    assert method.name == expected


@pytest.mark.parametrize(
    ("kind", "mime", "size"),
    [
        ("photo", "image/png", 10_000_001),
        ("video", "video/mp4", 50_000_001),
        ("document", "application/pdf", 50_000_001),
        ("photo", "image/jpeg", 0),
        ("audio", "audio/invalid", 1024),
    ],
)
def test_unsupported_size_or_format_is_rejected_before_network(
    kind: str, mime: str, size: int
) -> None:
    """Reject rather than trying an unsupported Bale multipart API call."""
    with pytest.raises(MediaLimitError):
        bale_media_method(kind, mime, size)


@pytest.mark.asyncio
async def test_photo_source_over_bale_limit_is_removed(tmp_path) -> None:
    """A photo over 10,000,000 bytes cannot be stored as a cross-channel photo."""
    content = BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 10_000_000)
    uploaded = UploadFile(file=content, filename="too-big.png")
    with pytest.raises(UnsupportedMediaError):
        await save_media(
            uploaded, root=tmp_path, max_bytes=BALE_OTHER_UPLOAD_LIMIT
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_regular_pdf_under_other_limit_is_stored(tmp_path) -> None:
    """A supported document remains private with a random storage key."""
    data = b"%PDF-1.5\n" + b"x" * 512
    uploaded = UploadFile(file=BytesIO(data), filename="manual.pdf")
    stored = await save_media(
        uploaded, root=tmp_path, max_bytes=BALE_OTHER_UPLOAD_LIMIT
    )
    assert stored.kind == "document"
    assert stored.size_bytes == len(data)
    assert safe_media_path(tmp_path, stored.key).read_bytes() == data


def test_file_id_namespace_uses_the_original_bot_token() -> None:
    """One remote ID must never be reused by a different bot or platform."""
    first = bot_fingerprint("123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    second = bot_fingerprint("123456:BBBBBBBBBBBBBBBBBBBBBBBBBBBB")
    assert first != second
    assert first == bot_fingerprint(
        "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )
    assert len(first) == 64
    assert "AAAA" not in first
