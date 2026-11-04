"""Pure environment guards for provider-free integration labs."""

from __future__ import annotations

import os


def lab_database_identity() -> tuple[str, str]:
    """Allow only the two explicitly isolated lab identities, never arbitrary DBs."""
    mode = os.environ.get("SHOP_BETA_QA", "")
    if mode == "1":
        if os.environ.get("CODESPACE_FRESH_SCHEMA") != "true":
            raise RuntimeError("Beta QA requires guarded fresh-schema mode.")
        return "shop_codespace", "shop_codespace"
    if mode:
        raise RuntimeError("Unrecognized Beta QA mode.")
    return "shop_lab_test", "shop_lab"


def require_isolated_lab() -> None:
    """Fail before importing any application modules if safety gates differ."""
    database_name, database_user = lab_database_identity()
    required = {
        "SHOP_TEST_LAB": "1",
        "POSTGRES_DB": database_name,
        "POSTGRES_USER": database_user,
        "DB_HOST": "postgres",
        "WEBHOOK_HOST": "https://disabled.invalid",
        "NEXT_ADMIN_BRIDGE_ENABLED": "true",
        "SHOP_CAMPAIGN_DISPATCH_ENABLED": "false",
        "SHOP_BROADCAST_WORKER_ENABLED": "false",
        "BALE_BROADCAST_PAID_ENABLED": "false",
        "TELEGRAM_STARS_REFUNDS_ENABLED": "false",
        "TELEGRAM_STARS_CHECKOUT_ENABLED": "false",
        "TELEGRAM_FIAT_CHECKOUT_ENABLED": "false",
        "BALE_WALLET_CHECKOUT_ENABLED": "false",
        "CRYPTO_FORWARDING_MODE": "false",
        "SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR": "0",
        "BALE_BROADCAST_PREPARE_CHAT_ID": "0",
    }
    for name, expected in required.items():
        if os.environ.get(name) != expected:
            raise RuntimeError(
                f"Unsafe test lab configuration: {name} must be {expected!r}."
            )

    forbidden = (
        "TOKEN",
        "BALE_BOT_TOKEN",
        "BALE_WALLET_PROVIDER_TOKEN",
        "TELEGRAM_FIAT_PROVIDER_TOKEN",
        "TELEGRAM_WORKER_SECRET",
        "BALE_WEBHOOK_SECRET",
        "KRYPTO_EXPRESS_API_KEY",
    )
    for name in forbidden:
        if os.environ.get(name, "").strip():
            raise RuntimeError(
                f"Unsafe test lab: provider credential {name} is populated."
            )

    if len(os.environ.get("NEXT_ADMIN_BRIDGE_SECRET", "")) < 32:
        raise RuntimeError("The test bridge must use a strong unique key.")

    if len(os.environ.get("JWT_SECRET_KEY", "")) < 32:
        raise RuntimeError("The admin test secret is missing.")
