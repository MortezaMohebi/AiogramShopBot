"""Export the closed bot catalog for WPMCP's official SDK."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# This is a repository developer command, never a model-callable file writer.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.shop_mcp.catalog import tool_catalog  # noqa: E402
from services.shop_mcp.discovery import PROMPTS, RESOURCES  # noqa: E402


def main() -> None:
    """Write a versioned catalog without credentials or ORM data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    contract = {
        "version": 1,
        "provider": "bot_workflows",
        "tools": tool_catalog(),
        "resources": [
            {
                "name": key,
                "description": value[0],
                "required_scopes": [value[1]],
            }
            for key, value in RESOURCES.items()
        ],
        "prompts": [
            {
                "name": key,
                "description": value,
                "required_scopes": ["workflow:read"],
            }
            for key, value in PROMPTS.items()
        ],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
