"""One-time migration: strip access_token from device config JSONs.

Usage:
    python scripts/migrate_remove_tokens.py
    python scripts/migrate_remove_tokens.py --db-path /path/to/reef_ai.db
"""

import argparse
import asyncio
import logging

from config import DATABASE_PATH
from database.connection import migrate_remove_access_tokens

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate_tokens")


async def main():
    parser = argparse.ArgumentParser(description="Remove access_token from device configs")
    parser.add_argument("--db-path", default=DATABASE_PATH, help="Path to SQLite database")
    args = parser.parse_args()

    count = await migrate_remove_access_tokens(args.db_path)
    if count:
        print(f"Migration complete: {count} device(s) updated.")
    else:
        print("Migration complete: no devices had access_token in config.")


if __name__ == "__main__":
    asyncio.run(main())
