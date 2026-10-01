"""Tests for AquaWiz API endpoints and integration helpers.

Run with: python -m pytest tests/test_aquawiz_api.py -v
"""

import aiohttp
import asyncio
import tempfile
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient

from config import DATABASE_PATH
from database.connection import init_database
from devices.manager import DeviceManager, DeviceNotFoundError
from creds.manager import CredentialManager
from integrations.aquawiz import (
    AquaWizIntegration,
    AquaWizIntegrationError,
    _find_device,
    _safe_div,
    _safe_int,
    _parse_timestamp,
    _telemetry,
)


def _make_db():
    tmp = tempfile.mkdtemp()
    db_path = f"{tmp}/test.db"
    asyncio.run(init_database(db_path))
    return db_path


async def _make_device_with_creds(db_path, serial="KH1-00-02544"):
    mgr = DeviceManager(db_path)
    cred_mgr = CredentialManager(db_path)
    device = await mgr.create_device({
        "name": "Test KH",
        "device_type": "kh",
        "brand": "AquaWiz",
        "model": "KH",
        "integration": "aquawiz",
        "poll_interval_seconds": 300,
        "config": {"serial": serial, "device_type": "kh", "access_token": "tok-123"},
    })
    cred_ref = await cred_mgr.create(device["id"], "aquawiz")
    await mgr.update_device(device["id"], {"credential_ref": cred_ref["credential_ref"]})
    return device


def _make_app_client():
    from api.app import app
    from api.routes.auth import require_auth

    app.dependency_overrides.clear()
    app.dependency_overrides[require_auth] = lambda: {"user_id": "test-user", "username": "testuser"}
    return TestClient(app)


def _make_auth_dependency():
    async def _fake_auth():
        return {"user_id": "test-user", "username": "testuser"}
    return _fake_auth


# ─── Async mock helpers ─────────────────────────────────────────────────────

def _make_response_mock(status, json_data):
    """Create a mock HTTP response supporting async `with` and `.json()`."""
    m = mock.MagicMock()
    m.status = status
    m.__aenter__ = mock.AsyncMock(return_value=m)
    m.__aexit__ = mock.AsyncMock(return_value=False)
    m.json = mock.AsyncMock(return_value=json_data)
    return m


def _make_session(auth_devices=None, poll_status=200, poll_json=None):
    """Build a mock aiohttp.ClientSession.

    session.post(...) returns MagicMock responses directly (not coroutines)
    so they can be used as `async with session.post(...) as resp:`.
    The session itself also supports `async with aiohttp.ClientSession() as session:`.
    """
    if auth_devices is None:
        auth_devices = ["KH1-00-02544"]
    if poll_json is None:
        poll_json = {"latest_kh": 7566, "latest_time": 1727272140000}

    session = mock.MagicMock()
    session.__aenter__ = mock.AsyncMock(return_value=session)
    session.__aexit__ = mock.AsyncMock(return_value=False)

    auth_resp = _make_response_mock(200, {
        "access_token": "tok-abc",
        "user": {"devices": auth_devices},
    })
    poll_resp = _make_response_mock(poll_status, poll_json)

    session.post = mock.Mock(side_effect=[auth_resp, poll_resp])
    return session


# ─── _find_device ───────────────────────────────────────────────────────────

class TestFindDevice:
    def test_find_by_exact_serial(self):
        devices = [{"serial": "KH1-00-02544", "name": "KH1"}]
        result = _find_device(devices, "KH1-00-02544")
        assert result == {"serial": "KH1-00-02544", "name": "KH1"}

    def test_find_case_insensitive(self):
        devices = [{"serial": "kh1-00-02544", "name": "KH1"}]
        result = _find_device(devices, "KH1-00-02544")
        assert result is not None
        assert result["serial"] == "kh1-00-02544"

    def test_not_found(self):
        devices = [{"serial": "KH1-00-02544"}]
        assert _find_device(devices, "XX1-00-00001") is None

    def test_empty_list(self):
        assert _find_device([], "KH1-00-02544") is None


# ─── Integration test_connection ────────────────────────────────────────────

class TestIntegrationTestConnection:
    def setup_method(self):
        self.integration = AquaWizIntegration()

    @pytest.mark.asyncio
    async def test_success_with_device_validation(self):
        mock_session = _make_session()
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.test_connection(
                {"username": "u", "password": "p"},
                device_serial="KH1-00-02544",
                device_type="kh",
            )
        assert result["success"] is True
        assert "Connected" in result["message"]
        assert result["details"]["devices"][0]["serial"] == "KH1-00-02544"

    @pytest.mark.asyncio
    async def test_device_not_found_in_account(self):
        mock_session = _make_session()
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.test_connection(
                {"username": "u", "password": "p"},
                device_serial="XX1-00-00001",
                device_type="kh",
            )
        assert result["success"] is False
        assert "not found" in result["message"].lower()
        assert result["details"] is not None

    @pytest.mark.asyncio
    async def test_no_devices_in_account(self):
        mock_session = _make_session(auth_devices=[])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.test_connection(
                {"username": "u", "password": "p"},
                device_serial="KH1-00-02544",
                device_type="kh",
            )
        assert result["success"] is False
        assert "no devices" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_device_poll_fails(self):
        mock_session = _make_session(poll_status=500)
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.test_connection(
                {"username": "u", "password": "p"},
                device_serial="KH1-00-02544",
                device_type="kh",
            )
        assert result["success"] is False
        assert "failed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_auth_failure(self):
        mock_session = mock.MagicMock()
        mock_session.__aenter__ = mock.AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = mock.AsyncMock(return_value=False)
        auth_resp = _make_response_mock(401, {})
        auth_resp.raise_for_status = mock.Mock(
            side_effect=aiohttp.ClientResponseError(
                request_info=mock.MagicMock(), history=[], status=401
            )
        )
        mock_session.post = mock.Mock(return_value=auth_resp)
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.test_connection({"username": "u", "password": "p"})
        assert result["success"] is False
        assert "401" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        result = await self.integration.test_connection({"username": "", "password": ""})
        assert result["success"] is False
        assert "missing" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_success_without_device_serial(self):
        mock_session = _make_session()
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.test_connection({"username": "u", "password": "p"})
        assert result["success"] is True
        assert result["details"]["devices"][0]["serial"] == "KH1-00-02544"

    @pytest.mark.asyncio
    async def test_unsupported_device_type(self):
        mock_session = _make_session(auth_devices=["XX1-00-00001"])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.test_connection(
                {"username": "u", "password": "p"},
                device_serial="XX1-00-00001",
                device_type="unknown",
            )
        assert result["success"] is False
        assert "unsupported" in result["message"].lower()


# ─── Integration discover_devices ───────────────────────────────────────────

class TestDiscoverDevices:
    def setup_method(self):
        self.integration = AquaWizIntegration()

    @pytest.mark.asyncio
    async def test_discover_returns_devices_and_token(self):
        mock_session = _make_session(auth_devices=[
            "KH1-00-02544",
            "CA1-00-00646",
        ])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        assert result["success"] is True
        assert len(result["devices"]) == 2
        assert result["access_token"] == "tok-abc"
        assert result["devices"][0]["serial"] == "KH1-00-02544"

    @pytest.mark.asyncio
    async def test_discover_filters_empty_serials(self):
        mock_session = _make_session(auth_devices=[
            "KH1-00-02544",
            "",
            None,
        ])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        assert len(result["devices"]) == 1
        assert result["devices"][0]["serial"] == "KH1-00-02544"

    @pytest.mark.asyncio
    async def test_discover_detects_device_types(self):
        mock_session = _make_session(auth_devices=[
            "KH1-00-02544",
            "CA1-00-00646",
        ])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        types = {d["serial"]: d["type"] for d in result["devices"]}
        assert types["KH1-00-02544"] == "kh"
        assert types["CA1-00-00646"] == "carx"

    @pytest.mark.asyncio
    async def test_discover_missing_credentials(self):
        result = await self.integration.discover_devices({"username": "", "password": ""})
        assert result["success"] is False
        assert result["devices"] == []
        assert result["access_token"] == ""

    @pytest.mark.asyncio
    async def test_discover_auth_failure(self):
        mock_session = mock.MagicMock()
        mock_session.__aenter__ = mock.AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = mock.AsyncMock(return_value=False)
        auth_resp = _make_response_mock(401, {})
        auth_resp.raise_for_status = mock.Mock(
            side_effect=aiohttp.ClientResponseError(
                request_info=mock.MagicMock(), history=[], status=401
            )
        )
        mock_session.post = mock.Mock(return_value=auth_resp)
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        assert result["success"] is False
        assert "401" in result["message"]

    @pytest.mark.asyncio
    async def test_discover_with_string_serial_list(self):
        """Real AquaWiz API returns user.devices as a list of serial strings."""
        mock_session = _make_session(auth_devices=["KH1-00-02544", "CA1-00-00646"])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        assert result["success"] is True
        assert len(result["devices"]) == 2
        assert result["devices"][0]["serial"] == "KH1-00-02544"
        assert result["devices"][0]["type"] == "kh"
        assert result["devices"][1]["serial"] == "CA1-00-00646"
        assert result["devices"][1]["type"] == "carx"

    @pytest.mark.asyncio
    async def test_discover_handles_dict_devices_legacy(self):
        """Backward compat: also accept dict-format devices if API ever changes."""
        mock_session = _make_session(auth_devices=[
            {"serial": "KH1-00-02544"},
            {"serial": "CA1-00-00646"},
        ])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        assert result["success"] is True
        assert len(result["devices"]) == 2

    @pytest.mark.asyncio
    async def test_discover_empty_devices_list(self):
        mock_session = _make_session(auth_devices=[])
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        assert result["success"] is True
        assert result["devices"] == []

    @pytest.mark.asyncio
    async def test_discover_missing_user_devices_key(self):
        """user.devices key missing from response — handled safely."""
        mock_session = mock.MagicMock()
        mock_session.__aenter__ = mock.AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = mock.AsyncMock(return_value=False)
        auth_resp = _make_response_mock(200, {
            "access_token": "tok-abc",
            "user": {},
        })
        mock_session.post = mock.Mock(return_value=auth_resp)
        with mock.patch("integrations.aquawiz.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = mock_session
            result = await self.integration.discover_devices({"username": "u", "password": "p"})
        assert result["success"] is True
        assert result["devices"] == []


# ─── API endpoint tests ─────────────────────────────────────────────────────

class TestAquaWizApiEndpoints:
    def setup_method(self):
        from api.app import app
        from api.routes.auth import require_auth
        app.dependency_overrides.clear()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test-user", "username": "testuser"}
        self.client = TestClient(app)

    def test_discover_endpoint_success(self):
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover:
            mock_discover.return_value = {
                "success": True,
                "message": "2 devices found",
                "devices": [
                    {"serial": "KH1-00-02544", "type": "kh"},
                    {"serial": "CA1-00-00646", "type": "carx"},
                ],
                "access_token": "tok-abc",
            }
            response = self.client.post("/api/aquawiz/discover", json={
                "username": "testuser",
                "password": "testpass",
            }, headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["devices"]) == 2
        assert data["accessToken"] == "tok-abc"

    def test_discover_endpoint_failure(self):
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover:
            mock_discover.side_effect = AquaWizIntegrationError("Auth failed")
            response = self.client.post("/api/aquawiz/discover", json={
                "username": "bad",
                "password": "bad",
            }, headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 502

    def test_register_endpoint_success(self, isolated_aquawiz_db):
        import api.routes.aquawiz as _routes
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover, \
             mock.patch.object(_routes._mgr, "list_devices", return_value=[]):
            mock_discover.return_value = {
                "success": True,
                "message": "1 device found",
                "devices": [{"serial": "KH1-00-02544", "type": "kh"}],
                "access_token": "tok-abc",
            }
            response = self.client.post("/api/aquawiz/register", json={
                "serial": "KH1-00-02544",
                "deviceType": "KH",
                "username": "testuser",
                "password": "testpass",
                "pollIntervalSeconds": 300,
            }, headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["deviceId"] is not None
        assert data["serial"] == "KH1-00-02544"
        assert data["deviceType"] == "kh"

    def test_register_endpoint_serial_not_found(self):
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover:
            mock_discover.return_value = {
                "success": True,
                "message": "1 device found",
                "devices": [{"serial": "KH1-00-02544", "type": "kh"}],
                "access_token": "tok-abc",
            }
            response = self.client.post("/api/aquawiz/register", json={
                "serial": "XX1-00-00001",
                "deviceType": "KH",
                "username": "testuser",
                "password": "testpass",
            }, headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_test_connection_endpoint_success(self):
        fake_device = {
            "id": "test-device-id",
            "name": "Test KH",
            "device_type": "kh",
            "brand": "AquaWiz",
            "integration": "aquawiz",
            "config": {"serial": "KH1-00-02544", "device_type": "kh", "access_token": "tok-123"},
            "credential_ref": "cred-ref-1",
        }
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "test_connection") as mock_test, \
             mock.patch("api.routes.aquawiz._mgr.get_device", return_value=fake_device):
            mock_test.return_value = {
                "success": True,
                "message": "Connected - 1 device(s) found",
                "details": {"devices": [{"serial": "KH1-00-02544", "type": "kh"}]},
            }
            response = self.client.post("/api/aquawiz/test-device-id/test", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_test_connection_endpoint_device_not_found(self):
        with mock.patch("api.routes.aquawiz._mgr.get_device", side_effect=DeviceNotFoundError("Not found")):
            response = self.client.post("/api/aquawiz/nonexistent-id/test", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 404

    def test_test_connection_endpoint_not_aquawiz(self):
        fake_device = {
            "id": "generic-id",
            "name": "Generic",
            "device_type": "monitor",
            "brand": "Generic",
            "integration": "generic",
            "config": {"serial": ""},
        }
        with mock.patch("api.routes.aquawiz._mgr.get_device", return_value=fake_device):
            response = self.client.post("/api/aquawiz/generic-id/test", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 400

    def test_test_connection_endpoint_no_credentials(self):
        import api.routes.aquawiz as aw
        fake_device = {
            "id": "no-creds-id",
            "name": "NoCreds",
            "device_type": "kh",
            "brand": "AquaWiz",
            "integration": "aquawiz",
            "config": {"serial": "KH1-00-02544"},
            "credential_ref": None,
        }
        fake_mgr = mock.MagicMock()
        fake_mgr.get_device = mock.AsyncMock(return_value=fake_device)
        fake_integration = mock.MagicMock()
        fake_integration.test_connection = mock.AsyncMock(return_value={
            "success": False, "message": "Missing username or password", "details": None
        })
        saved_mgr = aw._mgr
        saved_int = aw._integration
        aw._mgr = fake_mgr
        aw._integration = fake_integration
        try:
            from api.app import app
            client = TestClient(app)
            response = client.post("/api/aquawiz/no-creds-id/test", headers={"Authorization": "Bearer test-token"})
        finally:
            aw._mgr = saved_mgr
            aw._integration = saved_int
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_poll_endpoint_success(self):
        fake_device = {
            "id": "poll-device-id",
            "name": "Test KH",
            "device_type": "kh",
            "brand": "AquaWiz",
            "integration": "aquawiz",
            "config": {"serial": "KH1-00-02544", "device_type": "kh", "access_token": "tok-123"},
            "credential_ref": "cred-ref-1",
        }
        fake_secrets = {"username": "u", "password": "p", "access_token": "tok-123"}
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "poll") as mock_poll, \
             mock.patch("api.routes.aquawiz._mgr.get_device", return_value=fake_device), \
             mock.patch("api.routes.aquawiz._cred_mgr.get_secrets", return_value=fake_secrets), \
             mock.patch("api.routes.aquawiz._data_mgr.store", return_value=2):
            mock_poll.return_value = [
                {"parameter_name": "kh", "value": 7.5, "unit": "dKH", "timestamp": "2024-09-25T13:49:00Z"},
                {"parameter_name": "ph", "value": 8.1, "unit": "", "timestamp": "2024-09-25T13:49:00Z"},
            ]
            response = self.client.post("/api/aquawiz/poll/poll-device-id", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["deviceId"] == "poll-device-id"
        assert len(data["readings"]) == 2

    def test_list_devices_endpoint(self):
        fake_devices = [
            {
                "id": "dev-1",
                "name": "Test KH",
                "device_type": "kh",
                "brand": "AquaWiz",
                "integration": "aquawiz",
                "enabled": True,
                "config": {"serial": "KH1-00-02544"},
                "credential_ref": "cred-ref-1",
            }
        ]
        fake_meta = {"credential_ref": "cred-ref-1", "configured": 1}
        with mock.patch("api.routes.aquawiz._mgr.list_devices", return_value=fake_devices), \
             mock.patch("api.routes.aquawiz._cred_mgr.get_metadata_by_ref", return_value=fake_meta):
            response = self.client.get("/api/aquawiz/devices", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["serial"] == "KH1-00-02544"


# ─── Security: no credential leakage ───────────────────────────────────────

class TestNoCredentialLeakage:
    """Ensure AquaWiz credentials are never exposed through API responses."""

    def test_discover_does_not_return_password(self):
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover:
            mock_discover.return_value = {
                "success": True,
                "message": "1 device found",
                "devices": [{"serial": "KH1-00-02544", "type": "kh"}],
                "access_token": "tok-abc",
            }
            client = _make_app_client()
            response = client.post("/api/aquawiz/discover", json={
                "username": "testuser",
                "password": "secret123",
            }, headers={"Authorization": "Bearer any-token"})
        assert response.status_code == 200
        assert "secret123" not in response.text

    def test_register_does_not_return_credentials(self, isolated_aquawiz_db):
        import api.routes.aquawiz as _routes
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover, \
             mock.patch.object(_routes._mgr, "list_devices", return_value=[]):
            mock_discover.return_value = {
                "success": True,
                "message": "1 device found",
                "devices": [{"serial": "KH1-00-02544", "type": "kh"}],
                "access_token": "tok-abc",
            }
            client = _make_app_client()
            response = client.post("/api/aquawiz/register", json={
                "serial": "KH1-00-02544",
                "deviceType": "KH",
                "username": "testuser",
                "password": "secret123",
            }, headers={"Authorization": "Bearer any-token"})
        assert response.status_code == 200
        assert "secret123" not in response.text

    def test_discover_endpoint_normalizes_string_serials(self):
        """POST /api/aquawiz/discover with real AquaWiz string-list response."""
        from integrations.aquawiz import AquaWizIntegration
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover:
            mock_discover.return_value = {
                "success": True,
                "message": "2 devices found",
                "devices": [
                    {"serial": "KH1-00-02544", "type": "kh"},
                    {"serial": "CA1-00-00646", "type": "carx"},
                ],
                "access_token": "tok-real",
            }
            client = _make_app_client()
            response = client.post("/api/aquawiz/discover", json={
                "username": "testuser",
                "password": "secret123",
            }, headers={"Authorization": "Bearer any-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["devices"]) == 2
        assert data["devices"][0]["serial"] == "KH1-00-02544"
        assert "secret123" not in response.text
