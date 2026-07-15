#!/usr/bin/env python3
"""Create the first admin user (one-shot CLI)."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

# Allow running as `python scripts/create_admin.py` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run(email: str, password: str, full_name: str | None) -> int:
    from app.db.base import auto_create_tables_async
    from app.db.connection import session_scope
    from app.db.migrations import apply_migrations_async
    from app.core.exceptions import ValidationError
    from app.services.bootstrap import create_initial_admin, has_admin_user
    from pydantic import ValidationError as PydanticValidationError

    await auto_create_tables_async()
    await apply_migrations_async()

    async with session_scope() as session:
        if await has_admin_user(session):
            print("An admin user already exists — nothing to do.")
            return 0
        try:
            user = await create_initial_admin(
                session,
                email=email,
                password=password,
                full_name=full_name,
            )
            created_email = user.email
            created_id = user.id
        except ValidationError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
        except PydanticValidationError as exc:
            for err in exc.errors():
                print(f"Error: {err.get('msg', err)}", file=sys.stderr)
            return 1

    print(f"Admin user created: {created_email} (id={created_id})")
    print("If the server is running, restart it or complete setup via the web UI at /setup.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first Oshkelosh admin user")
    parser.add_argument("--email", default=None, help="Admin email")
    parser.add_argument("--password", default=None, help="Admin password")
    parser.add_argument("--full-name", default=None, help="Optional display name")
    args = parser.parse_args()

    email = args.email or input("Admin email: ").strip()
    if not email:
        print("Email is required.", file=sys.stderr)
        return 1

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1

    return asyncio.run(_run(email, password, args.full_name))


if __name__ == "__main__":
    sys.exit(main())
