import uuid
import aiosqlite
import logging
from datetime import datetime, timezone
from auth.session import hash_password, verify_password, revoke_all_sessions
from config import DATABASE_PATH

logger = logging.getLogger("reef_ai_hub.auth.manager")


class AuthManager:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path

    async def _row_factory(self, db):
        db.row_factory = aiosqlite.Row

    async def create_user(self, username: str, password: str, auth_type: str = "password") -> dict:
        """Create a new API user. Returns the created user (without password hash)."""
        pw_hash, salt = hash_password(password)
        now = datetime.now(timezone.utc).isoformat()
        user_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            await db.execute(
                """INSERT INTO api_users
                (user_id, username, password_hash, salt, auth_type, enabled, created_at, updated_at, last_login)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, pw_hash, salt, auth_type, 1, now, now, None),
            )
            await db.commit()
        return await self.get_user_by_username(username)

    async def get_user_by_username(self, username: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT * FROM api_users WHERE username = ?",
                (username,),
            )
            row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_user(self, user_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT * FROM api_users WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def list_users(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT user_id, username, auth_type, enabled, created_at, updated_at, last_login FROM api_users"
            )
            rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def _get_auth_data(self, username: str) -> dict | None:
        """Fetch user row with password_hash and salt for authentication."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._row_factory(db)
            cursor = await db.execute(
                "SELECT user_id, username, password_hash, salt, auth_type, enabled FROM api_users WHERE username = ?",
                (username,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def authenticate(self, username: str, password: str) -> dict | None:
        """Authenticate with username + password. Returns user dict or None."""
        user = await self._get_auth_data(username)
        if not user:
            return None
        if not user.get("enabled"):
            return None
        if user.get("auth_type") != "password":
            return None
        if not verify_password(password, user["password_hash"], user["salt"]):
            return None
        # Update last_login
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE api_users SET last_login = ? WHERE user_id = ?",
                (now, user["user_id"]),
            )
            await db.commit()
        user["last_login"] = now
        # Return safe dict (strip password material)
        user.pop("password_hash", None)
        user.pop("salt", None)
        return user

    async def update_password(self, user_id: str, new_password: str) -> None:
        """Update a user's password."""
        pw_hash, salt = hash_password(new_password)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE api_users SET password_hash = ?, salt = ?, updated_at = ? WHERE user_id = ?",
                (pw_hash, salt, now, user_id),
            )
            await db.commit()

    async def disable_user(self, user_id: str) -> None:
        """Disable a user (soft delete)."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE api_users SET enabled = 0, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            await db.commit()

    async def enable_user(self, user_id: str) -> None:
        """Re-enable a user."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE api_users SET enabled = 1, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            await db.commit()

    async def delete_user(self, user_id: str) -> None:
        """Delete a user entirely."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM api_users WHERE user_id = ?", (user_id,))
            await db.commit()

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        # Never expose password hash or salt
        d.pop("password_hash", None)
        d.pop("salt", None)
        return d
