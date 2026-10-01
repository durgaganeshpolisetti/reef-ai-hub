import uuid
import aiosqlite
import logging
from datetime import datetime, timezone
from config import DATABASE_PATH

logger = logging.getLogger("reef_ai_hub.aquawiz.data")


class AquaWizDataManager:
    """Persist normalized AquaWiz readings to aquawiz_data."""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path

    async def store(self, device_id: str, serial: str, readings: list[dict]) -> int:
        """Insert one row per reading type per poll.

        Returns the number of rows inserted.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for r in readings:
            rows.append((
                device_id,
                serial,
                r.get("timestamp") or now,
                r.get("kh"),
                r.get("ph"),
                r.get("kh_dosing"),
                r.get("kh_target"),
                r.get("delta_kh"),
                r.get("co2_bubbles"),
                now,
            ))

        if not rows:
            return 0

        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                """INSERT INTO aquawiz_data
                (device_id, serial, reading_time, kh, ph, kh_dosing,
                 kh_target, delta_kh, co2_bubbles, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            await db.commit()
        logger.debug("Stored %d aquawiz_data rows for %s", len(rows), device_id)
        return len(rows)

    async def latest(self, device_id: str) -> dict | None:
        """Return the most recent reading row for a device."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM aquawiz_data
                WHERE device_id = ?
                ORDER BY reading_time DESC LIMIT 1""",
                (device_id,),
            )
            row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def history(self, device_id: str, limit: int = 100) -> list[dict]:
        """Return recent reading rows for a device, newest first."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM aquawiz_data
                WHERE device_id = ?
                ORDER BY reading_time DESC LIMIT ?""",
                (device_id, limit),
            )
            rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        return d
