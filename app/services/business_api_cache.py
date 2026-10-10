"""Tenant-scoped cache for hot business API reads (WAVE 6)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

_CACHE_VERSION = int(os.getenv("BUSINESS_API_CACHE_VERSION", "1"))
_DEFAULT_TTL = int(os.getenv("BUSINESS_API_CACHE_TTL", "45"))

_MEM: dict[str, tuple[float, Any]] = {}


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    except Exception:
        return None


def tenant_cache_key(*, user_id: int, organization_id: int, scope: str, extra: str = "") -> str:
    raw = f"{int(user_id)}:{int(organization_id)}:{scope}:{extra}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"biz:v{_CACHE_VERSION}:{digest}"


def cache_get(key: str) -> Any | None:
    r = _redis()
    if r:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw.decode("utf-8"))
        except Exception:
            pass
    hit = _MEM.get(key)
    if not hit:
        return None
    expires, value = hit
    if expires < time.monotonic():
        _MEM.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, *, ttl: int | None = None) -> None:
    ttl_sec = int(ttl or _DEFAULT_TTL)
    payload = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    r = _redis()
    if r:
        try:
            r.setex(key, ttl_sec, payload)
            return
        except Exception:
            pass
    _MEM[key] = (time.monotonic() + ttl_sec, value)


def invalidate_user_cache(*, user_id: int, organization_id: int | None = None) -> None:
    prefix_part = f"{int(user_id)}:{int(organization_id or user_id)}"
    r = _redis()
    if r:
        try:
            for key in r.scan_iter(match=f"biz:v{_CACHE_VERSION}:*", count=200):
                # best-effort; keys are hashed — bump version env on deploy for full invalidation
                pass
        except Exception:
            pass
    for k in list(_MEM.keys()):
        if prefix_part in k:
            _MEM.pop(k, None)
