import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from devices.manager import DeviceManager, DeviceNotFoundError
from creds.manager import CredentialManager
from api.routes.auth import require_auth
from integrations.aquawiz import AquaWizIntegration, AquaWizIntegrationError
from aquawiz.data_manager import AquaWizDataManager
from config import DATABASE_PATH

logger = logging.getLogger("reef_ai_hub.api.aquawiz")
router = APIRouter(prefix="/api/aquawiz", tags=["aquawiz"])
_mgr = DeviceManager(DATABASE_PATH)
_cred_mgr = CredentialManager(DATABASE_PATH)
_integration = AquaWizIntegration()
_data_mgr = AquaWizDataManager(DATABASE_PATH)


class DeviceTestResponse(BaseModel):
    success: bool
    message: str
    error_type: str = ""
    details: dict | None = None


_AQUAWIZ_USER_MESSAGES = {
    "invalid_credentials": "AquaWiz authentication failed. Check the AquaWiz username and password.",
    "network": "Unable to reach AquaWiz. Check the internet connection.",
    "timeout": "AquaWiz did not respond within the expected time.",
    "not_found": "The configured AquaWiz device could not be found.",
    "device_error": "AquaWiz device test failed. Please try again.",
}


def _map_aquawiz_error(raw: str) -> str:
    """Normalize a raw AquaWiz integration error to a safe error_type key."""
    lower = raw.lower()
    if "timeout" in lower or "timed out" in lower:
        return "timeout"
    if "network" in lower or "unreachable" in lower or "resolve" in lower:
        return "network"
    if "auth failed" in lower:
        # HTTP 400 and 401 both come from _auth_login as "Auth failed: HTTP <code>"
        # AquaWiz uses both for authentication failures.
        return "invalid_credentials"
    if "401" in lower:
        return "invalid_credentials"
    if "not found" in lower:
        return "not_found"
    if "device" in lower:
        return "device_error"
    return "device_error"


# ─── Schemas ────────────────────────────────────────────────────────────────

class AquaWizReading(BaseModel):
    name: str
    value: float
    unit: str


class AquaWizPollResponse(BaseModel):
    deviceId: str
    deviceType: str
    serial: str
    readings: list[AquaWizReading]
    readingTimestamp: str | None = None
    lastUpdated: str


class AquaWizDeviceInfo(BaseModel):
    deviceId: str
    deviceType: str
    serial: str
    name: str
    model: str = ""
    brand: str = ""
    enabled: bool
    credentialsConfigured: bool
    lastPollSuccess: str | None = None
    lastPollFailure: str | None = None
    lastError: str | None = None


class AquaWizDiscoveredDevice(BaseModel):
    serial: str
    type: str
    registered: bool = False


class AquaWizDiscoverResponse(BaseModel):
    success: bool
    message: str
    devices: list[AquaWizDiscoveredDevice]
    accessToken: str = ""


class AqwWizAuthRequest(BaseModel):
    username: str = Field(..., description="AquaWiz account username")
    password: str = Field(..., description="AquaWiz account password")


class AquaWizRegisterRequest(AqwWizAuthRequest):
    serial: str = Field(..., description="AquaWiz device serial number")
    deviceType: str = Field(..., description="Device type: kh or carx")
    pollIntervalSeconds: int = Field(default=300, ge=60, description="Poll interval in seconds")


class AquaWizTestRequest(AqwWizAuthRequest):
    serial: str = Field(..., description="AquaWiz device serial number")
    deviceType: str = Field(..., description="Device type: kh or carx")


@router.post("/test-connection", response_model=DeviceTestResponse)
async def test_aquawiz_connection_pre_registration(request: AquaWizTestRequest, _: dict = Depends(require_auth)):
    """Test AquaWiz connection before device registration (for Add Device flow)."""
    secrets = {"username": request.username, "password": request.password}
    try:
        result = await _integration.test_connection(secrets, device_serial=request.serial, device_type=request.deviceType)
    except AquaWizIntegrationError as e:
        logger.warning("AquaWiz pre-registration test failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    return DeviceTestResponse(**result)


class AquaWizRegisterResponse(BaseModel):
    deviceId: str
    name: str
    serial: str
    deviceType: str
    message: str


# ─── Helpers ───────────────────────────────────────────────────────────────

async def _device_info(device: dict) -> dict:
    cred_ref = device.get("credential_ref")
    configured = False
    if cred_ref:
        meta = await _cred_mgr.get_metadata_by_ref(cred_ref)
        configured = bool(meta and meta.get("configured"))
        if not configured:
            secrets = await _cred_mgr.get_secrets(cred_ref)
            if secrets and (secrets.get("username") or secrets.get("password")):
                configured = True
                now = datetime.now(timezone.utc).isoformat()
                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.execute(
                        """INSERT OR IGNORE INTO device_credentials
                        (credential_ref, credential_type, configured, created_at, updated_at)
                        VALUES (?, 'password', 1, ?, ?)""",
                        (cred_ref, now, now),
                    )
                    await db.commit()
    return {
        "deviceId": device["id"],
        "deviceType": device.get("device_type", "other"),
        "serial": device.get("config", {}).get("serial", ""),
        "name": device.get("name", ""),
        "model": device.get("config", {}).get("model", ""),
        "brand": device.get("brand", ""),
        "enabled": device.get("enabled", True),
        "credentialsConfigured": configured,
        "lastPollSuccess": device.get("last_poll_success"),
        "lastPollFailure": device.get("last_poll_failure"),
        "lastError": device.get("last_error"),
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/devices", response_model=list[AquaWizDeviceInfo])
async def list_aquawiz_devices(_: dict = Depends(require_auth)):
    """List all AquaWiz devices with their current status."""
    devices = await _mgr.list_devices()
    results = []
    for d in devices:
        if (d.get("integration") or "").lower() == "aquawiz":
            results.append(await _device_info(d))
    return results


@router.post("/discover", response_model=AquaWizDiscoverResponse)
async def discover_aquawiz_devices(request: AqwWizAuthRequest, _: dict = Depends(require_auth)):
    """Authenticate with AquaWiz and return available devices for this account.

    The access_token is returned for device registration but is NOT stored
    in the device config at this stage — it is retrieved fresh from the
    Credential Vault during polling.
    """
    secrets = {"username": request.username, "password": request.password}
    try:
        result = await _integration.discover_devices(secrets)
    except AquaWizIntegrationError as e:
        logger.warning("AquaWiz discover failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    # Build a set of already-registered serials so the client can distinguish
    # "already registered" from "available to add"
    registered_serials: set[str] = set()
    for d in await _mgr.list_devices():
        if (d.get("integration") or "").lower() == "aquawiz":
            s = (d.get("config") or {}).get("serial", "").upper()
            if s:
                registered_serials.add(s)

    return AquaWizDiscoverResponse(
        success=result["success"],
        message=result["message"],
        devices=[
            AquaWizDiscoveredDevice(
                serial=d["serial"],
                type=d["type"],
                registered=d["serial"].upper() in registered_serials,
            )
            for d in result.get("devices", [])
        ],
        accessToken=result.get("access_token", ""),
    )


@router.post("/register", response_model=AquaWizRegisterResponse)
async def register_aquawiz_device(request: AquaWizRegisterRequest, _: dict = Depends(require_auth)):
    """Register a new AquaWiz device after validating credentials and device access."""
    # Step 1: Discover devices to validate credentials and find the target
    secrets = {"username": request.username, "password": request.password}
    try:
        discover_result = await _integration.discover_devices(secrets)
    except AquaWizIntegrationError as e:
        logger.warning("AquaWiz register discover failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    if not discover_result["success"]:
        raise HTTPException(status_code=401, detail=discover_result["message"])

    # Step 2: Validate the requested serial exists
    devices = discover_result.get("devices", [])
    target_serial = request.serial.upper()
    matching = [d for d in devices if d["serial"].upper() == target_serial]
    if not matching:
        available = ", ".join(d["serial"] for d in devices) or "none"
        raise HTTPException(
            status_code=404,
            detail=f"Device '{request.serial}' not found. Available: {available}",
        )

    # Step 3: Check for existing device with same serial
    existing = await _mgr.find_by_integration("aquawiz", request.serial)
    if existing:
        logger.info("AquaWiz device %s already registered — returning 409", request.serial)
        raise HTTPException(
            status_code=409,
            detail=f"AquaWiz {request.serial} is already registered",
        )

    # Step 4: Create the device record first (needed for device_id in credentials)
    # NOTE: access_token is stored in the Credential Vault only - never in devices.config
    device_data = {
        "name": f"AquaWiz {request.serial}",
        "device_type": request.deviceType.lower(),
        "brand": "AquaWiz",
        "model": request.deviceType.upper(),
        "integration": "aquawiz",
        "poll_interval_seconds": request.pollIntervalSeconds,
        "config": {
            "serial": request.serial,
            "device_type": request.deviceType.lower(),
        },
    }
    device = await _mgr.create_device(device_data)

    # Step 5: Store AquaWiz credentials in the Credential Vault and link to device
    credential_ref = str(uuid.uuid4())
    await _cred_mgr.store_secrets(credential_ref, {
        "username": request.username,
        "password": request.password,
        "access_token": discover_result.get("access_token", ""),
    }, device_id=device["id"])

    # Step 6: Link credential_ref to the device
    await _mgr.update_device(device["id"], {"credential_ref": credential_ref})

    logger.info("Registered AquaWiz device %s (serial=%s)", device["id"], request.serial)

    return AquaWizRegisterResponse(
        deviceId=device["id"],
        name=device["name"],
        serial=request.serial,
        deviceType=request.deviceType.lower(),
        message=f"AquaWiz {request.serial} registered successfully",
    )


@router.post("/poll/{device_id}", response_model=AquaWizPollResponse)
async def poll_aquawiz_device(device_id: str, _: dict = Depends(require_auth)):
    """Poll a specific AquaWiz device for current readings."""
    try:
        device = await _mgr.get_device(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")

    if (device.get("integration") or "").lower() != "aquawiz":
        raise HTTPException(status_code=400, detail="Not an AquaWiz device")

    cred_ref = device.get("credential_ref")
    if not cred_ref:
        raise HTTPException(status_code=400, detail="No credentials configured")

    secrets = await _cred_mgr.get_secrets(cred_ref) or {}
    if not secrets.get("username") or not secrets.get("password"):
        raise HTTPException(status_code=400, detail="Incomplete credentials")

    config = device.get("config") or {}
    serial = config.get("serial", "")
    device_type = config.get("device_type", "")
    access_token = secrets.get("access_token", "")

    if not access_token:
        raise HTTPException(status_code=400, detail="Device missing access token in credential vault")
    if not serial:
        raise HTTPException(status_code=400, detail="Device missing serial in config")

    try:
        readings = await _integration.poll(device_id, secrets, config)
    except AquaWizIntegrationError as e:
        logger.warning("AquaWiz poll failed for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=str(e))

    # Persist readings to brand-specific storage (never overwrite)
    if readings:
        await _data_mgr.store(device_id, serial, readings)

    # Build reading timestamp from the first reading's timestamp
    reading_ts = None
    if readings:
        reading_ts = readings[0].get("timestamp")

    return AquaWizPollResponse(
        deviceId=device_id,
        deviceType=device_type,
        serial=serial,
        readings=[
            AquaWizReading(name=r["parameter_name"], value=r["value"], unit=r.get("unit", ""))
            for r in readings
        ],
        readingTimestamp=reading_ts,
        lastUpdated=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/{device_id}/test", response_model=DeviceTestResponse)
async def test_aquawiz_connection(device_id: str, _: dict = Depends(require_auth)):
    """Test AquaWiz device connection using real integration."""
    try:
        device = await _mgr.get_device(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")

    if (device.get("integration") or "").lower() != "aquawiz":
        raise HTTPException(status_code=400, detail="Not an AquaWiz device")

    cred_ref = device.get("credential_ref")
    secrets = {}
    if cred_ref:
        secrets = await _cred_mgr.get_secrets(cred_ref) or {}

    config = device.get("config") or {}
    serial = config.get("serial", "")
    device_type = config.get("device_type", "")

    try:
        result = await _integration.test_connection(
            secrets, device_serial=serial, device_type=device_type
        )
    except AquaWizIntegrationError as e:
        logger.warning("AquaWiz test failed for device %s: %s", device_id, e)
        error_type = _map_aquawiz_error(str(e))
        safe_message = _AQUAWIZ_USER_MESSAGES.get(error_type, "AquaWiz connection failed. Please try again.")
        result = {
            "success": False,
            "message": safe_message,
            "error_type": error_type,
            "details": None,
        }
    if cred_ref:
        await _cred_mgr.mark_tested(cred_ref, result.get("success", False), result.get("message", ""))

    return DeviceTestResponse(**result)
