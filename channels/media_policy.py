"""Bot API upload limits, kept separate from shop content configuration.

Bale official Bot API (docs.bale.ai): direct multipart images <=10 MB and
other media <=50 MB. HTTP URL transfer is stricter (5/20 MB), so the shop
uses private multipart uploads. These are decimal MB caps, not MiB.
"""

from __future__ import annotations

from dataclasses import dataclass

BALE_PHOTO_UPLOAD_LIMIT = 10_000_000
BALE_OTHER_UPLOAD_LIMIT = 50_000_000
BALE_VOICE_LIMIT = 1_000_000


class MediaLimitError(ValueError):
    """A file is too large or incompatible with a platform method."""


@dataclass(frozen=True, slots=True)
class BaleMediaMethod:
    """The compatible Bale API method, multipart field and delivery type."""

    name: str
    field: str
    kind: str


def upload_limit(kind: str, configured_max: int) -> int:
    """Cap private source uploads by documented Bale multipart limits."""
    if type(configured_max) is not int or not 1 <= configured_max <= BALE_OTHER_UPLOAD_LIMIT:
        raise ValueError("The shop media limit must be 1..50,000,000 bytes.")
    if kind == "photo":
        return min(configured_max, BALE_PHOTO_UPLOAD_LIMIT)
    if kind not in ("document", "video", "audio", "animation"):
        raise MediaLimitError("این نوع رسانه پشتیبانی نمی‌شود.")
    return min(configured_max, BALE_OTHER_UPLOAD_LIMIT)


def bale_media_method(kind: str, mime: str, size_bytes: int) -> BaleMediaMethod:
    """Validate actual disk size and choose one supported multipart method.

    An OGG voice message exceeding Bale's 1 MB voice limit is sent as a
    document rather than claimed to be an unsupported voice/audio message.
    """
    if type(size_bytes) is not int or size_bytes <= 0:
        raise MediaLimitError("اندازه فایل معتبر نیست.")
    if size_bytes > upload_limit(kind, BALE_OTHER_UPLOAD_LIMIT):
        raise MediaLimitError("حجم فایل از محدودیت آپلود بله بیشتر است.")

    if kind == "photo" and mime in ("image/jpeg", "image/png", "image/webp"):
        return BaleMediaMethod("sendPhoto", "photo", "photo")
    if kind == "video" and mime == "video/mp4":
        return BaleMediaMethod("sendVideo", "video", "video")
    if kind == "audio" and mime == "audio/mpeg":
        return BaleMediaMethod("sendAudio", "audio", "audio")
    if kind == "audio" and mime == "audio/ogg":
        if size_bytes <= BALE_VOICE_LIMIT:
            return BaleMediaMethod("sendVoice", "voice", "voice")
        return BaleMediaMethod("sendDocument", "document", "document")
    if kind == "animation" and mime == "image/gif":
        return BaleMediaMethod("sendAnimation", "animation", "animation")
    if kind == "document":
        return BaleMediaMethod("sendDocument", "document", "document")
    raise MediaLimitError("نوع رسانه با متد ارسال بله سازگار نیست.")
