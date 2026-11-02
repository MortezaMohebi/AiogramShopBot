"""Private media signature and path validation tests."""

from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from dashboard.media_storage import (
    UnsupportedMediaError,
    detect_media_type,
    safe_media_path,
    save_media,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"sample", "image/png"),
        (b"\xff\xd8\xff" + b"sample", "image/jpeg"),
        (b"%PDF-1.5\n" + b"sample", "application/pdf"),
        (b"ID3" + b"sample", "audio/mpeg"),
        (b"OggS" + b"sample", "audio/ogg"),
    ],
)
def test_detect_allowed_file_signatures(header, expected):
    """Use magic bytes rather than the client's filename or MIME header."""
    assert detect_media_type(header)[0] == expected


def test_path_rejects_file_traversal(tmp_path):
    """Prevent administrators or callbacks from selecting arbitrary files."""
    with pytest.raises(UnsupportedMediaError):
        safe_media_path(tmp_path, "../../etc/passwd")


@pytest.mark.asyncio
async def test_save_media_keeps_uploaded_name_out_of_path(tmp_path):
    """Store valid files using unpredictable private keys."""
    file = UploadFile(
        file=BytesIO(b"\x89PNG\r\n\x1a\n" + b"safe-data"),
        filename="../../bad.png",
    )
    stored = await save_media(file, root=tmp_path, max_bytes=1000)
    assert stored.kind == "photo"
    assert stored.original_filename == "bad.png"
    assert stored.storage_key if hasattr(stored, "storage_key") else stored.key
    path = safe_media_path(tmp_path, stored.key)
    assert path.is_file()
    assert path.read_bytes().startswith(b"\x89PNG")
    assert path.parent == tmp_path.resolve()


@pytest.mark.asyncio
async def test_upload_size_limit_removes_partial_file(tmp_path):
    """Ensure oversized uploads do not leave private temporary files."""
    file = UploadFile(
        file=BytesIO(b"%PDF-1.7" + b"X" * 200),
        filename="big.pdf",
    )
    with pytest.raises(UnsupportedMediaError):
        await save_media(file, root=tmp_path, max_bytes=20)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_reject_executable_disguised_as_image(tmp_path):
    """Accept only recognized magic, never a spoofed file extension."""
    file = UploadFile(
        file=BytesIO(b"MZ" + b"Executable"),
        filename="photo.jpg",
    )
    with pytest.raises(UnsupportedMediaError):
        await save_media(file, root=tmp_path, max_bytes=100)
