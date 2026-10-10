"""IP rate limiting by route prefix — Redis first, in-process fallback."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from threading import Lock

_LOG = logging.getLogger(__name__)

_lock = Lock()
_hits: dict[str, list[float]] = defaultdict(list)
_redis_client = None
_redis_last_fail = 0.0
_REDIS_RETRY_SEC = 5.0

# Auth / credential endpoints — production must NOT silently fall back to memory.
SENSITIVE_RATE_PREFIXES = frozenset(
    {
        "/auth/login",
        "/auth/register",
        "/auth/otp/send",
        "/auth/otp/verify",
    }
)

# (max_requests, window_seconds)
RATE_RULES: dict[str, tuple[int, int]] = {
    "/auth/login": (20, 300),
    "/auth/register": (10, 3600),
    # 10/giờ đủ dùng; chống spam làm Gmail lọc + vô hiệu OTP cũ.
    "/auth/otp/send": (10, 3600),
    "/auth/otp/verify": (30, 3600),
    "/affiliate/track-click": (60, 3600),
    "/content-ai/auto-update/fetch-url": (40, 3600),
    "/content-ai/auto-update/generate": (30, 3600),
    "/content-ai/auto-update/publish": (20, 3600),
    "/content-ai/auto-update/restore": (15, 3600),
    "/analyze": (30, 3600),
    "/analyze/url-seo-scoreboard": (30, 3600),
    "/content-ai/wordpress/publish": (25, 3600),
    "/content-ai/images/generate": (40, 3600),
    # Costly / previously-public SEO tools (IP bucket; auth+credit still required)
    "/schema-generator": (40, 3600),
    "/api/schema-preview": (120, 3600),
    "/api/schema/validate": (120, 3600),
    "/api/keyword-intelligence": (40, 3600),
    "/api/serp/keyword-intelligence": (40, 3600),
}


def _client_ip(request) -> str:
    from app.services.trusted_proxy import resolve_client_ip

    return resolve_client_ip(request)


def _get_redis():
    """Lazy Redis client; caches failures briefly to avoid storming."""
    global _redis_client, _redis_last_fail
    if os.getenv("RATE_LIMIT_REDIS", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    now = time.time()
    if _redis_client is not None:
        return _redis_client
    if now - _redis_last_fail < _REDIS_RETRY_SEC:
        return None
    try:
        import redis

        url = (os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.4, socket_timeout=0.4)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as exc:
        _redis_last_fail = now
        _redis_client = None
        _LOG.debug("rate_limit_redis_unavailable: %s", exc)
        return None


def _check_redis(bucket_key: str, max_calls: int, window: int) -> bool | None:
    """
    Sliding window via Redis sorted set.
    Returns True/False on success, None if Redis unavailable (caller falls back).
    """
    r = _get_redis()
    if r is None:
        return None
    key = f"rl:v1:{bucket_key}"
    now = time.time()
    window_start = now - float(window)
    member = f"{now:.6f}:{os.getpid()}"
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        results = pipe.execute()
        count = int(results[1] or 0)
        if count >= max_calls:
            return False
        pipe2 = r.pipeline()
        pipe2.zadd(key, {member: now})
        pipe2.expire(key, int(window) + 5)
        pipe2.execute()
        return True
    except Exception as exc:
        global _redis_client, _redis_last_fail
        _redis_client = None
        _redis_last_fail = time.time()
        _LOG.debug("rate_limit_redis_error: %s", exc)
        return None


def _check_memory(bucket_key: str, max_calls: int, window: int) -> bool:
    now = time.time()
    with _lock:
        arr = [t for t in _hits[bucket_key] if now - t < window]
        if len(arr) >= max_calls:
            _hits[bucket_key] = arr
            return False
        arr.append(now)
        _hits[bucket_key] = arr
    return True


def check_request_rate_limit(path: str, client_ip: str, *, method: str = "") -> tuple[bool, str | None]:
    """
    IP rate limit by longest matching prefix.

    GET /analyze/technical/jobs/{id} is job polling (every ~2s for minutes) and
    must not share the expensive POST /analyze bucket (30/hour).
    """
    p = str(path or "")
    if p in ("/health", "/ready"):
        return True, None
    m = str(method or "GET").upper()
    if m in ("GET", "HEAD", "OPTIONS") and (
        p == "/analyze/technical/jobs" or p.startswith("/analyze/technical/jobs/")
    ):
        return True, None
    rule_key = None
    for prefix in sorted(RATE_RULES.keys(), key=len, reverse=True):
        if p == prefix or p.startswith(prefix + "/") or p.endswith(prefix):
            rule_key = prefix
            break
    if not rule_key:
        return True, None
    max_calls, window = RATE_RULES[rule_key]
    bucket_key = f"{rule_key}:{client_ip}"
    redis_ok = _check_redis(bucket_key, max_calls, window)
    if redis_ok is not None:
        return (True, None) if redis_ok else (False, rule_key)

    # Redis unavailable
    from app.core.runtime import is_production

    if is_production() and rule_key in SENSITIVE_RATE_PREFIXES:
        _LOG.critical(
            "rate_limit_redis_required_fail_closed path=%s ip=%s",
            rule_key,
            client_ip,
        )
        return False, rule_key

    if not _check_memory(bucket_key, max_calls, window):
        return False, rule_key
    return True, None


def clear_rate_limit(path_prefix: str | None = None, client_ip: str | None = None) -> int:
    """Xóa bucket rate-limit (dùng khi ops cần mở khóa OTP cho IP bị kẹt)."""
    removed = 0
    with _lock:
        keys = list(_hits.keys())
        for key in keys:
            rule_part, _, ip_part = key.partition(":")
            if path_prefix and rule_part != path_prefix:
                continue
            if client_ip and ip_part != client_ip:
                continue
            del _hits[key]
            removed += 1
    r = _get_redis()
    if r is not None:
        try:
            pattern = "rl:v1:"
            if path_prefix and client_ip:
                pattern = f"rl:v1:{path_prefix}:{client_ip}"
            elif path_prefix:
                pattern = f"rl:v1:{path_prefix}:*"
            elif client_ip:
                pattern = f"rl:v1:*:{client_ip}"
            else:
                pattern = "rl:v1:*"
            for key in r.scan_iter(match=pattern, count=100):
                r.delete(key)
                removed += 1
        except Exception as exc:
            _LOG.debug("rate_limit_redis_clear_failed: %s", exc)
    return removed
