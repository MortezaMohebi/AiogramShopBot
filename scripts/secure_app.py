"""ASGI entrypoint preserving all existing Telegram and Bale business handlers."""
import config
from bot import app as legacy_app, dp
from run import main_router
from dashboard.admin_control_app import create_app

if config.MULTIBOT:
    raise RuntimeError("The controlled Codespaces runtime uses one bot per platform")
# run.py includes the main router only when invoked as __main__.
if main_router not in dp.sub_routers:
    dp.include_router(main_router)
app = create_app(legacy_app, live_receivers=True)
