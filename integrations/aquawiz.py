"""AquaWiz integration for Reef AI Hub.

Communicates with AquaWiz API to discover devices and fetch readings.
All AquaWiz tokens and credentials remain in the secure Credential Vault
and are never exposed through REST responses.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from integrations.catalog import IntegrationCatalog

logger = logging.getLogger("reef_ai_hub.integrations.aquawiz")

AQUAWIZ_BASE = "https://server.aquawiz.net/api/v1"

# Sub-paths by device type (lowercase per API spec)
_DEVICE_ENDPOINTS = {
    "kh": "KH",
    "carx": "KH",  # CaRx uses the same /api/v1/KH/ path
}


class AquaWizIntegrationError(Exception):
    """Raised when AquaWiz communication fails."""


class AquaWizIntegration:
    name = "aquawiz"
    credential_fields = ["username", "password"]

    def __init__(self):
        self.catalog = IntegrationCatalog()

    async def test_connection(self, secrets: dict) -> dict:
        """Authenticate with AquaWiz and return device list."""
        username = secrets.get("username", "")
        password = secrets.get("password", "")
        if not username or not password:
            return {
                "success": False,
                "message": "Missing username or password",
                "details": None,
            }

        try:
            async with aiohttp.ClientSession() as session:
                token_info = await self._auth_login(session, username, password)
                access_token = token_info["access_token"]
                devices = token_info.get("user", {}).get("devices", [])
                return {
                    "success": True,
                    "message": f"Connected — {len(devices)} device(s) found",
                    "details": {
                        "devices": [
                            {"serial": d.get("serial"), "type": self._detect_device_type(d)}
                            for d in devices
                        ],
                        "access_token": access_token,
                    },
                }
        except aiohttp.ClientResponseError as e:
            logger.warning("AquaWiz auth failed: %s %s", e.status, e.message)
            return {
                "success": False,
                "message": f"Authentication failed (HTTP {e.status})",
                "details": None,
            }
        except Exception as e:
            logger.error("AquaWiz connection test error: %s", e)
            return {
                "success": False,
                "message": str(e)[:200],
                "details": None,
            }

    async def poll(self, device_id: str, secrets: dict, config: dict) -> list[dict]:
        """Poll AquaWiz for device readings.

        Returns a list of normalized telemetry dicts. Never returns
        raw AquaWiz API responses or tokens.
        """
        username = secrets.get("username", "")
        password = secrets.get("password", "")
        access_token = config.get("access_token", "")
        if not username or not password or not access_token:
            raise AquaWizIntegrationError("Missing credentials or access token")

        serial = config.get("serial", "")
        device_type = config.get("device_type", "").lower()
        if not serial or not device_type:
            raise AquaWizIntegrationError("Device missing serial or type")

        endpoint_prefix = _DEVICE_ENDPOINTS.get(device_type)
        if not endpoint_prefix:
            raise AquaWizIntegrationError(f"Unsupported device type: {device_type}")

        url = f"{AQUAWIZ_BASE}/{endpoint_prefix}/{serial}/all_field"

        payload = {
            "user": username,
            "password": password,
            "serial": serial,
            "token": {"access_token": access_token},
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 401:
                        raise AquaWizIntegrationError("AquaWiz token expired")
                    if resp.status != 200:
                        raise AquaWizIntegrationError(f"AquaWiz API error: HTTP {resp.status}")
                    data = await resp.json()
        except aiohttp.ClientError as e:
            raise AquaWizIntegrationError(f"Network error: {e}")
        except Exception as e:
            raise AquaWizIntegrationError(str(e))

        return self._normalize(data, device_type, serial)

    # ─── Private helpers ──────────────────────────────────────────

    async def _auth_login(self, session: aiohttp.ClientSession, username: str, password: str) -> dict:
        """Authenticate with AquaWiz and return token + device list.

        IMPORTANT: The returned dict includes the access_token. The caller
        (integration manager) is responsible for storing it in the
        Credential Vault config, NOT in telemetry or API responses.
        """
        payload = {
            "user": username,
            "password": password,
            "token": {"access_token": ""},
        }
        async with session.post(
            f"{AQUAWIZ_BASE}/KH/auth", json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                raise AquaWizIntegrationError(f"Auth failed: HTTP {resp.status}")
            data = await resp.json()
        return data

    def _detect_device_type(self, device: dict) -> str:
        """Infer device type from AquaWiz device info."""
        serial = (device.get("serial") or "").upper()
        if serial.startswith("KH"):
            return "kh"
        if serial.startswith("CA"):
            return "carx"
        return "other"

    def _normalize(self, raw: dict, device_type: str, serial: str) -> list[dict]:
        """Map AquaWiz raw fields to normalized Reef AI telemetry.

        Only the explicitly requested fields are included.
        Raw response data is NOT forwarded.
        """
        now = datetime.now(timezone.utc).isoformat()
        readings_ts = _parse_timestamp(raw.get("latest_time"))

        entries = []
        get = raw.get

        if device_type == "kh":
            kh_val = _safe_div(get("latest_kh"), 1000)
            ph_val = _safe_div(get("latest_ph1"), 1000)
            kh_target = _safe_div(get("field8"), 1000)
            kh_dosing = _safe_int(get("latest_dos"))

            if kh_val is not None:
                entries.append(_telemetry("kh", kh_val, "dKH", readings_ts or now))
            if ph_val is not None:
                entries.append(_telemetry("ph", ph_val, "", readings_ts or now))
            if kh_target is not None:
                entries.append(_telemetry("kh_target", kh_target, "dKH", readings_ts or now))
            if kh_dosing is not None:
                entries.append(_telemetry("kh_dosing", kh_dosing, "ml", readings_ts or now))

        elif device_type == "carx":
            delta_kh = _safe_div(get("latest_kh"), 1000)
            co2_bubbles = _safe_int(get("latest_dos"))

            if delta_kh is not None:
                entries.append(_telemetry("delta_kh", delta_kh, "dKH", readings_ts or now))
            if co2_bubbles is not None:
                entries.append(_telemetry("co2_bubbles", co2_bubbles, "", readings_ts or now))

        return entries


def _safe_div(value: Any, divisor: float) -> float | None:
    """Safely divide a numeric value, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value) / divisor
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    """Safely convert to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(raw_ts: Any) -> str | None:
    """Convert AquaWiz epoch-millis timestamp to ISO-8601 string."""
    if raw_ts is None:
        return None
    try:
        ms = int(raw_ts)
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError):
        return None


def _telemetry(name: str, value: float, unit: str, timestamp: str) -> dict:
    """Build a normalized telemetry entry."""
    return {
        "device_id": "",  # filled by caller
        "parameter_name": name,
        "value": value,
        "unit": unit,
        "timestamp": timestamp,
        "status": "normal",
        "source": "aquawiz",
        "raw": {},
    }
