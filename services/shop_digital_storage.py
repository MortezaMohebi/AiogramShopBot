"""Private, streaming and bounded digital file storage (never public Media).

Files stay outside SHOP_MEDIA_ROOT and static directories. Server-generated
random names, exact SHA-256 receipts, exclusive 0600 writes and strict media
signatures prevent directory traversal, unbounded uploads and public catalog
leaks. Only authenticated staff can call this storage layer.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path, PurePath

from starlette.datastructures import UploadFile

from services.shop_digital_rules import (
    DeliveryPolicyError, safe_digital_filename,
)

_MAX_FILE = 50_000_000
_MIMES = {
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".epub": "application/epub+zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".txt": "text/plain",
}
_ZIPPED = frozenset({".zip", ".docx", ".xlsx", ".epub"})


@dataclass(frozen=True, slots=True)
class PrivateDigitalFile:
    """Metadata for a persisted asset; the private root is not serialized."""

    storage_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str


def digital_root(root: str | Path, *, public_media_root: str | Path) -> Path:
    """Refuse unset, relative or overlapping roots that might expose paid files."""
    if not isinstance(root, (str, Path)) or not str(root).strip():
        raise DeliveryPolicyError("SHOP_DIGITAL_ROOT is not configured.")
    if not Path(root).is_absolute():
        raise DeliveryPolicyError("Private digital storage root must be absolute.")
    private = Path(root).resolve()
    media = Path(public_media_root).resolve()
    if (
        private == media
        or private in media.parents
        or media in private.parents
    ):
        raise DeliveryPolicyError("Digital assets cannot share the public media root.")
    return private


def safe_digital_path(root: str | Path, key: str) -> Path:
    """Return only a random filename inside the private delivery directory."""
    safe_digital_filename(key)
    base = Path(root).resolve()
    path = base / key
    if path.is_symlink() or path.resolve().parent != base:
        raise DeliveryPolicyError("Invalid private digital storage path.")
    return path


def _mime_for_content(ext: str, header: bytes) -> str:
    """Accept a small allowlist with matching file magic, never client MIME."""
    if ext not in _MIMES:
        raise DeliveryPolicyError("Unsupported digital asset extension.")
    supported = (
        ext in _ZIPPED and header.startswith(bytes((0x50, 0x4B, 0x03, 0x04)))
        or ext == ".pdf" and header.startswith(b"%PDF-")
        or ext == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n")
        or ext == ".jpg" and header.startswith(b"\xff\xd8\xff")
        or ext == ".webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
        or ext == ".gif" and header.startswith((b"GIF87a", b"GIF89a"))
        or ext == ".mp4" and len(header) >= 12 and header[4:8] == b"ftyp"
        or ext == ".mp3" and (
            header.startswith(b"ID3")
            or len(header) > 2 and header[0] == 0xFF
            and header[1] & 0xE0 == 0xE0
        )
        or ext == ".ogg" and header.startswith(b"OggS")
        or ext == ".txt" and b"\x00" not in header
    )
    if not supported:
        raise DeliveryPolicyError("Invalid digital file signature.")
    return _MIMES[ext]


async def save_digital_file(
    uploaded: UploadFile, *, root: str | Path,
    public_media_root: str | Path, max_bytes: int = _MAX_FILE,
) -> PrivateDigitalFile:
    """Stream an authenticated upload to private exclusive storage.

    Caller MUST unlink the stored file if the subsequent DB transaction
    fails. Upload data never appears in logs, CDN, media cache or URLs.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_FILE:
        raise DeliveryPolicyError("Invalid digital upload size.")
    filename = PurePath((uploaded.filename or "").replace("\\", "/")).name
    filename = "".join(
        char for char in filename if char.isprintable()
        and char not in "<>:|?*\\/"
    )[:255]
    ext = Path(filename).suffix.lower()
    base = digital_root(root, public_media_root=public_media_root)
    base.mkdir(parents=True, mode=0o700, exist_ok=True)
    first = await uploaded.read(64)
    try:
        mime = _mime_for_content(ext, first)
        key = secrets.token_hex(16) + ext
        destination = safe_digital_path(base, key)
        checksum = hashlib.sha256()
        size = 0
        try:
            fd = os.open(
                destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(fd, "wb") as stream:
                for chunk in (first,):
                    if chunk:
                        stream.write(chunk)
                        checksum.update(chunk)
                        size += len(chunk)
                while True:
                    chunk = await uploaded.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise DeliveryPolicyError("Private file size exceeds limit.")
                    checksum.update(chunk)
                    await asyncio.to_thread(stream.write, chunk)
            if not 0 < size <= max_bytes:
                raise DeliveryPolicyError("Digital file is empty or too large.")
            return PrivateDigitalFile(
                storage_key=key,
                original_filename=filename or ("asset" + ext),
                mime_type=mime, size_bytes=size,
                sha256=checksum.hexdigest(),
            )
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    finally:
        await uploaded.close()
