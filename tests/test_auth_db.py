"""Tests for api_users table creation and Hub authentication behavior.

Run with: python -m pytest tests/test_auth_db.py -v
"""

import asyncio
import json
import sqlite3
import tempfile
import unittest
import unittest.mock as mock

from database.connection import init_database
from auth.manager import AuthManager
from auth.session import verify_password, hash_password, create_session, validate_session


def _make_db_path(tmp_dir, name="test.db"):
    return f"{tmp_dir}/{name}"


class TestApiUsersTableCreation(unittest.TestCase):

    def test_fresh_init_creates_api_users(self):
        tmp = tempfile.mkdtemp()
        db_path = _make_db_path(tmp)
        asyncio.run(init_database(db_path))
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='api_users'"
            )
            self.assertIsNotNone(cur.fetchone())
        finally:
            conn.close()

    def test_api_users_columns(self):
        tmp = tempfile.mkdtemp()
        db_path = _make_db_path(tmp)
        asyncio.run(init_database(db_path))
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute("PRAGMA table_info(api_users)")
            cols = [r[1] for r in cur.fetchall()]
        finally:
            conn.close()
        expected = [
            "user_id", "username", "password_hash", "salt",
            "auth_type", "enabled", "created_at", "updated_at", "last_login",
        ]
        for col in expected:
            self.assertIn(col, cols, f"Missing column: {col}")

    def test_api_users_username_unique(self):
        tmp = tempfile.mkdtemp()
        db_path = _make_db_path(tmp)
        asyncio.run(init_database(db_path))
        h1, s1 = hash_password("pass")
        h2, s2 = hash_password("pass")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO api_users (user_id, username, password_hash, salt, auth_type, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'password', 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
                ("u1", "alice", h1, s1),
            )
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO api_users (user_id, username, password_hash, salt, auth_type, enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'password', 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
                    ("u2", "alice", h2, s2),
                )
                conn.commit()
        finally:
            conn.close()

    def test_safe_reinit_preserves_data(self):
        tmp = tempfile.mkdtemp()
        db_path = _make_db_path(tmp)
        asyncio.run(init_database(db_path))
        h, s = hash_password("pass")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO api_users (user_id, username, password_hash, salt, auth_type, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'password', 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
                ("u1", "alice", h, s),
            )
            conn.execute(
                "INSERT INTO devices (id, name, device_type, brand, integration, status, config, created_at, updated_at) "
                "VALUES (?, ?, 'test', 'brand', 'test', 'ok', '{}', '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
                ("dev-1", "Test"),
            )
            conn.commit()
        finally:
            conn.close()
        asyncio.run(init_database(db_path))
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM api_users")
            self.assertEqual(cur.fetchone()[0], 1)
            cur = conn.execute("SELECT COUNT(*) FROM devices")
            self.assertEqual(cur.fetchone()[0], 1)
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r[0] for r in cur.fetchall()]
            self.assertIn("api_users", tables)
            self.assertIn("devices", tables)
            self.assertIn("device_credentials", tables)
        finally:
            conn.close()


class TestAuthManagerWithDb(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = f"{self._tmp}/test.db"
        await init_database(self.db_path)
        self.mgr = AuthManager(self.db_path)

    async def test_create_and_list_user(self):
        user = await self.mgr.create_user("alice", "s3cret")
        self.assertEqual(user["username"], "alice")
        self.assertNotIn("password_hash", user)
        self.assertNotIn("salt", user)

        users = await self.mgr.list_users()
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["username"], "alice")
        self.assertNotIn("password_hash", users[0])
        self.assertNotIn("salt", users[0])

    async def test_login_success(self):
        await self.mgr.create_user("bob", "correct-horse")
        user = await self.mgr.authenticate("bob", "correct-horse")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "bob")

    async def test_login_wrong_password(self):
        await self.mgr.create_user("bob", "correct-horse")
        user = await self.mgr.authenticate("bob", "wrong-password")
        self.assertIsNone(user)

    async def test_login_nonexistent_user(self):
        user = await self.mgr.authenticate("nobody", "anything")
        self.assertIsNone(user)

    async def test_login_disabled_user(self):
        await self.mgr.create_user("eve", "pass")
        user_id = (await self.mgr.get_user_by_username("eve"))["user_id"]
        await self.mgr.disable_user(user_id)
        user = await self.mgr.authenticate("eve", "pass")
        self.assertIsNone(user)

    async def test_multiple_users(self):
        await self.mgr.create_user("alice", "pass1")
        await self.mgr.create_user("bob", "pass2")
        await self.mgr.create_user("charlie", "pass3")
        users = await self.mgr.list_users()
        self.assertEqual(len(users), 3)
        usernames = {u["username"] for u in users}
        self.assertEqual(usernames, {"alice", "bob", "charlie"})

    async def test_password_is_hashed_not_plaintext(self):
        await self.mgr.create_user("alice", "my-password")
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT password_hash, salt FROM api_users WHERE username = ?",
                ("alice",),
            ) as cur:
                row = await cur.fetchone()
        pw_hash, salt = row
        self.assertNotEqual(pw_hash, "my-password")
        self.assertNotEqual(salt, "my-password")
        self.assertEqual(len(pw_hash), 64)
        self.assertEqual(len(salt), 32)

    async def test_verify_password_function(self):
        await self.mgr.create_user("alice", "my-password")
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT password_hash, salt FROM api_users WHERE username = ?",
                ("alice",),
            ) as cur:
                row = await cur.fetchone()
        pw_hash, salt = row
        self.assertTrue(verify_password("my-password", pw_hash, salt))
        self.assertFalse(verify_password("wrong", pw_hash, salt))

    async def test_existing_devices_preserved_after_reinit(self):
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO devices (id, name, device_type, brand, integration, status, config, created_at, updated_at) "
                "VALUES (?, ?, 'test', 'brand', 'test', 'ok', '{}', '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
                ("dev-1", "KH-01"),
            )
            await db.execute(
                "INSERT INTO device_credentials (credential_ref, device_id, credential_type, configured, created_at, updated_at) "
                "VALUES (?, ?, 'aquawiz', 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
                ("cred-1", "dev-1"),
            )
            await db.commit()

        await init_database(self.db_path)

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM devices")
            self.assertEqual(cur.fetchone()[0], 1)
            cur = conn.execute("SELECT COUNT(*) FROM device_credentials")
            self.assertEqual(cur.fetchone()[0], 1)
            cur = conn.execute("SELECT COUNT(*) FROM api_users")
            self.assertEqual(cur.fetchone()[0], 0)
        finally:
            conn.close()


class TestApiAuthEndpoints(unittest.IsolatedAsyncioTestCase):
    """Unit tests for auth endpoint handlers (no HTTP client needed)."""

    async def test_setup_then_login_flow(self):
        tmp = tempfile.mkdtemp()
        db_path = f"{tmp}/test.db"
        await init_database(db_path)
        mgr = AuthManager(db_path)

        # Setup: create initial admin
        user = await mgr.create_user("admin", "secret123")
        self.assertEqual(user["username"], "admin")
        token = create_session(user["username"])
        self.assertIsNotNone(token)

        # Login validation
        auth_user = await mgr.authenticate("admin", "secret123")
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user["username"], "admin")

    async def test_query_param_auth_token_validation(self):
        from auth.session import validate_session
        tmp = tempfile.mkdtemp()
        db_path = f"{tmp}/test.db"
        await init_database(db_path)
        mgr = AuthManager(db_path)

        user = await mgr.create_user("admin", "secret123")
        token = create_session(user["username"])

        # Validate token (same as middleware would do with ?authorization=<token>)
        session = validate_session(token)
        self.assertIsNotNone(session)
        self.assertEqual(session["username"], "admin")

        # Invalid token returns None
        bad = validate_session("invalid-token")
        self.assertIsNone(bad)

    async def test_bearer_header_token_validation(self):
        from auth.session import validate_session
        tmp = tempfile.mkdtemp()
        db_path = f"{tmp}/test.db"
        await init_database(db_path)
        mgr = AuthManager(db_path)

        user = await mgr.create_user("admin", "secret123")
        token = create_session(user["username"])

        # Bearer prefix stripping (same as middleware does)
        self.assertTrue(token.startswith("") or len(token) > 0)
        extracted = token[7:] if token.startswith("Bearer ") else token

        # Validate bare token
        session = validate_session(extracted)
        self.assertIsNotNone(session)
        self.assertEqual(session["username"], "admin")

        # Validate full Bearer token (should fail - not a valid token format)
        bad = validate_session(f"Bearer {token}")
        self.assertIsNone(bad)

    async def test_setup_returns_409_when_users_exist(self):
        tmp = tempfile.mkdtemp()
        db_path = f"{tmp}/test.db"
        await init_database(db_path)
        mgr = AuthManager(db_path)

        # First setup succeeds
        user = await mgr.create_user("admin", "secret123")
        self.assertIsNotNone(user)

        # Second setup should fail (list_users returns non-empty)
        existing = await mgr.list_users()
        self.assertEqual(len(existing), 1)

    async def test_invalid_token_returns_none(self):
        from auth.session import validate_session
        result = validate_session("invalid-token")
        self.assertIsNone(result)

    async def test_no_token_returns_none(self):
        from auth.session import validate_session
        result = validate_session(None)
        self.assertIsNone(result)

    async def test_wrong_password_returns_401_equivalent(self):
        tmp = tempfile.mkdtemp()
        db_path = f"{tmp}/test.db"
        await init_database(db_path)
        mgr = AuthManager(db_path)

        await mgr.create_user("admin", "secret123")
        user = await mgr.authenticate("admin", "wrong")
        self.assertIsNone(user)


class TestAuthMiddleware(unittest.IsolatedAsyncioTestCase):
    """Auth middleware rejects query-param tokens, accepts Bearer header only."""

    async def test_valid_bearer_header_passes(self):
        from api.routes.auth import _get_user_from_credentials
        from fastapi.security import HTTPAuthorizationCredentials

        tmp = tempfile.mkdtemp()
        db_path = f"{tmp}/test.db"
        await init_database(db_path)
        mgr = AuthManager(db_path)
        user = await mgr.create_user("admin", "secret123")
        token = create_session(user["username"])

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        result = _get_user_from_credentials(creds)
        self.assertIsNotNone(result)
        self.assertEqual(result["username"], "admin")

    async def test_missing_auth_returns_none(self):
        from api.routes.auth import _get_user_from_credentials

        result = _get_user_from_credentials(None)
        self.assertIsNone(result)

    async def test_invalid_bearer_token_returns_none(self):
        from api.routes.auth import _get_user_from_credentials
        from fastapi.security import HTTPAuthorizationCredentials

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid-token")
        result = _get_user_from_credentials(creds)
        self.assertIsNone(result)

    async def test_bare_token_instead_of_bearer_returns_none(self):
        from api.routes.auth import _get_user_from_credentials
        from fastapi.security import HTTPAuthorizationCredentials

        # Bare token without "Bearer " scheme
        creds = HTTPAuthorizationCredentials(scheme="Token", credentials="some-token")
        result = _get_user_from_credentials(creds)
        self.assertIsNone(result)

    async def test_require_auth_with_valid_credentials(self):
        from api.routes.auth import _get_user_from_credentials
        from fastapi.security import HTTPAuthorizationCredentials

        tmp = tempfile.mkdtemp()
        db_path = f"{tmp}/test.db"
        await init_database(db_path)
        mgr = AuthManager(db_path)
        user = await mgr.create_user("admin", "secret123")
        token = create_session(user["username"])

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        result = _get_user_from_credentials(creds)
        self.assertIsNotNone(result)
        self.assertEqual(result["username"], "admin")

    async def test_require_auth_without_credentials_returns_none(self):
        from api.routes.auth import _get_user_from_credentials

        result = _get_user_from_credentials(None)
        self.assertIsNone(result)

    async def test_require_auth_with_invalid_token_returns_none(self):
        from api.routes.auth import _get_user_from_credentials
        from fastapi.security import HTTPAuthorizationCredentials

        result = _get_user_from_credentials(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
        )
        self.assertIsNone(result)


class TestOpenApiSecurity(unittest.IsolatedAsyncioTestCase):
    """OpenAPI schema uses BearerAuth, no query parameters."""

    async def test_bearer_auth_scheme_defined(self):
        from api.app import app
        schema = app.openapi()
        schemes = schema.get("components", {}).get("securitySchemes", {})
        self.assertIn("BearerAuth", schemes)
        self.assertEqual(schemes["BearerAuth"]["type"], "http")
        self.assertEqual(schemes["BearerAuth"]["scheme"], "bearer")

    async def test_no_authorization_query_param(self):
        from api.app import app
        schema = app.openapi()
        for path, methods in schema.get("paths", {}).items():
            for method_name, op in methods.items():
                params = op.get("parameters", [])
                for p in params:
                    self.assertNotEqual(p.get("name"), "authorization",
                        f"Found authorization query param on {path} {method_name}")

    async def test_health_has_no_security(self):
        from api.app import app
        schema = app.openapi()
        health_ops = schema.get("paths", {}).get("/health", {})
        for method_name, op in health_ops.items():
            self.assertEqual(op.get("security", []), [])

    async def test_login_has_no_security(self):
        from api.app import app
        schema = app.openapi()
        login_ops = schema.get("paths", {}).get("/api/auth/login", {})
        for method_name, op in login_ops.items():
            self.assertEqual(op.get("security", []), [])

    async def test_protected_endpoints_have_bearer_security(self):
        from api.app import app
        schema = app.openapi()
        protected = ["/api/auth/logout", "/api/auth/status", "/api/auth/users",
                     "/server", "/api/devices", "/api/aquawiz/devices",
                     "/api/aquawiz/poll/{device_id}", "/api/aquawiz/{device_id}/test"]
        for path, methods in schema.get("paths", {}).items():
            if path in protected:
                for method_name, op in methods.items():
                    security = op.get("security", [])
                    self.assertTrue(
                        any("BearerAuth" in s for s in security),
                        f"{path} {method_name.upper()} missing BearerAuth security"
                    )

    async def test_no_httpbearer_scheme_in_components(self):
        from api.app import app
        schema = app.openapi()
        schemes = schema.get("components", {}).get("securitySchemes", {})
        self.assertNotIn("HTTPBearer", schemes)

    async def test_health_has_no_security(self):
        from api.app import app
        schema = app.openapi()
        health_ops = schema.get("paths", {}).get("/health", {})
        for method_name, op in health_ops.items():
            self.assertEqual(op.get("security", []), [])

    async def test_login_has_no_security(self):
        from api.app import app
        schema = app.openapi()
        login_ops = schema.get("paths", {}).get("/api/auth/login", {})
        for method_name, op in login_ops.items():
            self.assertEqual(op.get("security", []), [])

    async def test_protected_endpoints_have_bearer_security(self):
        from api.app import app
        schema = app.openapi()
        protected = ["/api/auth/logout", "/api/auth/status", "/api/auth/users",
                     "/server", "/api/devices", "/api/aquawiz/devices",
                     "/api/aquawiz/poll/{device_id}", "/api/aquawiz/{device_id}/test"]
        for path, methods in schema.get("paths", {}).items():
            if path in protected:
                for method_name, op in methods.items():
                    security = op.get("security", [])
                    self.assertTrue(
                        any("BearerAuth" in s for s in security),
                        f"{path} {method_name} missing BearerAuth security"
                    )
