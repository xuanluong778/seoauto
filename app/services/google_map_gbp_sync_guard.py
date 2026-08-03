"""Google Map SEO — cache, single-flight sync & rate-limit guard cho GBP."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.services.google_map_gbp_api import ACCOUNTS_LIST_ENDPOINT, GBP_QUOTA_FRIENDLY_MSG, GbpApiError

_LOG = logging.getLogger("google_map_gbp.guard")

ACCOUNTS_CACHE_TTL_SEC = 600.0  # 10 phút
LOCATIONS_CACHE_TTL_SEC = 600.0
DEFAULT_COOLDOWN_SEC = 120
MAX_COOLDOWN_SEC = 600
SYNC_LOCK_TTL_SEC = 300

_accounts_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_locations_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_rate_limit_until: dict[int, float] = {}  # monotonic
_sync_locks: dict[str, threading.Lock] = {}
_guard_lock = threading.Lock()


def _mono() -> float:
    return time.monotonic()


def _utc_iso_from_mono(deadline_mono: float) -> str:
    remaining = max(0.0, deadline_mono - _mono())
    return datetime.fromtimestamp(time.time() + remaining, tz=timezone.utc).isoformat()


def _redis_client():
    try:
        import redis

        url = (os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()
        return redis.Redis.from_url(url, decode_responses=True)
    except Exception:
        return None


def _sync_lock_key(user_id: int, connection_id: int | None = None) -> str:
    cid = int(connection_id) if connection_id else 0
    return f"gbp:sync:{int(user_id)}:{cid}"


def _thread_lock(key: str) -> threading.Lock:
    with _guard_lock:
        lock = _sync_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _sync_locks[key] = lock
        return lock


@contextmanager
def gbp_sync_lock(user_id: int, connection_id: int | None = None) -> Iterator[bool]:
    """Single-flight sync — Redis NX lock, fallback in-process lock."""
    key = _sync_lock_key(user_id, connection_id)
    r = _redis_client()
    redis_key = f"lock:{key}"
    acquired = False
    use_thread_fallback = False
    thread_lock: threading.Lock | None = None

    if r is not None:
        try:
            acquired = bool(r.set(redis_key, "1", nx=True, ex=SYNC_LOCK_TTL_SEC))
        except Exception:
            _LOG.warning("GBP Redis lock unavailable user_id=%s connection_id=%s", user_id, connection_id)
            use_thread_fallback = True
    else:
        use_thread_fallback = True

    if use_thread_fallback:
        thread_lock = _thread_lock(key)
        acquired = thread_lock.acquire(blocking=False)

    try:
        yield acquired
    finally:
        if r is not None and acquired and not use_thread_fallback:
            try:
                r.delete(redis_key)
            except Exception:
                pass
        elif thread_lock is not None and acquired:
            thread_lock.release()


def get_accounts_cached(user_id: int) -> list[dict[str, Any]] | None:
    with _guard_lock:
        row = _accounts_cache.get(user_id)
        if not row:
            return None
        ts, data = row
        if _mono() - ts > ACCOUNTS_CACHE_TTL_SEC:
            _accounts_cache.pop(user_id, None)
            return None
        return list(data)


def set_accounts_cached(user_id: int, accounts: list[dict[str, Any]]) -> None:
    with _guard_lock:
        _accounts_cache[user_id] = (_mono(), list(accounts))


def get_locations_cached(user_id: int, account_resource: str) -> list[dict[str, Any]] | None:
    cache_key = f"{int(user_id)}:{str(account_resource or '').strip()}"
    with _guard_lock:
        row = _locations_cache.get(cache_key)
        if not row:
            return None
        ts, data = row
        if _mono() - ts > LOCATIONS_CACHE_TTL_SEC:
            _locations_cache.pop(cache_key, None)
            return None
        return list(data)


def set_locations_cached(user_id: int, account_resource: str, locations: list[dict[str, Any]]) -> None:
    cache_key = f"{int(user_id)}:{str(account_resource or '').strip()}"
    with _guard_lock:
        _locations_cache[cache_key] = (_mono(), list(locations))


def invalidate_accounts_cache(user_id: int) -> None:
    with _guard_lock:
        _accounts_cache.pop(user_id, None)
        prefix = f"{int(user_id)}:"
        for k in list(_locations_cache.keys()):
            if k.startswith(prefix):
                _locations_cache.pop(k, None)


def is_rate_limited(user_id: int) -> bool:
    with _guard_lock:
        until = _rate_limit_until.get(user_id)
        if until is None:
            return False
        if _mono() >= until:
            _rate_limit_until.pop(user_id, None)
            return False
        return True


def rate_limit_until_iso(user_id: int) -> str | None:
    with _guard_lock:
        until = _rate_limit_until.get(user_id)
        if until is None or _mono() >= until:
            return None
        return _utc_iso_from_mono(until)


def retry_after_seconds(user_id: int) -> int | None:
    with _guard_lock:
        until = _rate_limit_until.get(user_id)
        if until is None:
            return None
        remaining = until - _mono()
        if remaining <= 0:
            return None
        return max(1, int(remaining + 0.999))


def mark_rate_limited(
    user_id: int,
    *,
    retry_after_sec: int | None = None,
    endpoint: str = ACCOUNTS_LIST_ENDPOINT,
    reason: str = "google_429",
) -> str:
    if retry_after_sec and retry_after_sec > 0:
        cooldown = min(int(retry_after_sec), MAX_COOLDOWN_SEC)
    else:
        cooldown = DEFAULT_COOLDOWN_SEC
    with _guard_lock:
        _rate_limit_until[user_id] = _mono() + cooldown
        until_iso = _utc_iso_from_mono(_rate_limit_until[user_id])
    _LOG.warning(
        "GBP rate limit user_id=%s endpoint=%s reason=%s retry_after_seconds=%s until=%s",
        user_id,
        endpoint,
        reason,
        cooldown,
        until_iso,
    )
    return until_iso


def ensure_google_api_allowed(user_id: int, source_action: str) -> None:
    """Trong cooldown 429 — tuyệt đối không gọi Google API."""
    if not is_rate_limited(user_id):
        return
    retry_sec = retry_after_seconds(user_id)
    _LOG.info(
        "GBP API blocked user_id=%s endpoint=%s source_action=%s status_code=429 reason=cooldown retry_after=%s",
        user_id,
        ACCOUNTS_LIST_ENDPOINT,
        source_action,
        retry_sec,
    )
    raise GbpApiError(
        GBP_QUOTA_FRIENDLY_MSG,
        status_code=429,
        endpoint=ACCOUNTS_LIST_ENDPOINT,
        retry_count=0,
        retry_after_sec=retry_sec,
        user_id=user_id,
    )


def friendly_sync_error(exc: BaseException) -> str:
    if isinstance(exc, GbpApiError) and exc.is_quota:
        return GBP_QUOTA_FRIENDLY_MSG
    code = str(exc)
    if "429" in code or "quota" in code.lower():
        return GBP_QUOTA_FRIENDLY_MSG
    return str(exc)[:480]


class GbpSyncGuard:
    """Single-flight: mỗi user (+ optional connection) chỉ 1 tiến trình đồng bộ."""

    def __init__(self, user_id: int, connection_id: int | None = None) -> None:
        self.user_id = user_id
        self.connection_id = connection_id
        self.acquired = False
        self._lock_cm = gbp_sync_lock(user_id, connection_id)

    def __enter__(self) -> GbpSyncGuard:
        self.acquired = self._lock_cm.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock_cm.__exit__(exc_type, exc, tb)
