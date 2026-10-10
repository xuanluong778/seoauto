"""In-process LLM call counters for ops /metrics (WAVE 9)."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_calls = 0
_timeouts = 0
_rate_limited = 0
_server_errors = 0
_tokens_approx = 0
_last_error_at: float | None = None


def record_llm_call(
    *,
    ok: bool = True,
    timeout: bool = False,
    rate_limited: bool = False,
    server_error: bool = False,
    tokens: int = 0,
) -> None:
    global _calls, _timeouts, _rate_limited, _server_errors, _tokens_approx, _last_error_at
    with _lock:
        _calls += 1
        if timeout:
            _timeouts += 1
        if rate_limited:
            _rate_limited += 1
        if server_error:
            _server_errors += 1
        if tokens:
            _tokens_approx += int(tokens)
        if not ok or timeout or rate_limited or server_error:
            _last_error_at = time.time()


def llm_snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "calls": _calls,
            "timeouts": _timeouts,
            "rate_limited_429": _rate_limited,
            "server_errors_5xx": _server_errors,
            "tokens_approx": _tokens_approx,
            "last_error_at": int(_last_error_at) if _last_error_at else None,
        }
