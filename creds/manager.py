import uuid
import aiosqlite
import json
import logging
from datetime import datetime, timezone
from creds.vault import vault

logger = logging.getLogger("reef_ai_hub.creds.manager")


class CredentialManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def _row_factory(self, db):
        db.row_factory = aiosqlite.Row

    async def get_metadata(self, device_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT * FROM device_credentials WHERE device_id = ?",
                (device_id,),
            )
            row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def create(self, device_id: str, credential_type: str) -> dict:
        credential_ref = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            await db.execute(
                """INSERT INTO device_credentials
                (credential_ref, device_id, credential_type, configured,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (credential_ref, device_id, credential_type, 0, now, now),
            )
            await db.commit()
        return await self.get_metadata_by_ref(credential_ref)

    async def store_secrets(self, credential_ref: str, secrets: dict) -> None:
        vault.store(credential_ref, secrets)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO device_credentials
                (credential_ref, credential_type, configured, created_at, updated_at)
                VALUES (?, 'password', 0, ?, ?)""",
                (credential_ref, now, now),
            )
            await db.execute(
                "UPDATE device_credentials SET configured = 1, updated_at = ? WHERE credential_ref = ?",
                (now, credential_ref),
            )
            await db.commit()

    async def get_secrets(self, credential_ref: str) -> dict | None:
        return vault.retrieve(credential_ref)

    async def mark_tested(self, credential_ref: str, success: bool, result: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO device_credentials
                (credential_ref, credential_type, configured, created_at, updated_at)
                VALUES (?, 'password', 0, ?, ?)""",
                (credential_ref, now, now),
            )
            await db.execute(
                "UPDATE device_credentials SET last_tested_at = ?, last_test_result = ?, updated_at = ? WHERE credential_ref = ?",
                (now, result, now, credential_ref),
            )
            await db.commit()

    async def delete(self, credential_ref: str) -> None:
        vault.delete(credential_ref)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM device_credentials WHERE credential_ref = ?",
                (credential_ref,),
            )
            await db.commit()

    async def get_metadata_by_ref(self, credential_ref: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT * FROM device_credentials WHERE credential_ref = ?",
                (credential_ref,),
            )
            row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    def _row_to_dict(self, row) -> dict:
        if hasattr(row, "keys"):
            return dict(row)
        return row
