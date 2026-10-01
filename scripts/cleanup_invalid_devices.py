"""One-time cleanup: remove placeholder devices with name='string'.

These devices were created during early development and have no real data.

Usage:
    python scripts/cleanup_invalid_devices.py
    python scripts/cleanup_invalid_devices.py --db-path /path/to/reef_ai.db
"""

import argparse
import asyncio
import json
import logging

import aiosqlite

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanup_devices")

PLACEHOLDER_NAME = "string"
PLACEHOLDER_BRAND = "string"
PLACEHOLDER_INTEGRATION = "string"


async def main():
    parser = argparse.ArgumentParser(description="Remove invalid placeholder devices")
    parser.add_argument("--db-path", default="data/reef_ai.db", help="Path to SQLite database")
    args = parser.parse_args()

    async with aiosqlite.connect(args.db_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT id, name, brand, integration, credential_ref, config FROM devices "
            "WHERE name = ? AND brand = ? AND integration = ?",
            (PLACEHOLDER_NAME, PLACEHOLDER_BRAND, PLACEHOLDER_INTEGRATION),
        )
        rows = await cursor.fetchall()

        if not rows:
            print("No placeholder devices found. Nothing to do.")
            return

        print(f"Found {len(rows)} placeholder device(s):")
        for row in rows:
            config = json.loads(row["config"]) if row["config"] else {}
            print(f"  - id={row['id']} name={row['name']} brand={row['brand']} "
                  f"integration={row['integration']} credential_ref={row['credential_ref']}")
            print(f"    config={json.dumps(config)}")

        confirm = input("\nDelete these devices? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return

        for row in rows:
            await db.execute("DELETE FROM devices WHERE id = ?", (row["id"],))
            print(f"Deleted device {row['id']}")

        await db.commit()
        print(f"\nDone. {len(rows)} device(s) removed.")


if __name__ == "__main__":
    asyncio.run(main())
