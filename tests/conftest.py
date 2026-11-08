import importlib
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


sys.path = [
    path for path in sys.path
    if "AiogramShopBot\\Lib" not in path and "AiogramShopBot/Lib" not in path
]


def _build_config_module() -> ModuleType:
    config = ModuleType("config")
    config.WEBAPP_HOST = "127.0.0.1"
    config.WEBAPP_PORT = 5000
    config.TELEGRAM_PROXY_URL = None
    config.REDIS_HOST = "localhost"
    config.REDIS_PASSWORD = "password"
    config.DB_USER = "postgres"
    config.DB_PASS = "postgres"
    config.DB_HOST = "localhost"
    config.DB_PORT = 5432
    config.DB_NAME = "test"
    # Match deployment defaults while keeping every provider and worker inert.
    config.SHOP_WORKFLOW_RUNTIME_ENABLED = False
    config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH = False
    config.MULTIBOT_V2_RUNTIME_ENABLED = False
    config.SHOP_RELAY_POOL_ENABLED = False
    config.TELEGRAM_API_MODE = "direct"
    config.TELEGRAM_WORKER_URL = ""
    config.TELEGRAM_WORKER_SECRET = ""
    config.TELEGRAM_FIAT_CHECKOUT_ENABLED = False
    config.TELEGRAM_FIAT_PROVIDER_TOKEN = ""
    config.TELEGRAM_IRR_MINOR_MULTIPLIER = 0
    config.TELEGRAM_STARS_CHECKOUT_ENABLED = False
    config.TELEGRAM_STARS_REFUNDS_ENABLED = False
    config.BALE_WALLET_PROVIDER_TOKEN = ""
    config.BALE_WALLET_CHECKOUT_ENABLED = False
    config.BALE_BROADCAST_MODE = "standard"
    config.BALE_BROADCAST_PAID_ENABLED = False
    config.BALE_BROADCAST_PREPARE_CHAT_ID = 0
    config.SHOP_CAMPAIGN_DISPATCH_ENABLED = False
    config.SHOP_BROADCAST_WORKER_ENABLED = False
    config.SHOP_BROADCAST_TELEGRAM_MPS = 5
    config.SHOP_BROADCAST_BALE_STANDARD_MPS = 1
    config.SHOP_BROADCAST_BALE_BUSINESS_MPS = 5
    config.SHOP_BROADCAST_MAX_PAID_CALLS = 0
    config.SHOP_BROADCAST_POLL_SECONDS = 2
    config.SHOP_BROADCAST_STALE_SECONDS = 900
    config.SHOP_MEDIA_ROOT = "./media_data"
    config.SHOP_MEDIA_MAX_BYTES = 50_000_000
    config.SHOP_DIGITAL_ROOT = ""
    config.SHOP_DIGITAL_DELIVERY_ENABLED = False
    config.SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR = 0
    config.SHOP_ADMIN_SECURE_COOKIES = True
    config.NEXT_ADMIN_BRIDGE_ENABLED = False
    config.NEXT_ADMIN_BRIDGE_SECRET = ""
    config.DB_SQL_ECHO = False
    return config


sys.modules.setdefault("config", _build_config_module())

passlib_module = ModuleType("passlib")
passlib_context_module = ModuleType("passlib.context")


class _CryptContext:
    def __init__(self, *args, **kwargs):
        pass

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        return plain_password == hashed_password

    def hash(self, plain_password: str) -> str:
        return f"hashed:{plain_password}"


passlib_context_module.CryptContext = _CryptContext
passlib_module.context = passlib_context_module
sys.modules.setdefault("passlib", passlib_module)
sys.modules.setdefault("passlib.context", passlib_context_module)

redis_module = ModuleType("redis")
redis_asyncio_module = ModuleType("redis.asyncio")
redis_exceptions_module = ModuleType("redis.exceptions")


class RedisError(Exception):
    """Mirror the real Redis infrastructure exception in offline tests."""


redis_exceptions_module.RedisError = RedisError


class _Redis:
    def __init__(self, *args, **kwargs):
        pass

    async def close(self):
        return None


redis_asyncio_module.Redis = _Redis
redis_module.asyncio = redis_asyncio_module
sys.modules.setdefault("redis", redis_module)
sys.modules.setdefault("redis.asyncio", redis_asyncio_module)
sys.modules.setdefault("redis.exceptions", redis_exceptions_module)

db_module = ModuleType("db")


async def _noop_async(*args, **kwargs):
    return None


db_module.session_execute = _noop_async
db_module.session_flush = _noop_async
db_module.session_commit = _noop_async
db_module.get_db_session = _noop_async
db_module.create_db_and_tables = _noop_async
# Offline endpoint unit tests import the signed admin bridge without a real DB.
db_module.session_maker = lambda: None
sys.modules.setdefault("db", db_module)


def pytest_configure():
    """Register the complete ORM as db.py does, without opening a database.

    Full-suite collection imports the modern models in different orders.
    SQLAlchemy resolves every relationship together at first use, so a partial
    registry can poison otherwise unrelated tests with missing mapper names.
    """
    for model_file in sorted((PROJECT_ROOT / "models").glob("*.py")):
        if not model_file.name.startswith("_"):
            importlib.import_module(f"models.{model_file.stem}")
