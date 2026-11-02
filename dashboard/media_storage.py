"""Private, validated media storage for the shop's admin uploader.

Files are never served from the public static directory, and names supplied
by visitors do not determine the filesystem path. Only server-generated keys
are used for storage and subsequent bot delivery.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path, PurePath

from starlette.datastructures import UploadFile

from channels.media_policy import BALE_OTHER_UPLOAD_LIMIT, upload_limit


# Restrict file types to formats supported by the bot APIs and safe previews.
_SIGNATURES = {
    "image/png": (".png", "photo"),
    "image/jpeg": (".jpg", "photo"),
    "image/webp": (".webp", "photo"),
    "image/gif": (".gif", "document"),
    "application/pdf": (".pdf", "document"),
    "video/mp4": (".mp4", "video"),
    "audio/mpeg": (".mp3", "audio"),
    "audio/ogg": (".ogg", "audio"),
}
_STORAGE_KEY = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|webp|gif|pdf|mp4|mp3|ogg)$")


class UnsupportedMediaError(ValueError):
    """Invalid or too-large media upload."""


@dataclass(frozen=True, slots=True)
class StoredMedia:
    """File metadata returned after a successful private upload."""

    key: str
    kind: str
    mime_type: str
    original_filename: str
    size_bytes: int


def detect_media_type(header: bytes) -> tuple[str, str, str]:
    """Recognize supported media using file signatures, not user MIME data."""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif header.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        mime = "image/webp"
    elif header.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif header.startswith(b"%PDF-"):
        mime = "application/pdf"
    elif len(header) >= 12 and header[4:8] == b"ftyp":
        mime = "video/mp4"
    elif header.startswith(b"ID3") or (
        len(header) > 2 and header[0] == 255 and header[1] & 224 == 224
    ):
        mime = "audio/mpeg"
    elif header.startswith(b"OggS"):
        mime = "audio/ogg"
    else:
        raise UnsupportedMediaError("فرمت فایل پشتیبانی نمی‌شود.")

    extension, kind = _SIGNATURES[mime]
    return mime, extension, kind


def safe_media_path(root: str | Path, key: str) -> Path:
    """Resolve only server-generated filenames inside the private store."""
    if not isinstance(key, str) or _STORAGE_KEY.fullmatch(key) is None:
        raise UnsupportedMediaError("شناسه فایل معتبر نیست.")
    root_path = Path(root).resolve()
    destination = (root_path / key).resolve()
    if destination.parent != root_path:
        raise UnsupportedMediaError("مسیر فایل غیرمجاز است.")
    return destination


async def save_media(
    uploaded: UploadFile,
    *,
    root: str | Path,
    max_bytes: int,
) -> StoredMedia:
    """Stream one validated file into an exclusive, private destination.

    A rejected/partial upload is deleted immediately. The caller removes
    the file if its database transaction fails after storage succeeds.
    """
    if max_bytes <= 0 or max_bytes > BALE_OTHER_UPLOAD_LIMIT:
        raise ValueError("Invalid upload size configuration.")
    filename = PurePath((uploaded.filename or "").replace("\\", "/")).name
    filename = "".join(
        ch for ch in filename if ch.isprintable() and ch not in "<>:|?*"
    )[:255] or "file"
    root_path = Path(root).resolve()
    root_path.mkdir(mode=0o700, parents=True, exist_ok=True)

    header = await uploaded.read(64)
    try:
        mime, extension, kind = detect_media_type(header)
    except UnsupportedMediaError:
        await uploaded.close()
        raise
    # Multipart photo uploads in Bale are capped at 10 MB; other files
    # may use up to 50 MB. Do not accept a file that cannot be delivered.
    max_bytes = upload_limit(kind, max_bytes)
    key = secrets.token_hex(16) + extension
    destination = safe_media_path(root_path, key)
    amount = 0
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            amount = len(header)
            if amount > max_bytes:
                raise UnsupportedMediaError("حجم فایل بیش از حد مجاز است.")
            output.write(header)
            while True:
                chunk = await uploaded.read(256 * 1024)
                if not chunk:
                    break
                amount += len(chunk)
                if amount > max_bytes:
                    raise UnsupportedMediaError("حجم فایل بیش از حد مجاز است.")
                await asyncio.to_thread(output.write, chunk)
        if amount == 0:
            raise UnsupportedMediaError("فایل خالی است.")
        return StoredMedia(key, kind, mime, filename, amount)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await uploaded.close()
