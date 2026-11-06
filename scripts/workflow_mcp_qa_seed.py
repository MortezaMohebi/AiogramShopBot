"""Add disposable Native consent fixtures to the dedicated MCP PostgreSQL lab."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_MCP_QA") != "1" or not __debug__:
    raise RuntimeError("Dedicated MCP QA mode is required.")

from db import engine, session_maker
from scripts.beta_storefront_e2e import seed
from services.shop_mcp.contracts import Delegation
from services.shop_mcp.grants import prepare_pairing


async def main() -> None:
    """Seed synthetic Stores and one pending consent, never approve an effect."""
    fixture = await seed()
    instant = int(time.time())
    identity = {
        "v": 1,
        "iss": os.environ["SHOP_MCP_GATEWAY_ISSUER"],
        "aud": "urn:bot-workflows:" + os.environ["SHOP_MCP_INSTALLATION_ID"],
        "sub": "mcp-qa-requester",
        "client_id": "mcp-qa-client",
        "tenant_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "connection_id": str(uuid4()),
        "grant_id": str(uuid4()),
        "grant_version": 1,
        "scopes": ["workflow:read"],
        "method": "POST",
        "target": "/internal/mcp/v1/pairings/prepare",
        "body_sha256": "0" * 64,
        "iat": instant,
        "exp": instant + 45,
        "jti": str(uuid4()),
        "correlation_id": str(uuid4()),
    }
    async with session_maker() as db:
        pending = await prepare_pairing(
            db,
            delegation=Delegation.model_validate(identity),
            store_ids=[fixture["stores"][0]],
            scopes=identity["scopes"],
        )
    Path("/qa/workflow-mcp-fixture.json").write_text(
        json.dumps(
            {
                "store_id": fixture["stores"][0],
                "foreign_store_id": fixture["stores"][1],
                "admin_id": fixture["admin_id"],
                "pairing_id": pending["id"],
                "bots": fixture["bots"],
                "products": fixture["products"],
            }
        )
    )
    await engine.dispose()
    print("PASS  Synthetic MCP consent fixture; no business approval.")


if __name__ == "__main__":
    asyncio.run(main())
