import os

from dotenv import load_dotenv


load_dotenv(".env")
# Multi-bot receiver is opt-in until PostgreSQL and live-provider P4 QA pass.
MULTIBOT_V2_RUNTIME_ENABLED = (
    os.environ.get("MULTIBOT_V2_RUNTIME_ENABLED", "false")
    .strip().lower() == "true"
)
# Outbound relay pool changes no traffic unless an operator explicitly opts in.
SHOP_RELAY_POOL_ENABLED = (
    os.environ.get("SHOP_RELAY_POOL_ENABLED", "false")
    .strip().lower() == "true"
)
# Registry receivers own their provider credentials and modes.
WEBAPP_HOST = os.environ.get("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.environ.get("WEBAPP_PORT", "5000"))
SHOP_CURRENCY_LABEL = os.environ.get("SHOP_CURRENCY_LABEL", "ریال")
# Canonical shop prices and native Bale wallet invoices are always IRR.
SHOP_CURRENCY = "IRR"
SHOP_DISPLAY_UNIT = os.environ.get("SHOP_DISPLAY_UNIT", "IRR").upper()
if SHOP_DISPLAY_UNIT not in {"IRR", "TOMAN"}:
    raise ValueError("SHOP_DISPLAY_UNIT must be IRR or TOMAN.")
# Checkout is opt-in until live payment, shipping and reconciliation tests pass.
# Telegram fiat must be enabled only after a provider confirms IRR support.
TELEGRAM_FIAT_CHECKOUT_ENABLED = (
    os.environ.get("TELEGRAM_FIAT_CHECKOUT_ENABLED", "false").lower() == "true"
)
# Provider's confirmed conversion of an integer rial to its Bot API minor unit.
TELEGRAM_IRR_MINOR_MULTIPLIER = int(
    os.environ.get("TELEGRAM_IRR_MINOR_MULTIPLIER", "0")
)
TELEGRAM_STARS_CHECKOUT_ENABLED = (
    os.environ.get("TELEGRAM_STARS_CHECKOUT_ENABLED", "false").lower() == "true"
)
TELEGRAM_STARS_REFUNDS_ENABLED = (
    os.environ.get("TELEGRAM_STARS_REFUNDS_ENABLED", "false").lower() == "true"
)
if TELEGRAM_IRR_MINOR_MULTIPLIER not in (0, 1, 10, 100):
    raise ValueError("Telegram IRR minor multiplier is unsupported.")

BALE_WALLET_CHECKOUT_ENABLED = (
    os.environ.get("BALE_WALLET_CHECKOUT_ENABLED", "false").lower() == "true"
)
SHOP_MEDIA_ROOT = os.environ.get("SHOP_MEDIA_ROOT", "./media_data")
# Paid digital content must use a separate, absolute directory not served
# by Product Media/CDN routes. Unconfigured deployments fail closed.
SHOP_DIGITAL_ROOT = os.environ.get("SHOP_DIGITAL_ROOT", "")
SHOP_DIGITAL_DELIVERY_ENABLED = (
    os.environ.get("SHOP_DIGITAL_DELIVERY_ENABLED", "false").lower() == "true"
)
# Bale official multipart limits: photos <=10,000,000 bytes; all other
# supported media <=50,000,000 bytes. The upload service applies the
# stricter photo limit even when the configured site limit is higher.
SHOP_MEDIA_MAX_BYTES = int(
    os.environ.get("SHOP_MEDIA_MAX_BYTES", "50000000")
)
if not 1 <= SHOP_MEDIA_MAX_BYTES <= 50_000_000:
    raise ValueError("SHOP_MEDIA_MAX_BYTES must be 1..50,000,000 bytes.")
# POSTGRESQL
DB_USER = os.environ.get("POSTGRES_USER", "postgres")
DB_PASS = os.environ.get("POSTGRES_PASSWORD")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_NAME = os.environ.get("POSTGRES_DB", "aiogram-shop-bot")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD")
# Zero disables manual merchant store-credit adjustments until configured.
SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR = int(
    os.environ.get("SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR", "0")
)
if not 0 <= SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR <= 100_000_000_000:
    raise ValueError("SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR out of range.")

# Set to false ONLY for explicitly isolated HTTP development environments.
SHOP_ADMIN_SECURE_COOKIES = (
    os.environ.get("SHOP_ADMIN_SECURE_COOKIES", "true").lower() == "true"
)

# Keep SQL parameters (addresses/payment metadata) out of production logs.
DB_SQL_ECHO = os.environ.get("DB_SQL_ECHO", "false").strip().lower() == "true"

# Campaign dispatch is disabled until consent and rate limiting pass live QA.
SHOP_CAMPAIGN_DISPATCH_ENABLED = (
    os.environ.get("SHOP_CAMPAIGN_DISPATCH_ENABLED", "false").lower() == "true"
)

# Bale regular Bot API has interactive rate limits. The optional Business API
# has separate higher throughput and CHARGES per message from merchant credit.
BALE_BROADCAST_MODE = os.environ.get(
    "BALE_BROADCAST_MODE", "standard"
).strip().lower()
if BALE_BROADCAST_MODE not in ("standard", "business"):
    raise ValueError("BALE_BROADCAST_MODE must be standard or business.")
BALE_BROADCAST_PAID_ENABLED = (
    os.environ.get("BALE_BROADCAST_PAID_ENABLED", "false").lower() == "true"
)
# The one shared durable broadcast worker is opt-in until final live QA.
# Telegram's free broadcast ceiling is about 30 messages/s; these defaults
# stay safely below it. Bale limits need field verification; use conservative
# values unless the provider explicitly approves higher throughput.
SHOP_BROADCAST_WORKER_ENABLED = (
    os.environ.get("SHOP_BROADCAST_WORKER_ENABLED", "false").lower() == "true"
)
# Registry campaigns additionally require the CLI's per-bot transport factory.
SHOP_BROADCAST_REGISTRY_ENABLED = (
    os.environ.get("SHOP_BROADCAST_REGISTRY_ENABLED", "false").lower() == "true"
)
SHOP_BROADCAST_TELEGRAM_MPS = int(
    os.environ.get("SHOP_BROADCAST_TELEGRAM_MPS", "5")
)
SHOP_BROADCAST_BALE_STANDARD_MPS = int(
    os.environ.get("SHOP_BROADCAST_BALE_STANDARD_MPS", "1")
)
SHOP_BROADCAST_BALE_BUSINESS_MPS = int(
    os.environ.get("SHOP_BROADCAST_BALE_BUSINESS_MPS", "5")
)
SHOP_BROADCAST_MAX_PAID_CALLS = int(
    os.environ.get("SHOP_BROADCAST_MAX_PAID_CALLS", "0")
)
SHOP_BROADCAST_POLL_SECONDS = int(
    os.environ.get("SHOP_BROADCAST_POLL_SECONDS", "2")
)
SHOP_BROADCAST_STALE_SECONDS = int(
    os.environ.get("SHOP_BROADCAST_STALE_SECONDS", "900")
)
if not 1 <= SHOP_BROADCAST_TELEGRAM_MPS <= 20:
    raise ValueError("Telegram broadcast limit must be 1..20 msg/s.")
if not 1 <= SHOP_BROADCAST_BALE_STANDARD_MPS <= 5:
    raise ValueError("Bale standard broadcast limit must be 1..5 msg/s.")
if not 1 <= SHOP_BROADCAST_BALE_BUSINESS_MPS <= 10:
    raise ValueError("Bale business broadcast limit must be 1..10 msg/s.")
if not 0 <= SHOP_BROADCAST_MAX_PAID_CALLS <= 1_000_000:
    raise ValueError("Maximum billable Bale calls is out of range.")
if not 1 <= SHOP_BROADCAST_POLL_SECONDS <= 30:
    raise ValueError("Broadcast polling must be 1..30 seconds.")
if not 300 <= SHOP_BROADCAST_STALE_SECONDS <= 86_400:
    raise ValueError("Broadcast stale-claim threshold is invalid.")

# The Next.js dashboard uses a dedicated server-only HMAC bridge.
# The bridge is disabled until both processes share a strong secret.
NEXT_ADMIN_BRIDGE_ENABLED = (
    os.environ.get("NEXT_ADMIN_BRIDGE_ENABLED", "false").lower() == "true"
)
NEXT_ADMIN_BRIDGE_SECRET = os.environ.get(
    "NEXT_ADMIN_BRIDGE_SECRET", ""
)
if NEXT_ADMIN_BRIDGE_ENABLED and len(NEXT_ADMIN_BRIDGE_SECRET) < 32:
    raise ValueError(
        "NEXT_ADMIN_BRIDGE_SECRET must be at least 32 characters when enabled."
    )

# Workflow Runtime requires explicit global and per-Store/per-Bot opt-in.
SHOP_WORKFLOW_RUNTIME_ENABLED = os.environ.get("SHOP_WORKFLOW_RUNTIME_ENABLED", "false").lower() == "true"
SHOP_WORKFLOW_RUNTIME_KILL_SWITCH = os.environ.get("SHOP_WORKFLOW_RUNTIME_KILL_SWITCH", "false").lower() == "true"
