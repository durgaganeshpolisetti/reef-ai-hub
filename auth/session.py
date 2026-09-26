import hashlib
import hmac
import os
import time
import logging

logger = logging.getLogger("reef_ai_hub.auth")

# In-memory session store for Phase 1B.
# Production should swap this for Redis or a DB-backed store.
_sessions: dict[str, dict] = {}
_session_counter = 0


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> int:
    return int(time.time())


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with HMAC-SHA256. Returns (hash, salt)."""
    if salt is None:
        salt = os.urandom(16).hex()
    pw_hash = hmac.new(salt.encode(), password.encode(), hashlib.sha256).hexdigest()
    return pw_hash, salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    """Verify a password against a stored hash."""
    computed, _ = hash_password(password, salt)
    return hmac.compare_digest(computed, pw_hash)


def create_session(username: str, ttl_seconds: int = 86400) -> str:
    """Create a new session token. Returns the token string."""
    global _session_counter
    _session_counter += 1
    token = os.urandom(32).hex()
    _sessions[token] = {
        "username": username,
        "created_at": _now_iso(),
        "expires_at": _now_ts() + ttl_seconds,
        "counter": _session_counter,
    }
    return token


def validate_session(token: str | None) -> dict | None:
    """Validate a session token. Returns session dict or None."""
    if not token:
        return None
    session = _sessions.get(token)
    if not session:
        return None
    if session["expires_at"] < _now_ts():
        del _sessions[token]
        return None
    return session


def revoke_session(token: str) -> None:
    """Revoke a session token."""
    _sessions.pop(token, None)


def revoke_all_sessions(username: str) -> int:
    """Revoke all sessions for a user. Returns count revoked."""
    to_remove = [t for t, s in _sessions.items() if s["username"] == username]
    for t in to_remove:
        del _sessions[t]
    return len(to_remove)
