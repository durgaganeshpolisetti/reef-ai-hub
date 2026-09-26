import aiosqlite
import logging
from pathlib import Path
from config import DATABASE_PATH

logger = logging.getLogger("reef_ai_hub.database")

SCHEMA_VERSION = 1

CREATE_DEVICES = """
CREATE TABLE IF NOT EXISTS devices (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    device_type          TEXT NOT NULL,
    brand                TEXT NOT NULL,
    model                TEXT,
    integration          TEXT NOT NULL,
    enabled              INTEGER NOT NULL DEFAULT 1,
    poll_interval_seconds INTEGER NOT NULL DEFAULT 300,
    status               TEXT NOT NULL DEFAULT 'configured',
    config               TEXT NOT NULL DEFAULT '{}',
    credential_ref       TEXT,
    last_poll_attempt    TEXT,
    last_poll_success    TEXT,
    last_poll_failure    TEXT,
    next_scheduled_poll  TEXT,
    last_error           TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
"""

CREATE_DEVICE_CREDENTIALS = """
CREATE TABLE IF NOT EXISTS device_credentials (
    credential_ref       TEXT PRIMARY KEY,
    device_id            TEXT NOT NULL REFERENCES devices(id),
    credential_type      TEXT NOT NULL,
    configured           INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    last_tested_at       TEXT,
    last_test_result     TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
);
"""

CREATE_API_USERS = """
CREATE TABLE IF NOT EXISTS api_users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    auth_type     TEXT NOT NULL DEFAULT 'password',
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_login    TEXT
);
"""

CREATE_TELEMETRY = """
CREATE TABLE IF NOT EXISTS telemetry (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id        TEXT NOT NULL,
    parameter_name   TEXT NOT NULL,
    value            REAL NOT NULL,
    unit             TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    status           TEXT NOT NULL,
    source           TEXT NOT NULL,
    raw              TEXT
);
"""

CREATE_ALERTS = """
CREATE TABLE IF NOT EXISTS alerts (
    id             TEXT PRIMARY KEY,
    severity       TEXT NOT NULL,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    read           INTEGER NOT NULL DEFAULT 0,
    timestamp      TEXT NOT NULL,
    device_id      TEXT,
    equipment_id   TEXT
);
"""

CREATE_COMMANDS = """
CREATE TABLE IF NOT EXISTS commands (
    id           TEXT PRIMARY KEY,
    device_id    TEXT NOT NULL,
    equipment_id TEXT,
    command      TEXT NOT NULL,
    params       TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'pending',
    result       TEXT,
    error        TEXT,
    timestamp    TEXT NOT NULL
);
"""

CREATE_EQUIPMENT = """
CREATE TABLE IF NOT EXISTS equipment (
    id              TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL,
    name            TEXT NOT NULL,
    equipment_type  TEXT NOT NULL,
    location        TEXT NOT NULL DEFAULT '',
    current_state   TEXT NOT NULL DEFAULT '{}',
    desired_state   TEXT NOT NULL DEFAULT '{}',
    manual_override INTEGER NOT NULL DEFAULT 0,
    last_change     TEXT NOT NULL
);
"""

CREATE_CONNECTION_HISTORY = """
CREATE TABLE IF NOT EXISTS connection_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id      TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    success        INTEGER NOT NULL,
    error_type     TEXT,
    error_message  TEXT
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_telemetry_device_param ON telemetry(device_id, parameter_name, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_read ON alerts(read);",
    "CREATE INDEX IF NOT EXISTS idx_connection_history_device ON connection_history(device_id, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_api_users_username ON api_users(username);",
]


async def init_database(db_path: str | None = None):
    db_path = db_path or DATABASE_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        for stmt in [
            CREATE_DEVICES, CREATE_DEVICE_CREDENTIALS, CREATE_API_USERS,
            CREATE_TELEMETRY, CREATE_ALERTS, CREATE_COMMANDS, CREATE_EQUIPMENT,
            CREATE_CONNECTION_HISTORY,
        ]:
            await db.execute(stmt)
        for idx in CREATE_INDEXES:
            await db.execute(idx)
        await db.commit()
    logger.info("Database initialized at %s", db_path)
