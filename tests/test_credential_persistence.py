"""Diagnostic regression tests for AquaWiz credential persistence.

These tests trace the full Create Device credential flow and compare
it with the Edit Device (update_credentials) flow.

Run with: python -m pytest tests/test_credential_persistence.py -v
"""

import asyncio
import tempfile
import unittest.mock as mock
import pytest

from config import DATABASE_PATH
from database.connection import init_database
from devices.manager import DeviceManager, DeviceNotFoundError
from creds.manager import CredentialManager
from integrations.aquawiz import AquaWizIntegration
from fastapi.testclient import TestClient
from api.app import app
from api.routes.auth import require_auth


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_db():
    tmp = tempfile.mkdtemp()
    db_path = f"{tmp}/test.db"
    asyncio.run(init_database(db_path))
    return db_path


def _clear_keyring(credential_ref):
    """Remove a credential from keyring if it exists (test cleanup)."""
    if not credential_ref:
        return
    try:
        import keyring
        keyring.delete_password("reef-ai-hub", credential_ref)
    except Exception:
        pass


def _retrieve_from_vault(credential_ref):
    """Directly call CredentialVault.retrieve() to check if credentials survive."""
    from creds.vault import vault
    return vault.retrieve(credential_ref)


def _make_client_with_managers(mgr, cred_mgr):
    """Create a TestClient with the app's module-level managers replaced.

    This is critical: the route functions hold references to the module-level
    singletons (e.g. api.routes.devices.manager). If we patch them AFTER
    creating the TestClient, the routes still point to the original DB.
    """
    import api.routes.aquawiz as _a_routes
    import api.routes.devices as _d_routes

    # Save originals
    a_orig_mgr = _a_routes._mgr
    a_orig_cred = _a_routes._cred_mgr
    d_orig_mgr = _d_routes.manager
    d_orig_cred = _d_routes.cred_mgr

    # Patch BEFORE creating the client so route functions capture the new refs
    _a_routes._mgr = mgr
    _a_routes._cred_mgr = cred_mgr
    _d_routes.manager = mgr
    _d_routes.cred_mgr = cred_mgr

    app.dependency_overrides.clear()
    app.dependency_overrides[require_auth] = lambda: {"user_id": "test-user", "username": "testuser"}
    client = TestClient(app)

    def _restore():
        _a_routes._mgr = a_orig_mgr
        _a_routes._cred_mgr = a_orig_cred
        _d_routes.manager = d_orig_mgr
        _d_routes.cred_mgr = d_orig_cred

    return client, _restore


def _do_register(db_path, cred_mgr):
    """Perform the AquaWiz registration and return (device_id, credential_ref)."""
    mgr = DeviceManager(db_path)

    import api.routes.aquawiz as _routes
    a_orig_mgr = _routes._mgr
    a_orig_cred = _routes._cred_mgr
    _routes._mgr = mgr
    _routes._cred_mgr = cred_mgr

    device_id = None
    credential_ref = None

    try:
        # Match the exact pattern from the existing test suite:
        # mock.patch.object returns an async-compatible mock when patching
        # an async method; we set .return_value to the discover result.
        with mock.patch.object(AquaWizIntegration, "discover_devices") as mock_discover, \
             mock.patch.object(_routes._mgr, "list_devices", return_value=[]):
            mock_discover.return_value = {
                "success": True,
                "message": "1 device found",
                "devices": [{"serial": "KH1-00-02544", "type": "kh"}],
                "access_token": "tok-abc",
            }
            app.dependency_overrides.clear()
            app.dependency_overrides[require_auth] = lambda: {"user_id": "test-user", "username": "testuser"}
            client = TestClient(app)
            response = client.post("/api/aquawiz/register", json={
                "serial": "KH1-00-02544",
                "deviceType": "KH",
                "username": "testuser",
                "password": "testpass123",
                "pollIntervalSeconds": 300,
            }, headers={"Authorization": "Bearer any-token"})

        assert response.status_code == 200, f"Register failed: {response.status_code} {response.text}"
        data = response.json()
        device_id = data["deviceId"]

        device = asyncio.run(mgr.get_device(device_id))
        credential_ref = device.get("credential_ref")
    finally:
        _routes._mgr = a_orig_mgr
        _routes._cred_mgr = a_orig_cred

    return device_id, credential_ref


# ─── Test A: Create Device → credentials stored → metadata configured ────

class TestCreateDeviceCredentialPersistence:
    """Verify the full Create Device credential flow."""

    def test_register_succeeds_and_returns_device_id(self):
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        device_id, _ = _do_register(db_path, cred_mgr)
        assert device_id is not None
        assert device_id != ""
        _clear_keyring(_)

    def test_device_credential_ref_populated_in_db(self):
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        device_id, cred_ref = _do_register(db_path, cred_mgr)

        device = asyncio.run(DeviceManager(db_path).get_device(device_id))
        assert device.get("credential_ref") is not None, \
            f"credential_ref is None for device {device_id}"
        assert device.get("credential_ref") != "", \
            f"credential_ref is empty for device {device_id}"
        _clear_keyring(cred_ref)

    def test_device_credentials_metadata_configured_is_true(self):
        """device_credentials row must have configured=1 after registration."""
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        device_id, cred_ref = _do_register(db_path, cred_mgr)

        meta = asyncio.run(cred_mgr.get_metadata_by_ref(cred_ref))
        assert meta is not None, f"No metadata row for credential_ref={cred_ref}"
        assert meta.get("configured") == 1, \
            f"configured={meta.get('configured')}, expected 1"
        _clear_keyring(cred_ref)

    def test_get_devices_reports_credentials_configured(self):
        """GET /api/devices must report credentials_configured=true."""
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        device_id, _ = _do_register(db_path, cred_mgr)
        mgr = DeviceManager(db_path)

        client, _restore = _make_client_with_managers(mgr, cred_mgr)
        try:
            response = client.get("/api/devices", headers={"Authorization": "Bearer any-token"})
        finally:
            _restore()

        assert response.status_code == 200
        data = response.json()
        matching = [d for d in data if d["id"] == device_id]
        assert len(matching) == 1, f"Device {device_id} not found in /api/devices: got {[d['id'] for d in data]}"
        assert matching[0]["credentials_configured"] is True

    def test_get_aquawiz_devices_reports_credentials_configured(self):
        """GET /api/aquawiz/devices must report credentialsConfigured=true."""
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        device_id, cred_ref = _do_register(db_path, cred_mgr)
        mgr = DeviceManager(db_path)

        import api.routes.aquawiz as _routes
        a_orig_mgr = _routes._mgr
        a_orig_cred = _routes._cred_mgr
        _routes._mgr = mgr
        _routes._cred_mgr = cred_mgr
        app.dependency_overrides.clear()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "test-user", "username": "testuser"}
        try:
            client = TestClient(app)
            response = client.get("/api/aquawiz/devices", headers={"Authorization": "Bearer any-token"})
        finally:
            _routes._mgr = a_orig_mgr
            _routes._cred_mgr = a_orig_cred

        assert response.status_code == 200
        data = response.json()
        matching = [d for d in data if d["deviceId"] == device_id]
        assert len(matching) == 1, f"Device {device_id} not found in /api/aquawiz/devices"
        assert matching[0]["credentialsConfigured"] is True
        _clear_keyring(cred_ref)

    def test_no_credentials_in_device_config(self):
        """After registration, devices.config must NOT contain sensitive fields."""
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        device_id, _ = _do_register(db_path, cred_mgr)

        device = asyncio.run(DeviceManager(db_path).get_device(device_id))
        config = device.get("config", {})
        for key in list(config.keys()):
            lower = key.lower()
            assert not any(s in lower for s in ("password", "token", "secret", "key", "credential")), \
                f"Sensitive key '{key}' found in device config: {config}"
        _clear_keyring(_)


# ─── Test B: CredentialVault.retrieve() after Create Device ─────────────

class TestCreateDeviceVaultRetrieval:
    """Verify that CredentialVault.retrieve() can get back stored credentials."""

    def test_credential_vault_retrieve_returns_credentials(self):
        """CredentialVault.retrieve() must return the stored username/password."""
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        _, cred_ref = _do_register(db_path, cred_mgr)

        assert cred_ref is not None, "No credential_ref stored"
        secrets = _retrieve_from_vault(cred_ref)
        assert secrets is not None, \
            f"CredentialVault.retrieve() returned None for {cred_ref}"
        assert secrets.get("username") == "testuser", \
            f"Retrieved username={secrets.get('username')!r}, expected 'testuser'"
        assert secrets.get("password") == "testpass123", \
            f"Retrieved password={secrets.get('password')!r}, expected 'testpass123'"
        _clear_keyring(cred_ref)

    def test_credential_vault_retrieve_includes_access_token(self):
        """The access_token from discover must be in the vault."""
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        _, cred_ref = _do_register(db_path, cred_mgr)

        secrets = _retrieve_from_vault(cred_ref)
        assert secrets is not None
        assert secrets.get("access_token") == "tok-abc"
        _clear_keyring(cred_ref)


# ─── Test C: Edit Device → credentials stored/retrieved (baseline) ───────

class TestEditDeviceCredentialBaseline:
    """Verify that the Edit Device credential update works (baseline for comparison)."""

    def test_update_credentials_stores_and_retrieves(self):
        """POST /api/devices/{id}/credentials must store and allow retrieval."""
        db_path = _make_db()
        mgr = DeviceManager(db_path)
        cred_mgr = CredentialManager(db_path)

        # Create device with NO credentials
        device = asyncio.run(mgr.create_device({
            "name": "Test Device",
            "device_type": "kh",
            "brand": "AquaWiz",
            "model": "KH",
            "integration": "aquawiz",
            "poll_interval_seconds": 300,
            "config": {"serial": "KH1-00-02544", "device_type": "kh"},
        }))

        # Create credential metadata row
        cred_meta = asyncio.run(cred_mgr.create(device["id"], "aquawiz"))
        cred_ref = cred_meta["credential_ref"]

        # Link to device
        asyncio.run(mgr.update_device(device["id"], {"credential_ref": cred_ref}))

        # Create client with patched managers BEFORE instantiation
        client, _restore = _make_client_with_managers(mgr, cred_mgr)
        try:
            response = client.post(
                f"/api/devices/{device['id']}/credentials",
                json={
                    "username": "edituser",
                    "password": "editpass456",
                },
                headers={"Authorization": "Bearer any-token"},
            )
        finally:
            _restore()

        assert response.status_code == 200, f"Got {response.status_code}: {response.text}"

        # Verify metadata: configured=1
        meta = asyncio.run(cred_mgr.get_metadata_by_ref(cred_ref))
        assert meta is not None
        assert meta.get("configured") == 1

        # Verify vault retrieval
        secrets = _retrieve_from_vault(cred_ref)
        assert secrets is not None
        assert secrets.get("username") == "edituser"
        assert secrets.get("password") == "editpass456"

        _clear_keyring(cred_ref)

    def test_create_vs_edit_both_store_secrets_in_vault(self):
        """Both Create Device and Edit Device must store secrets in vault."""
        # --- Create Device path ---
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        _, create_cred_ref = _do_register(db_path, cred_mgr)
        create_secrets = _retrieve_from_vault(create_cred_ref)
        _clear_keyring(create_cred_ref)

        # --- Edit Device path ---
        db_path2 = _make_db()
        mgr2 = DeviceManager(db_path2)
        cred_mgr2 = CredentialManager(db_path2)

        device = asyncio.run(mgr2.create_device({
            "name": "Test Device",
            "device_type": "kh",
            "brand": "AquaWiz",
            "model": "KH",
            "integration": "aquawiz",
            "poll_interval_seconds": 300,
            "config": {"serial": "KH1-00-02544", "device_type": "kh"},
        }))
        cred_meta = asyncio.run(cred_mgr2.create(device["id"], "aquawiz"))
        cred_ref2 = cred_meta["credential_ref"]
        asyncio.run(mgr2.update_device(device["id"], {"credential_ref": cred_ref2}))

        client, _restore = _make_client_with_managers(mgr2, cred_mgr2)
        try:
            client.post(
                f"/api/devices/{device['id']}/credentials",
                json={"username": "edituser", "password": "editpass456"},
                headers={"Authorization": "Bearer any-token"},
            )
        finally:
            _restore()

        edit_secrets = _retrieve_from_vault(cred_ref2)
        _clear_keyring(cred_ref2)

        # Both paths must have stored the secrets
        assert create_secrets is not None, "Create Device secrets not in vault"
        assert edit_secrets is not None, "Edit Device secrets not in vault"
        # Both must have the same structure
        assert "username" in create_secrets
        assert "password" in create_secrets
        assert "username" in edit_secrets
        assert "password" in edit_secrets


# ─── Test D: No credentials in device config ──────────────────────────────

class TestNoCredentialsInDeviceConfig:
    """Verify that credential data is never written to devices.config."""

    def test_register_does_not_write_credentials_to_config(self):
        """After Create Device, config must not contain sensitive fields."""
        db_path = _make_db()
        cred_mgr = CredentialManager(db_path)
        device_id, _ = _do_register(db_path, cred_mgr)

        device = asyncio.run(DeviceManager(db_path).get_device(device_id))
        config = device.get("config", {})
        for key in list(config.keys()):
            lower = key.lower()
            assert not any(s in lower for s in ("password", "token", "secret", "key", "credential")), \
                f"Sensitive key '{key}' found in device config: {config}"
        _clear_keyring(_)
