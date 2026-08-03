"""Lead Map Scanner — rate limit, cooldown, single-flight, Google quota guard."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core.lead_scanner_settings import (
    lead_google_cooldown_sec,
    lead_ip_rate_limit_per_min,
    lead_scan_cooldown_sec,
    lead_user_rate_limit_per_min,
)

_LOG = logging.getLogger("google_map_lead_guard")

_guard_lock = threading.Lock()
_google_cooldown_until: dict[int, float] = {}
_scan_cooldown_until: dict[str, float] = {}  # user_id|cache_key -> mono
_user_hits: dict[int, deque[float]] = defaultdict(deque)
_ip_hits: dict[str, deque[float]] = defaultdict(deque)
_scan_locks: dict[int, threading.Lock] = {}


def _mono() -> float:
    return time.monotonic()


def _utc_iso_from_mono(deadline_mono: float) -> str:
    remaining = max(0.0, deadline_mono - _mono())
    return datetime.fromtimestamp(time.time() + remaining, tz=timezone.utc).isoformat()


def _prune(hits: deque[float], *, window_sec: float = 60.0) -> None:
    cutoff = _mono() - window_sec
    while hits and hits[0] < cutoff:
        hits.popleft()


def _check_rate(hits: deque[float], limit: int) -> bool:
    _prune(hits)
    return len(hits) < limit


def _record_hit(hits: deque[float]) -> None:
    hits.append(_mono())


def is_google_cooldown(user_id: int) -> bool:
    with _guard_lock:
        until = _google_cooldown_until.get(user_id)
        if until is None:
            return False
        if _mono() >= until:
            _google_cooldown_until.pop(user_id, None)
            return False
        return True


def google_cooldown_until_iso(user_id: int) -> str | None:
    with _guard_lock:
        until = _google_cooldown_until.get(user_id)
        if until is None or _mono() >= until:
            return None
        return _utc_iso_from_mono(until)


def mark_google_cooldown(user_id: int, *, retry_after_sec: int | None = None) -> str:
    cooldown = retry_after_sec if retry_after_sec and retry_after_sec > 0 else lead_google_cooldown_sec()
    cooldown = min(max(int(cooldown), 30), 600)
    with _guard_lock:
        _google_cooldown_until[user_id] = _mono() + cooldown
        return _utc_iso_from_mono(_google_cooldown_until[user_id])


def ensure_google_api_allowed(user_id: int, *, action: str) -> None:
    if not is_google_cooldown(user_id):
        return
    until = google_cooldown_until_iso(user_id)
    _LOG.warning(
        "lead scanner Google API blocked user_id=%s action=%s cooldown_until=%s",
        user_id,
        action,
        until,
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "google_quota_cooldown",
            "message": "Google Places API tạm thời bị giới hạn. Vui lòng thử lại sau vài phút.",
            "cooldown_until": until,
        },
    )


def check_user_rate_limit(user_id: int) -> None:
    with _guard_lock:
        hits = _user_hits[user_id]
        if not _check_rate(hits, lead_user_rate_limit_per_min()):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "rate_limited",
                    "message": "Bạn thao tác quá nhanh. Vui lòng đợi 1 phút rồi thử lại.",
                },
            )
        _record_hit(hits)


def check_ip_rate_limit(client_ip: str | None) -> None:
    ip = str(client_ip or "").strip() or "unknown"
    with _guard_lock:
        hits = _ip_hits[ip]
        if not _check_rate(hits, lead_ip_rate_limit_per_min()):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "rate_limited",
                    "message": "Quá nhiều yêu cầu từ IP này. Vui lòng thử lại sau.",
                },
            )
        _record_hit(hits)


def check_scan_cooldown(user_id: int, cache_key: str) -> None:
    key = f"{user_id}|{cache_key}"
    with _guard_lock:
        until = _scan_cooldown_until.get(key)
        if until is None:
            return
        if _mono() >= until:
            _scan_cooldown_until.pop(key, None)
            return
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "scan_cooldown",
                "message": "Vừa quét cùng từ khóa/khu vực. Vui lòng đợi trước khi quét lại.",
                "cooldown_until": _utc_iso_from_mono(until),
            },
        )


def mark_scan_cooldown(user_id: int, cache_key: str) -> None:
    key = f"{user_id}|{cache_key}"
    with _guard_lock:
        _scan_cooldown_until[key] = _mono() + lead_scan_cooldown_sec()


def _user_scan_lock(user_id: int) -> threading.Lock:
    with _guard_lock:
        lock = _scan_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _scan_locks[user_id] = lock
        return lock


class LeadScanGuard:
    """Single-flight: mỗi user chỉ 1 quét đang chạy."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self._lock = _user_scan_lock(user_id)
        self.acquired = False

    def __enter__(self) -> LeadScanGuard:
        self.acquired = self._lock.acquire(blocking=False)
        if not self.acquired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "scan_in_progress",
                    "message": "Đang có lượt quét khác — vui lòng đợi hoàn tất.",
                },
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.acquired:
            self._lock.release()
