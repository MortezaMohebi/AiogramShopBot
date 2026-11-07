"""Inspect or change deployment service choices from a private server shell."""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from db import create_db_and_tables, session_maker
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_service_controls as controls


async def main(args: argparse.Namespace) -> None:
    """Use the same validation, revision guard and audit trail as the dashboard."""
    await create_db_and_tables()
    async with session_maker() as db:
        if args.command == "list":
            print(json.dumps(await db.run_sync(controls.describe_controls), indent=2))
            return
        actor = await db.scalar(select(ShopStaff).where(
            ShopStaff.username == args.actor,
            ShopStaff.is_active.is_(True),
        ))
        if not actor or not security.has_permission(actor.role, "settings.manage"):
            raise SystemExit("Supply the username of an active administrator.")
        result = await db.run_sync(lambda session: controls.write_override(
            session, key=args.service, enabled={
                "enable": True, "disable": False, "default": None,
            }[args.choice], expected_version=args.version, actor_id=actor.id,
        ))
        await db.commit()
        print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    update = commands.add_parser("set")
    update.add_argument("service", choices=tuple(controls.FLAGS))
    update.add_argument("choice", choices=("enable", "disable", "default"))
    update.add_argument("--actor", required=True)
    update.add_argument("--version", type=int, required=True)
    try:
        asyncio.run(main(parser.parse_args()))
    except security.SecurityRejected as exc:
        raise SystemExit(exc.code) from None
