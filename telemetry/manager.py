import uuid
import json
import aiosqlite
import logging
from datetime import datetime, timezone

logger = logging.getLogger("reef_ai_hub.telemetry")


class TelemetryManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def _row_factory(self, db):
        db.row_factory = aiosqlite.Row

    async def insert(self, data: dict) -> dict:
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            await db.execute(
                """INSERT INTO telemetry
                (id, device_id, parameter_name, value, unit, timestamp, status, source, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id,
                    data["device_id"],
                    data["parameter_name"],
                    data["value"],
                    data["unit"],
                    data.get("timestamp") or now,
                    data.get("status", "normal"),
                    data.get("source", "sensor"),
                    json.dumps(data.get("raw", {})),
                ),
            )
            await db.commit()
        return {"id": entry_id, "timestamp": now}

    async def list(self, device_id: str, parameter: str | None = None, limit: int = 100) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            if parameter:
                cursor = await db.execute(
                    "SELECT * FROM telemetry WHERE device_id = ? AND parameter_name = ? ORDER BY timestamp DESC LIMIT ?",
                    (device_id, parameter, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM telemetry WHERE device_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (device_id, limit),
                )
            rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def latest(self, device_id: str, parameter: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT * FROM telemetry WHERE device_id = ? AND parameter_name = ? ORDER BY timestamp DESC LIMIT 1",
                (device_id, parameter),
            )
            row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        d["raw"] = json.loads(d.get("raw") or "{}")
        return d
