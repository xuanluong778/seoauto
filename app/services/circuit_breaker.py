"""Lightweight circuit breaker for third-party HTTP APIs.

Opens after consecutive failures; half-opens after cooldown. Graceful callers
should treat CircuitOpenError as degrade/fallback (not hard 500).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    def __init__(self, name: str, retry_after_sec: float):
        self.name = name
        self.retry_after_sec = retry_after_sec
        super().__init__(f"circuit_open:{name}:retry_after={retry_after_sec:.1f}s")


@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_BREAKERS: dict[str, _BreakerState] = {}
_GLOBAL_LOCK = threading.Lock()


def _threshold() -> int:
    try:
        return max(2, int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")))
    except (TypeError, ValueError):
        return 5


def _cooldown_sec() -> float:
    try:
        return max(5.0, float(os.getenv("CIRCUIT_BREAKER_COOLDOWN_SECONDS", "60")))
    except (TypeError, ValueError):
        return 60.0


def _state(name: str) -> _BreakerState:
    with _GLOBAL_LOCK:
        st = _BREAKERS.get(name)
        if st is None:
            st = _BreakerState()
            _BREAKERS[name] = st
        return st


def circuit_allow(name: str) -> None:
    """Raise CircuitOpenError if breaker is open."""
    st = _state(name)
    with st.lock:
        if st.failures < _threshold():
            return
        elapsed = time.monotonic() - st.opened_at
        cool = _cooldown_sec()
        if elapsed >= cool:
            # half-open: allow one probe
            st.failures = _threshold() - 1
            return
        raise CircuitOpenError(name, cool - elapsed)


def circuit_record_success(name: str) -> None:
    st = _state(name)
    with st.lock:
        st.failures = 0
        st.opened_at = 0.0


def circuit_record_failure(name: str) -> None:
    st = _state(name)
    with st.lock:
        st.failures += 1
        if st.failures >= _threshold():
            st.opened_at = time.monotonic()


def call_with_circuit(name: str, fn: Callable[[], T]) -> T:
    circuit_allow(name)
    try:
        out = fn()
    except Exception:
        circuit_record_failure(name)
        raise
    circuit_record_success(name)
    return out


def circuit_snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {}
    with _GLOBAL_LOCK:
        items = list(_BREAKERS.items())
    for name, st in items:
        with st.lock:
            out[name] = {
                "failures": st.failures,
                "open": st.failures >= _threshold() and (time.monotonic() - st.opened_at) < _cooldown_sec(),
            }
    return out
