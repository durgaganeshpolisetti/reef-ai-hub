import uuid
import json
import aiosqlite
import logging
from datetime import datetime, timezone

logger = logging.getLogger("reef_ai_hub.devices")


class DeviceNotFoundError(Exception):
    pass


class DeviceManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def _row_factory(self, db):
        db.row_factory = aiosqlite.Row

    async def list_devices(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute("SELECT * FROM devices ORDER BY created_at DESC")
            rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def get_device(self, device_id: str) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            row = await cursor.fetchone()
        if row is None:
            raise DeviceNotFoundError(f"Device {device_id} not found")
        return self._row_to_dict(row)

    async def create_device(self, data: dict) -> dict:
        device_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        config = json.dumps(data.get("config", {}))
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            await db.execute(
                """INSERT INTO devices
                (id, name, device_type, brand, model, integration, enabled,
                 poll_interval_seconds, status, config, credential_ref,
                 last_poll_attempt, last_poll_success, last_poll_failure,
                 next_scheduled_poll, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    device_id,
                    data["name"],
                    data["device_type"],
                    data["brand"],
                    data.get("model"),
                    data["integration"],
                    1,
                    data.get("poll_interval_seconds", 300),
                    "configured",
                    config,
                    None,
                    None, None, None, None, None,
                    now, now,
                ),
            )
            await db.commit()
        return await self.get_device(device_id)

    async def update_device(self, device_id: str, data: dict) -> dict:
        await self.get_device(device_id)  # verify exists
        now = datetime.now(timezone.utc).isoformat()
        updates = {"updated_at": now}
        for key in ["name", "device_type", "brand", "model", "integration", "enabled", "status", "last_error", "credential_ref"]:
            if data.get(key) is not None:
                updates[key] = data[key]
        if data.get("poll_interval_seconds") is not None:
            updates["poll_interval_seconds"] = data["poll_interval_seconds"]
        if data.get("config") is not None:
            updates["config"] = json.dumps(data["config"])
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [device_id]
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            await db.execute(f"UPDATE devices SET {set_clause} WHERE id = ?", values)
            await db.commit()
        return await self.get_device(device_id)

    async def find_by_integration(self, integration: str, serial: str) -> dict | None:
        """Find an existing device by integration type + serial in config."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT * FROM devices WHERE integration = ? AND config LIKE ?",
                (integration, f'%"{serial}"%'),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        d = self._row_to_dict(row)
        # Verify the serial actually matches (config is JSON)
        if (d.get("config", {}).get("serial") or "").upper() == serial.upper():
            return d
        return None

    async def delete_device(self, device_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            await db.commit()
        if cursor.rowcount == 0:
            raise DeviceNotFoundError(f"Device {device_id} not found")

    async def record_connection(self, device_id: str, success: bool,
                                error_type: str | None = None, error_message: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            await db.execute(
                "INSERT INTO connection_history (device_id, timestamp, success, error_type, error_message) VALUES (?, ?, ?, ?, ?)",
                (device_id, now, 1 if success else 0, error_type, error_message),
            )
            update_fields = {"updated_at": now}
            if success:
                update_fields.update({
                    "status": "connected",
                    "last_poll_success": now,
                    "last_poll_attempt": now,
                    "last_poll_failure": None,
                    "last_error": None,
                })
            else:
                update_fields.update({
                    "status": "error",
                    "last_poll_failure": now,
                    "last_poll_attempt": now,
                    "last_error": error_message or "Connection failed",
                })
            set_clause = ", ".join(f"{k} = ?" for k in update_fields)
            values = list(update_fields.values()) + [device_id]
            await db.execute(f"UPDATE devices SET {set_clause} WHERE id = ?", values)
            await db.commit()

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        d["config"] = json.loads(d.get("config") or "{}")
        return d
