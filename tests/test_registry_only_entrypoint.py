"""Verify the Registry-only ASGI surface without live providers."""
import asyncio
import importlib
from httpx import ASGITransport, AsyncClient


def test_registry_entrypoint_has_no_environment_bot_receivers(monkeypatch):
    module = importlib.import_module("scripts.secure_app")
    async def verified_schema():
        pass
    monkeypatch.setattr(module, "create_db_and_tables", verified_schema)
    monkeypatch.setattr(module.config, "MULTIBOT_V2_RUNTIME_ENABLED", False)
    monkeypatch.setattr(module.config, "NEXT_ADMIN_BRIDGE_ENABLED", True)
    monkeypatch.setattr(module.config, "NEXT_ADMIN_BRIDGE_SECRET", "test-only-bridge-secret-" * 3)
    async def probe():
        async with module.lifespan(module.base):
            async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
                for path in ("/hooks/telegram", "/webhooks/bale/old", "/admin"):
                    assert (await client.post(path, json={})).status_code == 404
                assert (await client.get("/internal/admin/v1/bot-registry")).status_code == 401
                assert module.app.state is module.base.state
    asyncio.run(probe())
