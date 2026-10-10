"""Tenant-scoped embedding cache: content_hash → vector bytes."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import numpy as np

_CACHE_VERSION = int(os.getenv("EMBEDDING_CACHE_VERSION", "2"))
_DEFAULT_TTL = int(os.getenv("EMBEDDING_CACHE_TTL", "604800"))
_MAX_MEM = int(os.getenv("EMBEDDING_CACHE_MAX_KEYS", "8000"))

_MEM: dict[str, np.ndarray] = {}
_MEM_ORDER: list[str] = []


def content_hash(text: str) -> str:
    normalized = " ".join(str(text or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def tenant_scope_key(tenant_scope: str) -> str:
    scope = str(tenant_scope or "global").strip() or "global"
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]


def redis_cache_key(*, tenant_scope: str, digest: str) -> str:
    return f"emb:v{_CACHE_VERSION}:{tenant_scope_key(tenant_scope)}:{digest}"


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    except Exception:
        return None


def cache_get(*, tenant_scope: str, digest: str) -> np.ndarray | None:
    key = redis_cache_key(tenant_scope=tenant_scope, digest=digest)
    r = _redis()
    if r:
        try:
            raw = r.get(key)
            if raw:
                return np.frombuffer(raw, dtype=np.float32)
        except Exception:
            pass
    return _MEM.get(key)


def cache_set(*, tenant_scope: str, digest: str, vec: np.ndarray, ttl: int | None = None) -> None:
    key = redis_cache_key(tenant_scope=tenant_scope, digest=digest)
    v = np.asarray(vec, dtype=np.float32).flatten()
    r = _redis()
    if r:
        try:
            r.setex(key, int(ttl or _DEFAULT_TTL), v.tobytes())
            return
        except Exception:
            pass
    if len(_MEM_ORDER) >= _MAX_MEM and key not in _MEM:
        old = _MEM_ORDER.pop(0)
        _MEM.pop(old, None)
    _MEM[key] = v.copy()
    if key not in _MEM_ORDER:
        _MEM_ORDER.append(key)


def cache_stats() -> dict[str, Any]:
    r = _redis()
    mem_keys = len(_MEM)
    redis_info: dict[str, Any] = {}
    if r:
        try:
            redis_info = dict(r.info("memory"))
        except Exception:
            pass
    return {
        "cache_version": _CACHE_VERSION,
        "in_memory_keys": mem_keys,
        "redis_used_memory_human": redis_info.get("used_memory_human"),
        "redis_used_memory": redis_info.get("used_memory"),
    }


def bump_tenant_cache_version(tenant_scope: str) -> int:
    """Invalidate tenant embedding cache by bumping version counter."""
    r = _redis()
    ver_key = f"emb:ver:{tenant_scope_key(tenant_scope)}"
    if not r:
        return _CACHE_VERSION
    try:
        return int(r.incr(ver_key))
    except Exception:
        return _CACHE_VERSION


# Metrics (process-local; wave5 script aggregates)
_METRICS: dict[str, int] = {"hit": 0, "miss": 0}


def record_cache_hit() -> None:
    _METRICS["hit"] = int(_METRICS.get("hit", 0)) + 1


def record_cache_miss() -> None:
    _METRICS["miss"] = int(_METRICS.get("miss", 0)) + 1


def cache_hit_rate() -> float:
    hit = int(_METRICS.get("hit", 0))
    miss = int(_METRICS.get("miss", 0))
    total = hit + miss
    return round(hit / total, 4) if total else 0.0


def reset_metrics() -> None:
    _METRICS["hit"] = 0
    _METRICS["miss"] = 0


def metrics_snapshot() -> dict[str, Any]:
    return {
        "cache_hits": int(_METRICS.get("hit", 0)),
        "cache_misses": int(_METRICS.get("miss", 0)),
        "cache_hit_rate": cache_hit_rate(),
        **cache_stats(),
    }
