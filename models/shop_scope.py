"""Reliable defaults for legacy rows during the multi-bot cutover.

Every business row must have a bot-specific owner, not just a Telegram/Bale
platform name. This default is used only by untouched legacy ORM call sites;
new multi-bot runtimes must provide bot_id from an authenticated BotContext.
"""

from __future__ import annotations

from models.shop_multibot import LEGACY_BOT_IDS


def legacy_bot_default(context) -> str:
    """Set a deterministic legacy owner based on the row's platform column.

    SQLAlchemy invokes this Python-side default when an older ORM call site
    constructs a legacy business record without explicitly passing bot_id.
    """
    parameters = context.get_current_parameters()
    platform = parameters.get("platform")
    try:
        return LEGACY_BOT_IDS[platform]
    except (KeyError, TypeError):
        raise ValueError("A valid bot_id or legacy platform is required") from None


def legacy_id(platform: str) -> str:
    """Return the immutable legacy bot ID for a known provider."""
    try:
        return LEGACY_BOT_IDS[platform]
    except KeyError:
        raise ValueError("Unsupported legacy platform") from None
