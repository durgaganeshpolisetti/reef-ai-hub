# Reef AI Hub â€” Project Status

## Current Phase
AquaWiz integration and device-management stabilization.

## Verified Completed

- FastAPI/Uvicorn Reef AI Hub is operational.
- Hub authentication uses Bearer tokens.
- GET /health, GET /docs, and GET /openapi.json are public as designed.
- Normal device/data/control APIs are protected.
- Generic device registry is implemented in the devices table.
- Device uniqueness is based on integration + serial.
- Duplicate registration returns conflict instead of silently overwriting.
- Device credentials use the credential vault with credential_ref linkage.
- AquaWiz discovery calls the real AquaWiz API.
- AquaWiz registration works.
- AquaWiz Test Connection uses stored credentials and the real AquaWiz API.
- Delete Device works through authenticated requests.
- AquaWiz historical storage uses the separate aquawiz_data table.
- Test isolation was improved so AquaWiz tests do not depend on the real reef_ai_hub.db.
- Backend AquaWiz tests have repeatedly been verified at 67 passing.
- Development database is:
  C:\Users\Ganesh\Projects\reef_ai_hub\reef_ai_hub.db

## Database Structure

Main generic registry:
devices

Credential metadata:
device_credentials

AquaWiz historical measurements:
aquawiz_data

Other existing tables include:
alerts
commands
connection_history
equipment
telemetry
api_users

Do not delete/reset the development database during normal coding tasks.

## AquaWiz API Contract

Base:
https://server.aquawiz.net

Authentication:
POST /api/v1/KH/auth

Request:
{
  "user": "<username>",
  "password": "<password>",
  "token": {
    "access_token": ""
  }
}

Response includes:
access_token
user.devices

user.devices is list[str], for example:
[
  "KH1-00-02544",
  "CA1-00-00646"
]

Device data:
POST /api/v1/KH/{serial}/all_field

## AquaWiz Internal/User-Facing Models

Internal:
kh
carx

User-facing:
KHA
CRA

Do not change the internal values solely for display-label changes.

## Current Dashboard Read-Path Work

The Dashboard AquaWiz API was returning HTTP 500.

Investigation identified a backend serialization bug in:
api/routes/aquawiz.py

The _device_info() helper incorrectly read model from config JSON even though registration stores model in the top-level devices.model column.

Required correction:
device.get("model", "")

instead of:
device.get("config", {}).get("model", "")

This fix must be fully implemented and manually verified.

Dashboard must:
- read registered AquaWiz devices from devices
- tolerate zero aquawiz_data rows
- return registered devices with latest=null/equivalent when no telemetry exists
- return latest data from aquawiz_data when telemetry exists
- never require Flutter to call AquaWiz directly

## Current Data State

The development database was intentionally cleaned before onboarding tests.

Two AquaWiz devices were subsequently registered through the app:
- KH1-00-02544
- CA1-00-00646

Historical aquawiz_data was previously empty before polling starts.

## Next Phase

After the Dashboard read path is confirmed:
AquaWiz polling â†’ /all_field â†’ normalization â†’ aquawiz_data â†’ Dashboard latest values/history.

Do not implement the full recurring polling scheduler until the Dashboard read path is validated.

## Important Rules

- Read CLAUDE.md first.
- Read this file before starting a new phase.
- Do not scan the entire repository unless necessary.
- Start with explicitly named relevant files.
- Do not modify unrelated code.
- Do not run the emulator unless explicitly requested.
- Do not weaken authentication.
- Do not put vendor passwords or tokens in devices.config or normal API responses.
- Do not log secrets.
- Tests must not depend on the real development DB; use isolated test databases.
