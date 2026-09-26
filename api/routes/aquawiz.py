import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from devices.manager import DeviceManager, DeviceNotFoundError
from creds.manager import CredentialManager
from api.routes.auth import require_auth
from integrations.aquawiz import AquaWizIntegration, AquaWizIntegrationError
from config import DATABASE_PATH

logger = logging.getLogger("reef_ai_hub.api.aquawiz")
router = APIRouter(prefix="/api/aquawiz", tags=["aquawiz"])
_mgr = DeviceManager(DATABASE_PATH)
_cred_mgr = CredentialManager(DATABASE_PATH)
_integration = AquaWizIntegration()


class DeviceTestResponse(BaseModel):
    success: bool
    message: str
    details: dict | None = None


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
    enabled: bool
    credentialsConfigured: bool
    lastPollSuccess: str | None = None
    lastPollFailure: str | None = None
    lastError: str | None = None


# ─── Helpers ───────────────────────────────────────────────────────────────

async def _device_info(device: dict) -> dict:
    meta = await _cred_mgr.get_metadata(device["id"])
    configured = bool(meta and meta.get("configured"))
    return {
        "deviceId": device["id"],
        "deviceType": device.get("device_type", "other"),
        "serial": device.get("config", {}).get("serial", ""),
        "name": device.get("name", ""),
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
    access_token = config.get("access_token", "")
    serial = config.get("serial", "")
    device_type = config.get("device_type", "")

    if not access_token or not serial:
        raise HTTPException(status_code=400, detail="Device missing serial or access token")

    # Refresh token in config if needed
    poll_config = dict(config)
    if not poll_config.get("access_token"):
        poll_config["access_token"] = access_token

    try:
        readings = await _integration.poll(device_id, secrets, poll_config)
    except AquaWizIntegrationError as e:
        logger.warning("AquaWiz poll failed for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=str(e))

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

    result = await _integration.test_connection(secrets)
    if cred_ref:
        await _cred_mgr.mark_tested(cred_ref, result.get("success", False), result.get("message", ""))

    return DeviceTestResponse(**result)
