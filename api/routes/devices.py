import logging
from fastapi import APIRouter, HTTPException, status, Depends, Body
from pydantic import BaseModel, Field
from devices.manager import DeviceManager, DeviceNotFoundError
from creds.manager import CredentialManager
from api.routes.auth import require_auth
from config import DATABASE_PATH

logger = logging.getLogger("reef_ai_hub.api.devices")
router = APIRouter(prefix="/api/devices", tags=["devices"])
manager = DeviceManager(DATABASE_PATH)
cred_mgr = CredentialManager(DATABASE_PATH)


# ─── Schemas ────────────────────────────────────────────────────────────────

class DeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    device_type: str
    brand: str = Field(..., min_length=1, max_length=50)
    model: str | None = None
    integration: str = Field(..., min_length=1, max_length=50)
    poll_interval_seconds: int = Field(default=300, ge=60)
    config: dict = Field(default_factory=dict)


class DeviceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    device_type: str | None = None
    brand: str | None = Field(None, min_length=1, max_length=50)
    model: str | None = Field(None, max_length=100)
    integration: str | None = Field(None, min_length=1, max_length=50)
    enabled: bool | None = None
    poll_interval_seconds: int | None = Field(None, ge=60)
    config: dict | None = None


class DeviceResponse(BaseModel):
    id: str
    name: str
    device_type: str
    brand: str
    model: str | None = None
    integration: str
    enabled: bool
    poll_interval_seconds: int
    status: str
    config: dict
    credentials_configured: bool
    last_poll_attempt: str | None = None
    last_poll_success: str | None = None
    last_poll_failure: str | None = None
    next_scheduled_poll: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str


class DeviceTestResponse(BaseModel):
    success: bool
    message: str
    details: dict | None = None


# ─── Helpers ───────────────────────────────────────────────────────────────

async def _enrich_device(device: dict) -> dict:
    meta = await cred_mgr.get_metadata(device["id"])
    device["_credentials_configured"] = bool(meta and meta.get("configured"))
    return device


def _mask_device(device: dict) -> dict:
    result = dict(device)
    result.pop("credential_ref", None)
    result.pop("_credentials_configured", None)
    config = result.get("config", {})
    for key in list(config.keys()):
        lower = key.lower()
        if any(s in lower for s in ("password", "token", "secret", "key", "credential", "api_key")):
            config.pop(key)
    result["config"] = config
    result["credentials_configured"] = device.get("_credentials_configured", False)
    result["last_error"] = None
    return result


# ─── Endpoints ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[DeviceResponse])
async def list_devices(_: dict = Depends(require_auth)):
    devices = await manager.list_devices()
    results = []
    for d in devices:
        d = await _enrich_device(d)
        results.append(_mask_device(d))
    return results


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, _: dict = Depends(require_auth)):
    try:
        device = await manager.get_device(device_id)
        return _mask_device(await _enrich_device(device))
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def create_device(payload: DeviceCreate, _: dict = Depends(require_auth)):
    device = await manager.create_device(payload.model_dump())
    cred_meta = await cred_mgr.create(device["id"], device.get("integration", "unknown"))
    await manager.update_device(device["id"], {"credential_ref": cred_meta["credential_ref"]})
    result = await manager.get_device(device["id"])
    return _mask_device(await _enrich_device(result))


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: str, payload: DeviceUpdate, _: dict = Depends(require_auth)):
    try:
        device = await manager.update_device(device_id, payload.model_dump(exclude_none=True))
        return _mask_device(await _enrich_device(device))
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: str, _: dict = Depends(require_auth)):
    try:
        cred_meta = await cred_mgr.get_metadata(device_id)
        if cred_meta:
            await cred_mgr.delete(cred_meta["credential_ref"])
        await manager.delete_device(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")


@router.post("/{device_id}/test", response_model=DeviceTestResponse)
async def test_device_connection(device_id: str, _: dict = Depends(require_auth)):
    try:
        device = await manager.get_device(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")

    cred_ref = device.get("credential_ref")
    secrets = {}
    if cred_ref:
        secrets = await cred_mgr.get_secrets(cred_ref) or {}

    # Integration test - honest "not implemented" for Phase 1B
    result = {
        "success": False,
        "message": f"{device.get('integration', 'Unknown').title()} integration not yet implemented",
        "details": None,
    }
    if cred_ref:
        await cred_mgr.mark_tested(cred_ref, result.get("success", False), result.get("message", ""))
    return DeviceTestResponse(**result)


@router.post("/{device_id}/credentials", status_code=status.HTTP_200_OK)
async def update_credentials(device_id: str, payload: dict = Body(...), _: dict = Depends(require_auth)):
    try:
        device = await manager.get_device(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")

    cred_ref = device.get("credential_ref")
    if not cred_ref:
        cred_meta = await cred_mgr.create(device_id, device.get("integration", "unknown"))
        cred_ref = cred_meta["credential_ref"]
        await manager.update_device(device_id, {"credential_ref": cred_ref})

    secrets = {k: v for k, v in payload.items() if v}
    if secrets:
        await cred_mgr.store_secrets(cred_ref, secrets)
    return {"status": "ok", "credential_ref": cred_ref}


@router.get("/{device_id}/credentials", status_code=status.HTTP_200_OK)
async def get_credentials_status(device_id: str, _: dict = Depends(require_auth)):
    try:
        device = await manager.get_device(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")

    cred_ref = device.get("credential_ref")
    if not cred_ref:
        return {"configured": False}

    meta = await cred_mgr.get_metadata(device_id)
    if not meta:
        return {"configured": False}

    return {
        "configured": bool(meta.get("configured")),
        "credential_type": meta.get("credential_type"),
        "last_tested_at": meta.get("last_tested_at"),
        "last_test_result": meta.get("last_test_result"),
    }
