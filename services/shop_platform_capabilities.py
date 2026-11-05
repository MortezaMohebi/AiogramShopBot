"""Official Telegram/Bale limits and the separately verified adapter contract.

Sources reviewed 2026-11-05: https://core.telegram.org/bots/api and
https://docs.bale.ai/. Studio never executes or probes either provider.
"""

from copy import deepcopy

CAPABILITIES = {
    "telegram": {
        "text_characters": 4096,
        "caption_characters": 1024,
        "adapter_caption_characters": 1024,
        "callback_bytes": 64,
        "photo_bytes": 10_000_000,
        "file_bytes": 50_000_000,
        "download_bytes": 20_000_000,
        "inline_keyboard": True,
        "reply_keyboard": True,
        "request_contact": True,
        "message_editing": True,
        "media_group": True,
        "adapter_media_group": False,
        "media_group_items": 10,
        "native_payment": "telegram_stars_or_configured_fiat",
    },
    "bale": {
        "text_characters": 4096,
        "caption_characters": 4096,
        # Current channels/bale.py deliberately truncates captions at 1024.
        "adapter_caption_characters": 1024,
        "callback_bytes": 64,
        "photo_bytes": 10_000_000,
        "file_bytes": 50_000_000,
        "download_bytes": 20_000_000,
        "inline_keyboard": True,
        "reply_keyboard": True,
        "request_contact": True,
        "message_editing": True,
        "media_group": True,
        "adapter_media_group": False,
        # Bale documentation does not specify an official album count ceiling.
        "media_group_items": None,
        "editor_media_group_items": 10,
        "native_payment": "bale_wallet_irr",
    },
}


def platform_capabilities() -> dict:
    """Return redacted independent capability metadata, never mutable globals."""
    return deepcopy(CAPABILITIES)
