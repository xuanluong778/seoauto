"""Redis NX locks so duplicate Celery Beat processes cannot double-run ticks."""

from __future__ import annotations

import logging
import os
import socket
from typing import Any

_LOG = logging.getLogger(__name__)


def acquire_beat_tick_lock(task_name: str, *, ttl_seconds: int | None = None) -> bool:
    """
    Try to acquire a short-lived Redis lock for a beat task.

    Returns True if this process should run the tick; False if another holder exists.
    If Redis is unavailable, returns True (best-effort — PM2 instances:1 is primary guard).
    """
    ttl = ttl_seconds
    if ttl is None:
        ttl = int(os.getenv("CELERY_BEAT_TICK_LOCK_TTL", "240"))
    ttl = max(30, min(ttl, 3600))
    key = f"celery:beat:lock:{task_name}"
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return True
    try:
        import redis

        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        token = f"{socket.gethostname()}:{os.getpid()}"
        ok = client.set(key, token, nx=True, ex=ttl)
        if not ok:
            _LOG.warning("beat_tick_lock_skipped task=%s holder=%s", task_name, client.get(key))
            return False
        return True
    except Exception as exc:
        _LOG.warning("beat_tick_lock_redis_unavailable task=%s err=%s", task_name, exc)
        return True


def beat_lock_status(task_name: str) -> dict[str, Any]:
    url = (os.getenv("REDIS_URL") or "").strip()
    key = f"celery:beat:lock:{task_name}"
    if not url:
        return {"key": key, "ttl": None, "holder": None}
    try:
        import redis

        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        return {"key": key, "ttl": client.ttl(key), "holder": client.get(key)}
    except Exception as exc:
        return {"key": key, "error": type(exc).__name__}
