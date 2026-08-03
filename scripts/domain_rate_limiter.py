"""
Per-host crawl throttling using Redis (sliding minute counter + min gap).

Env:
  CRAWL_DOMAIN_MAX_RPM=30
  CRAWL_DOMAIN_MIN_INTERVAL_MS=500
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

_MIN_INTERVAL = float(os.getenv("CRAWL_DOMAIN_MIN_INTERVAL_MS", "500")) / 1000.0
_MAX_RPM = max(1, int(os.getenv("CRAWL_DOMAIN_MAX_RPM", "30")))


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
    except Exception:
        return None


def _host_key(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        if h.startswith("www."):
            h = h[4:]
        return h or "unknown"
    except Exception:
        return "unknown"


def acquire_domain_slot(url: str, *, timeout_sec: float = 120.0) -> bool:
    """Block until slot available or timeout. Returns False if timed out."""
    r = _redis()
    host = _host_key(url)
    key_window = f"crawl:ratelimit:{host}:minute"
    key_last = f"crawl:ratelimit:{host}:last"
    deadline = time.monotonic() + timeout_sec

    while time.monotonic() < deadline:
        if not r:
            time.sleep(_MIN_INTERVAL)
            return True
        try:
            n = int(r.incr(key_window))
            if n == 1:
                r.expire(key_window, 65)
            if n > _MAX_RPM:
                r.decr(key_window)
                time.sleep(0.2)
                continue
            last = r.get(key_last)
            now = time.time()
            if last is not None:
                gap = now - float(last)
                if gap < _MIN_INTERVAL:
                    r.decr(key_window)
                    time.sleep(_MIN_INTERVAL - gap + 0.02)
                    continue
            r.set(key_last, str(now), ex=300)
            return True
        except Exception:
            time.sleep(_MIN_INTERVAL)
            return True
    return False
