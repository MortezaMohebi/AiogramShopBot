"""Prepare isolated Codespace QA secrets without reading deployment credentials."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import secrets


ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / ".codespaces" / "beta-qa.env"
PROVIDER_KEYS = (
    "TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "LIVE_TELEGRAM_TOKEN",
    "LIVE_BALE_TOKEN",
    "BALE_BOT_TOKEN",
    "BALE_WALLET_PROVIDER_TOKEN",
    "TELEGRAM_FIAT_PROVIDER_TOKEN",
    "TELEGRAM_WORKER_SECRET",
    "BALE_WEBHOOK_SECRET",
    "KRYPTO_EXPRESS_API_KEY",
)


def prepare_environment(target: Path = TARGET) -> Path:
    """Create a private, repeatable QA environment; never replace another one."""
    if target.is_symlink():
        raise RuntimeError("QA environment must not be a symbolic link.")
    if target.exists():
        values = dict(
            line.split("=", 1)
            for line in target.read_text().splitlines()
            if line and not line.startswith("#") and "=" in line
        )
        if (
            values.get("SHOP_BETA_QA") != "1"
            or values.get("POSTGRES_DB") != "shop_codespace"
            or values.get("POSTGRES_USER") != "shop_codespace"
            or any(values.get(key, "").strip() for key in PROVIDER_KEYS)
            or len(values.get("POSTGRES_PASSWORD", "")) < 32
        ):
            raise RuntimeError("Existing file is not the isolated Beta QA environment.")
        target.chmod(0o600)
        return target

    values = {
        "SHOP_BETA_QA": "1",
        "SHOP_TEST_LAB": "1",
        "CODESPACE_FRESH_SCHEMA": "true",
        "POSTGRES_DB": "shop_codespace",
        "DB_NAME": "shop_codespace",
        "POSTGRES_USER": "shop_codespace",
        "DB_USER": "shop_codespace",
        "DB_HOST": "postgres",
        "DB_PORT": "5432",
        "DB_SQL_ECHO": "false",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "REDIS_HOST": "redis",
        "REDIS_PASSWORD": secrets.token_urlsafe(32),
        "LIVE_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "NEXT_ADMIN_BRIDGE_ENABLED": "true",
        "NEXT_ADMIN_BRIDGE_SECRET": secrets.token_urlsafe(48),
        "NEXT_ADMIN_SESSION_SECRET": secrets.token_urlsafe(48),
        "SHOP_SECURITY_ENCRYPTION_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode("ascii"),
        "SHOP_FASTAPI_INTERNAL_URL": "http://127.0.0.1:8091",
        # In next dev, an unset origin uses the same-origin localhost request.
        # An explicitly configured public origin requires HTTPS in production.
        "NEXT_ADMIN_PUBLIC_ORIGIN": "",
        "NEXT_ADMIN_CAPTCHA_PROVIDER": "none",
        "RUNTIME_ENVIRONMENT": "PROD",
        "SHOP_ADMIN_SECURE_COOKIES": "false",
        "SHOP_MEDIA_ROOT": "/qa/public",
        "SHOP_DIGITAL_ROOT": "/qa/private",
        "SHOP_DIGITAL_DELIVERY_ENABLED": "false",
        "SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR": "0",
        "SHOP_CAMPAIGN_DISPATCH_ENABLED": "false",
        "SHOP_BROADCAST_WORKER_ENABLED": "false",
        "SHOP_BROADCAST_REGISTRY_ENABLED": "false",
        "SHOP_CUSTOMER_NOTIFICATIONS_ENABLED": "false",
        "BALE_BROADCAST_PAID_ENABLED": "false",
        "TELEGRAM_STARS_REFUNDS_ENABLED": "false",
        "TELEGRAM_STARS_CHECKOUT_ENABLED": "false",
        "TELEGRAM_FIAT_CHECKOUT_ENABLED": "false",
        "BALE_WALLET_CHECKOUT_ENABLED": "false",
        "MULTIBOT_V2_RUNTIME_ENABLED": "false",
        "SHOP_RELAY_POOL_ENABLED": "false",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves a concurrently prepared environment.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    return target


if __name__ == "__main__":
    prepare_environment()
    print("Isolated Beta QA environment prepared; provider credentials are empty.")
