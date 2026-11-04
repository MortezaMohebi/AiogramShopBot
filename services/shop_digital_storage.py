"""Separate non-web-accessible digital asset vault and safe upload handling.

Unlike ProductMedia, digital merchandise has no publication/preview route.
Files are stored under a sibling of the general media root, with random
server-generated keys, exact signatures, 0600 permissions and a SHA-256
receipt. Archives are never unpacked or executed.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from starlette.datastructures import UploadFile

import config
from dashboard.media_storage import detect_media_type, UnsupportedMediaError
from services.shop_digital_rules import (
    DeliveryPolicyError, safe_digital_filename,
)

MAX_DIGITAL_BYTES = 50_000_000
_DIGITAL_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".zip": "application/zip",
}


@dataclass(frozen=True, slots=True)
class PrivateDigitalFile:
    """Non-secret metadata for one file under the dedicated digital vault."""

    storage_key: str
    name: str
    mime: str
    size: int
    sha256: str


def vault_root() -> Path:
    """Use a separate private sibling, never /static or public ProductMedia."""
    root = Path(config.SHOP_MEDIA_ROOT).resolve()
    if root.name in {"static", "public", "www", "assets"}:
        raise DeliveryPolicyError("General media root cannot be public.")
    return (root.parent / (root.name + "_paid_digital")).resolve()


def private_file_path(key: str) -> Path:
    """Resolve only a generated key under the dedicated private asset root."""
    safe_digital_filename(key)
    root = vault_root()
    path = (root / key).resolve()
    if path.parent != root or path.is_symlink():
        raise DeliveryPolicyError("Invalid digital file location.")
    return path


async def store_digital_file(uploaded: UploadFile) -> PrivateDigitalFile:
    """Stream and SHA-256-check exactly one bounded binary asset to disk."""
    root = vault_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    header = await uploaded.read(64)
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        extension = ".zip"
    else:
        try:
            _, extension, _ = detect_media_type(header)
        except UnsupportedMediaError:
            raise DeliveryPolicyError(
                "Supported digital formats: PDF, ZIP, MP4, MP3, OGG, PNG, JPG, WEBP, GIF."
            ) from None
    name = (uploaded.filename or "paid-file").replace("\\", "/").split("/")[-1]
    name = "".join(
        char for char in name if char.isprintable() and char not in '<>:|?*'
    )[:200] or ("digital" + extension)
    key = secrets.token_hex(16) + extension
    path = private_file_path(key)
    digest = hashlib.sha256()
    total = 0
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            for chunk in (header,):
                total += len(chunk)
                if total > MAX_DIGITAL_BYTES:
                    raise DeliveryPolicyError("Digital file exceeds 50 MB.")
                digest.update(chunk)
                stream.write(chunk)
            while True:
                chunk = await uploaded.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DIGITAL_BYTES:
                    raise DeliveryPolicyError("Digital file exceeds 50 MB.")
                digest.update(chunk)
                stream.write(chunk)
        if total == 0:
            raise DeliveryPolicyError("Digital file is empty.")
        return PrivateDigitalFile(
            key, name, _DIGITAL_MIME[extension], total, digest.hexdigest(),
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await uploaded.close()


def verify_private_file(
    *, key: str, expected_size: int, expected_sha256: str,
) -> Path:
    """Verify file identity and SHA-256 before sending paid merchandise."""
    path = private_file_path(key)
    if (
        not path.is_file()
        or not 0 < expected_size <= MAX_DIGITAL_BYTES
        or path.stat().st_size != expected_size
    ):
        raise DeliveryPolicyError("Paid file is missing or changed.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(256 * 1024), b""):
            digest.update(chunk)
    if not secrets.compare_digest(digest.hexdigest(), expected_sha256):
        raise DeliveryPolicyError("Paid file checksum does not match.")
    return path


@contextmanager
def private_license_document(codes: list[str]) -> Iterator[Path]:
    """Create a 0600 one-time license text attachment, then remove it."""
    if not 1 <= len(codes) <= 99:
        raise DeliveryPolicyError("Invalid license delivery quantity.")
    root = vault_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = private_file_path(secrets.token_hex(16) + ".txt")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(("\n".join(codes) + "\n").encode("utf-8"))
        yield path
    finally:
        path.unlink(missing_ok=True)
