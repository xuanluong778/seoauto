"""Feature flag + canary rollout for Content AI async generation (WAVE 2)."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from fastapi import Request

from app.models.user import User


def content_ai_async_flag_enabled() -> bool:
    return os.getenv("CONTENT_AI_ASYNC_GENERATION", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def content_ai_async_shadow_enabled() -> bool:
    return os.getenv("CONTENT_AI_ASYNC_SHADOW", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def rollout_percent() -> int:
    try:
        return max(0, min(100, int(os.getenv("CONTENT_AI_ASYNC_ROLLOUT_PERCENT", "0"))))
    except (TypeError, ValueError):
        return 0


def _user_bucket(user_id: int) -> int:
    digest = hashlib.sha256(f"{int(user_id)}:content_ai_async_v2".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def async_enabled_for_user(user: User, *, request: Request | None = None) -> bool:
    if not content_ai_async_flag_enabled():
        return False
    pct = rollout_percent()
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    if request is not None:
        force = (request.headers.get("X-Content-AI-Async") or "").strip().lower()
        if force in ("1", "true", "yes", "force"):
            return True
        if force in ("0", "false", "no", "sync"):
            return False
    return _user_bucket(int(user.id)) < pct


def rollout_status(user: User | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "flag": content_ai_async_flag_enabled(),
        "shadow": content_ai_async_shadow_enabled(),
        "rollout_percent": rollout_percent(),
    }
    if user is not None:
        out["enabled_for_user"] = async_enabled_for_user(user)
        out["user_bucket"] = _user_bucket(int(user.id))
    return out
