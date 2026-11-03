"""Probe real provider APIs and explicitly register external webhooks.

Never send an unsolicited message, create an invoice or enable Broadcast.
Telegram uses the project's configured transport (direct/proxy/CF Worker).
Bale uses its documented regular Bot API only.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from aiohttp import ClientSession, ClientTimeout

import config
from channels.bale import BaleApiError, BaleTransport
from utils.telegram import create_bot, create_telegram_session


def validate() -> None:
    """Fail closed if the host or outbound paid flags are unsafe."""
    if os.getenv("POSTGRES_DB") != "shop_codespace":
        raise RuntimeError("Only the Codespaces database may be used.")
    if not config.WEBHOOK_URL.startswith("https://"):
        raise RuntimeError("Telegram HTTPS webhook URL is missing.")
    if not config.BALE_BOT_TOKEN or not config.BALE_WEBHOOK_SECRET:
        raise RuntimeError("Both provider bot credentials are required.")
    if config.SHOP_CAMPAIGN_DISPATCH_ENABLED or config.BALE_BROADCAST_PAID_ENABLED:
        raise RuntimeError("Paid/broadcast operations must remain disabled.")


async def check_provider(*, register: bool, unregister: bool) -> None:
    """Check both tokens; register only after a separate explicit request."""
    validate()
    if register and config.TELEGRAM_UPDATE_MODE != "webhook":
        raise RuntimeError(
            "Cannot register Telegram webhook while getUpdates is active."
        )
    tg_bot = create_bot(config.TOKEN, create_telegram_session())
    try:
        me = await tg_bot.get_me()
        print(f"Telegram API: OK (@{me.username or 'unnamed'})")
        info = await tg_bot.get_webhook_info()
        expected_tg = config.WEBHOOK_URL
        if unregister:
            if info.url == expected_tg:
                await tg_bot.delete_webhook(drop_pending_updates=False)
                print("Telegram webhook: removed from this Codespace")
            else:
                print("Telegram webhook: points elsewhere, preserved")
        elif register:
            # Idempotent and non-destructive to pending customer updates.
            # Always refresh the webhook secret header too. A same-URL
            # registration can otherwise retain an obsolete token.
            await tg_bot.set_webhook(
                url=expected_tg,
                secret_token=config.WEBHOOK_SECRET_TOKEN,
                drop_pending_updates=False,
                max_connections=2,
            )
            print("Telegram webhook: configured on Codespace gateway")
        else:
            status = "matching" if info.url == expected_tg else "not matching"
            print(f"Telegram webhook: {status}")

        async with ClientSession(
            timeout=ClientTimeout(total=15), trust_env=False
        ) as client:
            bale = BaleTransport(config.BALE_BOT_TOKEN, client)
            identity = await bale._call("getMe", {})
            username = identity.get("username", "unnamed") if isinstance(
                identity, dict
            ) else "unknown"
            print(f"Bale Bot API: OK (@{username})")
            desired_bale = (
                f"{config.WEBHOOK_HOST}/webhooks/bale/"
                f"{config.BALE_WEBHOOK_SECRET}"
            )
            if register:
                await bale._call("setWebhook", {"url": desired_bale})
                print("Bale webhook: registration accepted by provider")
            else:
                # Some Bale API versions do not expose getWebhookInfo.
                try:
                    info_bale = await bale._call("getWebhookInfo", {})
                except BaleApiError:
                    if unregister:
                        raise RuntimeError(
                            "Cannot safely verify Bale webhook ownership; "
                            "check it manually before disconnecting."
                        ) from None
                    print("Bale webhook status: unsupported on this Bot API version")
                else:
                    current = info_bale.get("url", "") if isinstance(
                        info_bale, dict
                    ) else ""
                    if unregister and current == desired_bale:
                        await bale._call("deleteWebhook", {})
                        print("Bale webhook: removed from this Codespace")
                    else:
                        print(
                            "Bale webhook: "
                            + ("matching" if current == desired_bale else "not matching")
                        )
    finally:
        await tg_bot.session.close()


def main() -> None:
    """Require an explicit flag before registering either external webhook."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--unregister", action="store_true",
        help="Remove only webhooks still pointing to this Codespace.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register Codespace webhooks with real Telegram and Bale bots.",
    )
    args = parser.parse_args()
    if args.register and args.unregister:
        parser.error("Choose register OR unregister.")
    try:
        asyncio.run(check_provider(
            register=args.register, unregister=args.unregister
        ))
    except Exception as error:
        # Third-party error messages may contain provider URLs with tokens.
        # Never echo raw exception, headers or response bodies.
        raise SystemExit(
            f"Provider check failed ({type(error).__name__}). "
            "Check API credentials, network, Codespaces port visibility "
            "and provider status without sharing secrets."
        ) from None


if __name__ == "__main__":
    main()
