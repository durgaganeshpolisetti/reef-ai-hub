import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("reef_ai_hub.creds")

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

KEYRING_SERVICE = "reef-ai-hub"


class CredentialVault:
    """Stores per-device secrets in OS-protected storage.

    Uses OS keyring when available (Windows Credential Manager,
    macOS Keychain, Linux Secret Service). Falls back to a local
    JSON file only when keyring is unavailable.

    Never persists secrets to SQLite.
    """

    def store(self, credential_ref: str, data: dict) -> None:
        payload = json.dumps(data)
        if HAS_KEYRING:
            try:
                keyring.set_password(KEYRING_SERVICE, credential_ref, payload)
                return
            except Exception as e:
                logger.warning("keyring.set_password failed: %s", e)
        self._fallback_store(credential_ref, payload)

    def retrieve(self, credential_ref: str) -> dict | None:
        if HAS_KEYRING:
            try:
                raw = keyring.get_password(KEYRING_SERVICE, credential_ref)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.warning("keyring.get_password failed: %s", e)
                return None
        return None

    def delete(self, credential_ref: str) -> None:
        if HAS_KEYRING:
            try:
                keyring.delete_password(KEYRING_SERVICE, credential_ref)
            except Exception:
                pass


vault = CredentialVault()
