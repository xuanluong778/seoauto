"""Auth/session HTTP counters for anomaly detection (WAVE 9)."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_401 = 0
_403 = 0
_window_start = time.time()


def record_auth_status(status: int) -> None:
    global _401, _403
    if status == 401:
        with _lock:
            _401 += 1
    elif status == 403:
        with _lock:
            _403 += 1


def auth_snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "401_count": _401,
            "403_count": _403,
            "window_start": int(_window_start),
        }
