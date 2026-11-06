"""Prepare separate, provider-free Layer 4 QA secrets exactly once."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.beta_qa_environment import prepare_environment


def prepare() -> Path:
    """Generate test-only signing keys without reading any deployment secret."""
    path = Path(".codespaces/mcp-qa.env")
    existed = path.exists()
    prepare_environment(path)
    if existed:
        values = dict(
            line.split("=", 1) for line in path.read_text().splitlines()
        )
        if values.get("SHOP_MCP_QA") != "1":
            raise RuntimeError("Existing environment is not the MCP lab.")
        return path
    values = dict(line.split("=", 1) for line in path.read_text().splitlines())
    public = {}
    for purpose in ("delegation", "approval"):
        key = Ed25519PrivateKey.generate()
        values["MCP_QA_" + purpose.upper() + "_PRIVATE_KEY"] = (
            base64.b64encode(
                key.private_bytes(
                    serialization.Encoding.DER,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            ).decode()
        )
        public[purpose] = {
            "qa-" + purpose: base64.urlsafe_b64encode(
                key.public_key().public_bytes_raw()
            )
            .decode()
            .rstrip("=")
        }
    values.update(
        {
            "SHOP_MCP_QA": "1",
            "SHOP_MCP_ENABLED": "true",
            "SHOP_MCP_GATEWAY_ISSUER": "https://wpmcp.qa.invalid",
            "SHOP_MCP_INSTALLATION_ID": str(uuid4()),
            "SHOP_MCP_GATEWAY_KEYS_JSON": json.dumps(
                public, separators=(",", ":")
            ),
            "SHOP_FASTAPI_INTERNAL_URL": "http://127.0.0.1:8095",
        }
    )
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items())
    )
    path.chmod(0o600)
    return path


if __name__ == "__main__":
    prepare()
    print("PASS  Dedicated MCP QA environment; no provider credentials.")
