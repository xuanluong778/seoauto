"""Feature flags for server-side sessions + refresh rotation (WAVE 8)."""

from __future__ import annotations

import os
import time


def server_sessions_enabled() -> bool:
    return os.getenv("SERVER_SESSIONS_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def legacy_user_jwt_blocked() -> bool:
    """When True, user JWT must include sid+jti (session) or typ=service."""
    if not server_sessions_enabled():
        return False
    raw = (os.getenv("JWT_BLOCK_LEGACY_USER") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def service_tokens_enabled() -> bool:
    return os.getenv("JWT_SERVICE_TOKENS_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def jwt_legacy_cutoff_unix() -> int | None:
    """After this Unix timestamp, legacy user JWT (no sid/jti) is always rejected."""
    raw = (os.getenv("JWT_LEGACY_CUTOFF_UNIX") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def legacy_cutoff_active() -> bool:
    cutoff = jwt_legacy_cutoff_unix()
    if cutoff is None:
        return legacy_user_jwt_blocked()
    return int(time.time()) >= int(cutoff)


def jwt_access_expire_minutes() -> int:
    raw = (os.getenv("JWT_ACCESS_EXPIRE_MINUTES") or "20").strip()
    try:
        return max(15, min(30, int(raw)))
    except ValueError:
        return 20


def refresh_token_expire_days() -> int:
    raw = (os.getenv("REFRESH_TOKEN_EXPIRE_DAYS") or "30").strip()
    try:
        return max(1, min(90, int(raw)))
    except ValueError:
        return 30


def refresh_token_http_only_only() -> bool:
    return os.getenv("REFRESH_TOKEN_HTTPONLY_ONLY", "1").strip().lower() in ("1", "true", "yes", "on")
