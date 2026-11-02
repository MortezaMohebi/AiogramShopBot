import os

from dotenv import load_dotenv

from enums.currency import Currency
from enums.runtime_environment import RuntimeEnvironment
from utils.utils import get_sslipio_external_url, start_ngrok

load_dotenv(".env.bot.dev")
RUNTIME_ENVIRONMENT = RuntimeEnvironment(os.environ.get("RUNTIME_ENVIRONMENT"))
TELEGRAM_UPDATE_MODE = os.environ.get("TELEGRAM_UPDATE_MODE", "webhook").strip().lower()
if TELEGRAM_UPDATE_MODE not in {"webhook", "polling"}:
    raise ValueError("TELEGRAM_UPDATE_MODE must be webhook or polling.")
# Prefer an explicit HTTPS host in production. An external IP lookup should
# never be mandatory for installations hosted behind a known domain.
explicit_webhook_host = os.environ.get("WEBHOOK_HOST", "").strip()
if explicit_webhook_host:
    if not explicit_webhook_host.startswith("https://"):
        raise ValueError("WEBHOOK_HOST must use HTTPS.")
    WEBHOOK_HOST = explicit_webhook_host.rstrip("/")
elif TELEGRAM_UPDATE_MODE == "polling":
    # Polling through a Cloudflare Worker needs no public Telegram webhook.
    WEBHOOK_HOST = ""
elif RUNTIME_ENVIRONMENT == RuntimeEnvironment.DEV:
    WEBHOOK_HOST = start_ngrok()
else:
    WEBHOOK_HOST = get_sslipio_external_url()
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/")
WEBAPP_HOST = os.environ.get("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.environ.get("WEBAPP_PORT", "5000"))
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
TOKEN = os.environ.get("TOKEN")
# Legacy Telegram notification IDs are optional, not dashboard credentials.
_raw_admin_ids = os.environ.get("ADMIN_ID_LIST", "").strip()
try:
    ADMIN_ID_LIST = (
        [int(value.strip()) for value in _raw_admin_ids.split(",")]
        if _raw_admin_ids else []
    )
except ValueError:
    raise ValueError("ADMIN_ID_LIST must contain numeric IDs only.") from None
SUPPORT_LINK = os.environ.get("SUPPORT_LINK")
# Dual-channel storefront: secrets are never stored in version control.
BALE_BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN")
BALE_WEBHOOK_SECRET = os.environ.get("BALE_WEBHOOK_SECRET")
SHOP_CURRENCY_LABEL = os.environ.get("SHOP_CURRENCY_LABEL", "ریال")
# Canonical shop prices and native Bale wallet invoices are always IRR.
SHOP_CURRENCY = "IRR"
SHOP_DISPLAY_UNIT = os.environ.get("SHOP_DISPLAY_UNIT", "IRR").upper()
if SHOP_DISPLAY_UNIT not in {"IRR", "TOMAN"}:
    raise ValueError("SHOP_DISPLAY_UNIT must be IRR or TOMAN.")
BALE_WALLET_PROVIDER_TOKEN = os.environ.get("BALE_WALLET_PROVIDER_TOKEN", "")
# Checkout is opt-in until live payment, shipping and reconciliation tests pass.
# Telegram fiat must be enabled only after a provider confirms IRR support.
TELEGRAM_FIAT_CHECKOUT_ENABLED = (
    os.environ.get("TELEGRAM_FIAT_CHECKOUT_ENABLED", "false").lower() == "true"
)
TELEGRAM_FIAT_PROVIDER_TOKEN = os.environ.get(
    "TELEGRAM_FIAT_PROVIDER_TOKEN", ""
).strip()
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
# Legacy screens require a Telegram image ID; never fetch stock photos.
DEFAULT_MEDIA_FILE_ID = os.environ.get("DEFAULT_MEDIA_FILE_ID", "").strip()
SHOP_MEDIA_MAX_BYTES = int(os.environ.get("SHOP_MEDIA_MAX_BYTES", "20971520"))
if not 1 <= SHOP_MEDIA_MAX_BYTES <= 20971520:
    raise ValueError("SHOP_MEDIA_MAX_BYTES must be between 1 and 20971520.")
# POSTGRESQL
DB_USER = os.environ.get("POSTGRES_USER", "postgres")
DB_PASS = os.environ.get("POSTGRES_PASSWORD")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_NAME = os.environ.get("POSTGRES_DB", "aiogram-shop-bot")
PAGE_ENTRIES = int(os.environ.get("PAGE_ENTRIES", "8"))
MULTIBOT = os.environ.get("MULTIBOT", False) == 'true'
CURRENCY = Currency(os.environ.get("CURRENCY", "USD"))
KRYPTO_EXPRESS_API_KEY = os.environ.get("KRYPTO_EXPRESS_API_KEY")
KRYPTO_EXPRESS_API_URL = os.environ.get("KRYPTO_EXPRESS_API_URL")
KRYPTO_EXPRESS_API_SECRET = os.environ.get("KRYPTO_EXPRESS_API_SECRET")
WEBHOOK_SECRET_TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD")
TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL")
# Supported: direct, http_proxy, cloudflare_worker. Preserve the legacy
# proxy setting when TELEGRAM_API_MODE has not been explicitly configured.
TELEGRAM_API_MODE = (
    os.environ.get("TELEGRAM_API_MODE")
    or ("http_proxy" if TELEGRAM_PROXY_URL else "direct")
).strip().lower()
# This is a Worker *origin* (custom domain or workers.dev), not Telegram's host.
TELEGRAM_WORKER_URL = os.environ.get("TELEGRAM_WORKER_URL", "").strip()
# Independent Worker authentication; never use the bot token as relay key.
TELEGRAM_WORKER_SECRET = os.environ.get("TELEGRAM_WORKER_SECRET", "")
# VARIABLES FOR CRYPTO FORWARDING
CRYPTO_FORWARDING_MODE = os.environ.get("CRYPTO_FORWARDING_MODE", False) == 'true'
BTC_FORWARDING_ADDRESS = os.environ.get("BTC_FORWARDING_ADDRESS")
LTC_FORWARDING_ADDRESS = os.environ.get("LTC_FORWARDING_ADDRESS")
ETH_FORWARDING_ADDRESS = os.environ.get("ETH_FORWARDING_ADDRESS")
SOL_FORWARDING_ADDRESS = os.environ.get("SOL_FORWARDING_ADDRESS")
BNB_FORWARDING_ADDRESS = os.environ.get("BNB_FORWARDING_ADDRESS")
DOGE_FORWARDING_ADDRESS = os.environ.get("DOGE_FORWARDING_ADDRESS")
# VARIABLES FOR THE REFERRAL SYSTEM
MIN_REFERRER_TOTAL_DEPOSIT = int(os.environ.get("MIN_REFERRER_TOTAL_DEPOSIT", "500"))
REFERRAL_BONUS_PERCENT = float(os.environ.get("REFERRAL_BONUS_PERCENT", "5"))
REFERRAL_BONUS_DEPOSIT_LIMIT = int(os.environ.get("REFERRAL_BONUS_DEPOSIT_LIMIT", "3"))
REFERRER_BONUS_PERCENT = float(os.environ.get("REFERRER_BONUS_PERCENT", "3"))
REFERRER_BONUS_DEPOSIT_LIMIT = int(os.environ.get("REFERRER_BONUS_DEPOSIT_LIMIT", "5"))
REFERRAL_BONUS_CAP_PERCENT = float(os.environ.get("REFERRAL_BONUS_CAP_PERCENT", "7"))
REFERRER_BONUS_CAP_PERCENT = float(os.environ.get("REFERRER_BONUS_CAP_PERCENT", "7"))
TOTAL_BONUS_CAP_PERCENT = float(os.environ.get("TOTAL_BONUS_CAP_PERCENT", "12"))
# SQLADMIN
# Shared SQLAdmin passwords are retired. Accounts are provisioned with
# scripts/manage_shop_staff.py and stored as strong Argon2 password hashes.
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "30"))
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")

# The SQLAdmin authentication secret must be persistent and private.
if not JWT_SECRET_KEY or len(JWT_SECRET_KEY) < 32:
    raise ValueError("JWT_SECRET_KEY must be a random 32+ character secret.")

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
