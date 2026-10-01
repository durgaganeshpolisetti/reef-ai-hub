"""Shared fixtures for test modules."""
import asyncio
import tempfile
import unittest.mock as mock

import pytest
import auth.session as _auth_session
from database.connection import init_database


@pytest.fixture(scope="module")
def mock_auth():
    """Scope the validate_session mock to individual test modules."""
    original = _auth_session.validate_session
    _auth_session.validate_session = mock.MagicMock(
        return_value={"user_id": "test-user", "username": "testuser"}
    )
    yield
    _auth_session.validate_session = original


@pytest.fixture()
def isolated_aquawiz_db():
    """Redirect the aquawiz route managers to a temporary database.

    Any test that exercises the register endpoint (or any other endpoint
    that persists data) should request this fixture to keep the real
    DATABASE_PATH untouched.
    """
    import api.routes.aquawiz as _aquawiz_routes
    from devices.manager import DeviceManager as DM
    from creds.manager import CredentialManager as CM
    from aquawiz.data_manager import AquaWizDataManager as ADM

    tmp_dir = tempfile.mkdtemp()
    db_path = f"{tmp_dir}/test.db"
    asyncio.run(init_database(db_path))

    orig_mgr = _aquawiz_routes._mgr
    orig_cred_mgr = _aquawiz_routes._cred_mgr
    orig_data_mgr = _aquawiz_routes._data_mgr

    _aquawiz_routes._mgr = DM(db_path)
    _aquawiz_routes._cred_mgr = CM(db_path)
    _aquawiz_routes._data_mgr = ADM(db_path)
    yield db_path
    _aquawiz_routes._mgr = orig_mgr
    _aquawiz_routes._cred_mgr = orig_cred_mgr
    _aquawiz_routes._data_mgr = orig_data_mgr
