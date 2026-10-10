"""In-process HTTP latency + status counters for Wave 4 observability."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any

_lock = threading.Lock()
_started_at = time.time()
_max_samples = int(__import__("os").getenv("REQUEST_METRICS_MAX_SAMPLES", "5000") or "5000")
_latencies_ms: deque[float] = deque(maxlen=max(100, _max_samples))
_status_counts: dict[str, int] = {}
_path_counts: dict[str, int] = {}
_error_5xx = 0
_error_429 = 0
_total_requests = 0


def record_request(*, path: str, method: str, status: int, latency_ms: float) -> None:
    bucket = f"{method.upper()} {path}"
    with _lock:
        global _total_requests, _error_5xx, _error_429
        _total_requests += 1
        _latencies_ms.append(float(latency_ms))
        _status_counts[str(status)] = _status_counts.get(str(status), 0) + 1
        _path_counts[bucket] = _path_counts.get(bucket, 0) + 1
        if status >= 500:
            _error_5xx += 1
        if status == 429:
            _error_429 += 1


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def latency_snapshot() -> dict[str, Any]:
    with _lock:
        samples = list(_latencies_ms)
        total = _total_requests
        s5 = _error_5xx
        s429 = _error_429
        statuses = dict(_status_counts)
        paths = dict(_path_counts)
    return {
        "sample_count": len(samples),
        "total_requests": total,
        "p50_ms": _percentile(samples, 50),
        "p95_ms": _percentile(samples, 95),
        "p99_ms": _percentile(samples, 99),
        "error_5xx": s5,
        "error_429": s429,
        "status_counts": statuses,
        "top_paths": dict(sorted(paths.items(), key=lambda kv: kv[1], reverse=True)[:20]),
        "uptime_sec": int(time.time() - _started_at),
    }
