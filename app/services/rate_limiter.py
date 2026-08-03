"""Simple in-process rate limiting (per IP / per route prefix)."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

_lock = Lock()
_hits: dict[str, list[float]] = defaultdict(list)

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
}


def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    if request.client:
        return str(request.client.host or "unknown")[:64]
    return "unknown"


def check_request_rate_limit(path: str, client_ip: str) -> tuple[bool, str | None]:
    rule_key = None
    for prefix in sorted(RATE_RULES.keys(), key=len, reverse=True):
        if path == prefix or path.startswith(prefix + "/") or path.endswith(prefix):
            rule_key = prefix
            break
    if not rule_key:
        return True, None
    max_calls, window = RATE_RULES[rule_key]
    bucket_key = f"{rule_key}:{client_ip}"
    now = time.time()
    with _lock:
        arr = [t for t in _hits[bucket_key] if now - t < window]
        if len(arr) >= max_calls:
            return False, rule_key
        arr.append(now)
        _hits[bucket_key] = arr
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
    return removed
