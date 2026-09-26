# Reef AI Hub — API Endpoint & Credential Documentation

> **Source of truth:** This document is derived directly from the current server
> source code (`C:\Users\Ganesh\Projects\reef_ai_hub\`). If the server code changes,
> this document must be updated to match.

---

## 1. Complete REST Endpoint Table

| Method | Path | Purpose | Authentication | Request | Response | Source File |
|--------|------|---------|----------------|---------|----------|-------------|
| GET | `/health` | Liveness probe | **PUBLIC** | — | `{ status: "ok" }` | `api/routes/server.py` |
| GET | `/server` | Server name, version, timestamp | **REQUIRED** | — | `{ name, version, status, timestamp }` | `api/routes/server.py` |
| POST | `/api/auth/login` | Authenticate with username/password | None (login entry point) | `{ username, password }` | `{ access_token, token_type, username }` | `api/routes/auth.py` |
| POST | `/api/auth/logout` | Revoke current session token | **REQUIRED** | — | `{ status: "ok" }` | `api/routes/auth.py` |
| GET | `/api/auth/status` | Check if a token is valid | **REQUIRED** | — | `{ authenticated, username }` | `api/routes/auth.py` |
| GET | `/api/auth/users` | List all API users | **REQUIRED** | — | `[ { user_id, username, auth_type, enabled, ... } ]` | `api/routes/auth.py` |
| POST | `/api/auth/setup` | Create initial admin user (one-time) | None (setup entry point) | `{ username, password }` | `{ access_token, token_type, username }` | `api/routes/auth.py` |
| GET | `/api/devices` | List all devices (credentials masked) | **REQUIRED** | — | `[ DeviceResponse ]` | `api/routes/devices.py` |
| GET | `/api/devices/{device_id}` | Get single device (credentials masked) | **REQUIRED** | — | `DeviceResponse` | `api/routes/devices.py` |
| POST | `/api/devices` | Create new device (auto-creates credential ref) | **REQUIRED** | `DeviceCreate` | `DeviceResponse` | `api/routes/devices.py` |
| PUT | `/api/devices/{device_id}` | Update device fields | **REQUIRED** | `DeviceUpdate` | `DeviceResponse` | `api/routes/devices.py` |
| DELETE | `/api/devices/{device_id}` | Delete device + cascade credential ref | **REQUIRED** | — | 204 No Content | `api/routes/devices.py` |
| POST | `/api/devices/{device_id}/test` | Test device connection (Phase 1B stub) | **REQUIRED** | — | `{ success, message, details }` | `api/routes/devices.py` |
| POST | `/api/devices/{device_id}/credentials` | Store device credentials in vault | **REQUIRED** | `{ <credential_key>: <value> }` | `{ status, credential_ref }` | `api/routes/devices.py` |
| GET | `/api/devices/{device_id}/credentials` | Get credential status (configured? last tested?) | **REQUIRED** | — | `{ configured, credential_type, last_tested_at, last_test_result }` | `api/routes/devices.py` |
| GET | `/api/aquawiz/devices` | List all AquaWiz devices with status | **REQUIRED** | — | `[ AquaWizDeviceInfo ]` | `api/routes/aquawiz.py` |
| POST | `/api/aquawiz/poll/{device_id}` | Poll AquaWiz device, returns normalized telemetry | **REQUIRED** | — | `AquaWizPollResponse` | `api/routes/aquawiz.py` |
| POST | `/api/aquawiz/{device_id}/test` | Test AquaWiz connection (uses real integration) | **REQUIRED** | — | `{ success, message, details }` | `api/routes/aquawiz.py` |

**Total: 17 application endpoints across 14 paths. See Sections 2–4 for the breakdown.**

---

## 2. Public Endpoints

The following endpoints do not require authentication.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Basic Hub health check — returns `{ status: "ok" }` |
| GET | `/docs` | Swagger UI — interactive API documentation |
| GET | `/openapi.json` | OpenAPI schema definition — required by Swagger UI |

These endpoints are intentionally public so the Swagger UI can load and a health
check can verify the server is running.

---

## 3. Authentication Entry Point

| Method | Path | Requirement |
|--------|------|-------------|
| POST | `/api/auth/login` | Valid Hub username and password |

`/api/auth/login` does not require an existing bearer token. The request body
must contain valid Hub credentials (`username` and `password`).

On success, the server returns a session token. This token must be included as
`Authorization: Bearer <TOKEN>` on all subsequent protected requests.

`/api/auth/login` is documented in Swagger as **Authentication Entry Point**.
It is not an anonymous data endpoint — valid credentials are required.

**Never place tokens in URLs, query parameters, documentation examples, or logs.**

---

## 4. Protected Endpoints

All endpoints not listed in Section 2 or Section 3 require a valid bearer token.

### 4.1 Authentication & Session

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/logout` | Revoke the current session token |
| GET | `/api/auth/status` | Check if a bearer token is valid |
| GET | `/api/auth/users` | List all API users |

### 4.2 Server

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/server` | Server name, version, and timestamp |

### 4.3 Devices

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/devices` | List all devices (credentials masked) |
| GET | `/api/devices/{device_id}` | Get single device (credentials masked) |
| POST | `/api/devices` | Create new device |
| PUT | `/api/devices/{device_id}` | Update device fields |
| DELETE | `/api/devices/{device_id}` | Delete device |
| POST | `/api/devices/{device_id}/test` | Test device connection |
| POST | `/api/devices/{device_id}/credentials` | Store device credentials |
| GET | `/api/devices/{device_id}/credentials` | Get credential status |

### 4.4 AquaWiz

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/aquawiz/devices` | List AquaWiz devices |
| POST | `/api/aquawiz/poll/{device_id}` | Poll AquaWiz for readings |
| POST | `/api/aquawiz/{device_id}/test` | Test AquaWiz connection |

---

## 5. Authentication & Session Details

### 5.1 Login

- **Endpoint:** `POST /api/auth/login`
- **Authentication:** None required (this is the credential entry point)
- **Request body:** `{ "username": "<USERNAME>", "password": "<PASSWORD>" }`
- **Success response (200):** `{ "access_token": "<TOKEN>", "token_type": "bearer", "username": "<USERNAME>" }`
- **Failure response (401):** `{ "detail": "Invalid username or password" }`
- **Source:** `api/routes/auth.py` → `login()`

### 5.2 Logout

- **Endpoint:** `POST /api/auth/logout`
- **Authentication:** Bearer token required
- **Request:** No body
- **Response:** `{ "status": "ok" }`
- **Behavior:** Revokes the session token from the in-memory store
- **Source:** `api/routes/auth.py` → `logout()`

### 5.3 Token / Session Validation

- **Endpoint:** `GET /api/auth/status`
- **Authentication:** Bearer token required (middleware-enforced)
- **Response:** `{ "authenticated": true/false, "username": "<USERNAME>" | null }`
- **Source:** `api/routes/auth.py` → `auth_status()`

### 5.4 Token / Session Expiration

- Default TTL: **86400 seconds (24 hours)** from creation
- Expired tokens are automatically removed on validation attempt
- Session validation: `auth.session.validate_session(token)` — returns `None` if missing or expired

### 5.5 Token / Session Storage & Restart Behavior

- **Storage:** In-memory Python dictionary (`_sessions: dict[str, dict]`)
- **File:** `auth/session.py`
- **Restart behavior:** All sessions are lost on server restart. Clients must re-authenticate.
- **Production note:** Code comments indicate this should be replaced with Redis or DB-backed store.

### 5.6 Admin Setup

- **Endpoint:** `POST /api/auth/setup`
- **Authentication:** None required
- **Behavior:** Creates the first admin user. Returns 409 Conflict if users already exist.
- **Request:** `{ "username": "<USERNAME>", "password": "<PASSWORD>" }`
- **Response:** Same as login — `{ "access_token", "token_type", "username" }`
- **Source:** `api/routes/auth.py` → `setup_admin()`

### 5.7 Password Hashing

- **Algorithm:** HMAC-SHA256 with per-user random salt
- **Salt:** 16 random bytes (hex-encoded via `os.urandom(16).hex()`)
- **Verification:** Constant-time comparison via `hmac.compare_digest()`
- **Source:** `auth/session.py` → `hash_password()`, `verify_password()`

### 5.8 Authentication Middleware

- **File:** `api/middleware/auth.py` → `AuthMiddleware(BaseHTTPMiddleware)`
- **Protected paths:** All paths except those in `PUBLIC_PATHS`
- **Public paths (no auth required):**
  - `/health`
  - `/api/auth/login`
  - `/api/auth/setup`
  - `/docs`
  - `/openapi.json`
- **Authentication transport:** `Authorization: Bearer <TOKEN>` HTTP header ONLY
- **Query-string authentication:** NOT SUPPORTED — tokens passed via `?authorization=` are rejected
- **Failure response:** 401 with `{ "detail": "Authentication required" }`
- **Middleware role:** Reject requests without a valid `Authorization: Bearer` header before route handlers run
- **Source:** `api/app.py` → `app.add_middleware(AuthMiddleware)`

---

## 6. Swagger / OpenAPI Security

### 6.1 Bearer Security Scheme

The OpenAPI definition declares a `BearerAuth` security scheme of type `http`
with scheme `bearer`. This causes the Swagger UI to display the standard
**Authorize** button.

### 6.2 Protected Operation Marking

All endpoints except the public paths (`/health`, `/docs`, `/openapi.json`,
`/api/auth/login`, `/api/auth/setup`) are marked with:

```yaml
security:
  - BearerAuth: []
```

This tells Swagger that a bearer token is required to call those operations.

### 6.3 Testing from Swagger

1. Open `GET /docs`
2. Call `POST /api/auth/login` with `{ "username": "<USERNAME>", "password": "<PASSWORD>" }`
3. Click the **Authorize** button (top-right of Swagger UI)
4. Enter `Bearer <TOKEN>` (include the word "Bearer" followed by a space)
5. Test protected endpoints

### 6.4 ReDoc

`/redoc` is NOT listed in `PUBLIC_PATHS`. It requires authentication.

---

## 7. Security Checklist

| Check | Status | Notes |
|-------|--------|-------|
| GET /health is public | VERIFIED | In `PUBLIC_PATHS` |
| GET /docs is public | VERIFIED | In `PUBLIC_PATHS` |
| GET /openapi.json is public | VERIFIED | In `PUBLIC_PATHS` |
| POST /api/auth/login requires valid username/password | VERIFIED | Validated via `LoginRequest` model + `AuthManager.authenticate()` |
| GET /api/auth/status requires bearer token | VERIFIED | Removed from `PUBLIC_PATHS` |
| POST /api/auth/logout requires bearer token | VERIFIED | Protected by AuthMiddleware |
| POST /api/auth/setup cannot overwrite initialized auth | VERIFIED | Returns 409 if users already exist |
| GET /server requires bearer token | VERIFIED | Protected by AuthMiddleware |
| Device APIs require bearer token | VERIFIED | All `/api/devices/*` routes use `Depends(require_auth)` |
| Credential APIs require bearer token | VERIFIED | All credential endpoints use `Depends(require_auth)` |
| Telemetry APIs require bearer token | NOT VERIFIED | Telemetry manager exists but no REST endpoints expose it yet |
| Control APIs require bearer token | NOT VERIFIED | No control API endpoints currently implemented |
| WebSocket endpoints require authentication | N/A | No WebSocket endpoints implemented |
| Raw credentials are never returned in API responses | VERIFIED | `_mask_device()` strips sensitive keys and `credential_ref` |
| Raw credentials are never logged | VERIFIED | Passwords hashed at user creation; device secrets in OS keyring |
| Raw credentials not stored in SQLite | VERIFIED | Device credentials stored in OS keyring via `CredentialVault`; SQLite stores only metadata |
| Tokens are never placed in URLs | VERIFIED | Tokens are passed via `Authorization` header only |

---

## 8. Credential Inventory

### 4A. Hub Authentication (Flutter App → Reef AI Hub)

Hub users are stored in SQLite, table `api_users`. The table is created by
`database/connection.py → init_database()` using `CREATE TABLE IF NOT EXISTS`.

| Column | Type | Notes |
|--------|------|-------|
| user_id | TEXT | UUID primary key |
| username | TEXT | Unique identifier |
| password_hash | TEXT | HMAC-SHA256 hash, never plaintext |
| salt | TEXT | Per-user random 16-byte salt (hex) |
| auth_type | TEXT | e.g., "password" |
| enabled | INTEGER | 1=active, 0=disabled |
| created_at | TEXT | ISO 8601 |
| updated_at | TEXT | ISO 8601 |
| last_login | TEXT | ISO 8601, nullable |

**Password storage:** Passwords are never stored in plaintext. They are hashed
using HMAC-SHA256 with a per-user random salt (`auth/session.py → hash_password()`).
Verification uses constant-time comparison (`hmac.compare_digest`).

**Multiple users:** The schema supports multiple Hub users. No hard limit exists.

**No default user:** No default username/password is created automatically.
The first account must be explicitly bootstrapped via `POST /api/auth/setup`.

| Credential Domain | Credential | Storage | File / Class | API Exposed |
|-------------------|------------|---------|-------------|-------------|
| Hub | Hub username | SQLite `api_users` table | `auth/manager.py` → `AuthManager` | Never in API responses |
| Hub | Hub password hash | SQLite `api_users` table | `auth/session.py` → `hash_password()` | Never in API responses |
| Hub | Hub session (server-side) | In-memory Python dict | `auth.session._sessions` | Never exposed |

**Note:** Flutter-side Hub credentials are currently stored in plain Dart memory only.
No persistent storage (SharedPreferences, secure storage, etc.) is implemented.
Credentials are lost on app restart.

### 4B. Device Authentication (Reef AI Hub → Aquarium Devices)

| Credential Domain | Credential | Storage | File / Class | API Exposed |
|-------------------|------------|---------|-------------|-------------|
| AquaWiz | AquaWiz username | OS keyring (primary) / fallback file | `creds/vault.py` → `CredentialVault` | Never in REST responses |
| AquaWiz | AquaWiz password | OS keyring (primary) / fallback file | `creds/vault.py` → `CredentialVault` | Never in REST responses |
| AquaWiz | AquaWiz access token | Stored in device `config` JSON (SQLite) | `devices.manager` → `config` column | Not exposed by API (in device config) |
| Kamoer | Not yet implemented | — | — | — |
| INKBIRD | Not yet implemented | — | — | — |
| Generic | Not yet implemented | — | — | — |

**Note:** Hub server-side device credential fields (per integration catalog):
- AquaWiz: `["username", "password"]`
- Kamoer, INKBIRD, Generic: not yet defined

---

## 9. Flutter → Hub API Map

| Flutter Function | Method | Hub Path | Authentication | Source File |
|-----------------|--------|----------|----------------|-------------|
| `HubService.isHealthy()` | GET | `/health` | None (public) | `lib/services/hub_service.dart` |
| `HubService.getServerInfo()` | GET | `/server` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.login()` | POST | `/api/auth/login` | None (login entry) | `lib/services/hub_service.dart` |
| `HubService.logout()` | POST | `/api/auth/logout` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.getAuthStatus()` | GET | `/api/auth/status` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.setupAdmin()` | POST | `/api/auth/setup` | None (setup entry) | `lib/services/hub_service.dart` |
| `HubService.fetchDevices()` | GET | `/api/devices` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.fetchDevice(id)` | GET | `/api/devices/{id}` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.registerDevice()` | POST | `/api/devices` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.updateDevice()` | PUT | `/api/devices/{id}` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.deleteDevice()` | DELETE | `/api/devices/{id}` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.testDeviceConnection()` | POST | `/api/devices/{id}/test` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.getCredentialsStatus()` | GET | `/api/devices/{id}/credentials` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.updateCredentials()` | POST | `/api/devices/{id}/credentials` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.fetchAquaWizDevices()` | GET | `/api/aquawiz/devices` | Bearer token | `lib/services/hub_service.dart` |
| `HubService.pollAquaWizDevice()` | POST | `/api/aquawiz/poll/{deviceId}` | Bearer token | `lib/services/hub_service.dart` |

---

## 10. AquaWiz External API

### 6.1 Base URL

`https://server.aquawiz.net/api/v1`

### 6.2 Authentication Endpoint

- **Method:** POST
- **Path:** `/api/v1/KH/auth`
- **Request body:** `{ "user": "<USERNAME>", "password": "<PASSWORD>", "token": { "access_token": "" } }`
- **Response:** `{ "access_token": "<TOKEN>", "user": { "devices": [...] } }`
- **Purpose:** Obtain an AquaWiz access token + discover paired devices
- **Source:** `integrations/aquawiz.py` → `_auth_login()`

### 6.3 Device Data Endpoint

- **Method:** POST
- **Path:** `/api/v1/KH/{serial}/all_field`
- **Request body:** `{ "user": "<USERNAME>", "password": "<PASSWORD>", "serial": "<SERIAL>", "token": { "access_token": "<TOKEN>" } }`
- **Response:** Raw AquaWiz field data (not forwarded to Flutter — only normalized fields are returned)
- **Device types:** KH (KH Monitor), CaRx (Calcium Reactor — uses same `/KH/` path)
- **Source:** `integrations/aquawiz.py` → `poll()`

### 6.4 Token Handling (AquaWiz)

- AquaWiz access tokens are stored in the Hub's device `config` JSON column (SQLite)
- Tokens are refreshed during poll if expired
- Raw AquaWiz tokens are never returned in Hub REST API responses

---

## 11. Current vs Future

### Currently Implemented

- Hub server with HTTP REST API
- Hub user authentication (password-based, HMAC-SHA256)
- In-memory session tokens (24h TTL)
- Device CRUD (list, get, create, update, delete)
- Device credential vault (OS keyring)
- AquaWiz integration (poll + test)
- Flutter app with dashboard and settings screens

### Planned / Future

- Persistent session store (Redis or DB)
- Additional device integrations (Kamoer, INKBIRD, Generic)
- Telemetry REST endpoints (manager exists, not wired to routes)
- Alert and command endpoints
- Equipment management endpoints
- WebSocket real-time updates
- HTTPS support
- Rate limiting on login
- Token refresh mechanism
