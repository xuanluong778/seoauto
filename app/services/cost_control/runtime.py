"""Rate limit, cooldown, and single-flight guards."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException, status

_LOG = logging.getLogger("cost_control.runtime")

_guard_lock = threading.Lock()
_user_hits: dict[str, deque[float]] = defaultdict(deque)
_cooldown_until: dict[str, float] = {}
_flight_locks: dict[str, threading.Lock] = {}


def _mono() -> float:
  return time.monotonic()


def _utc_iso_from_mono(deadline_mono: float) -> str:
  remaining = max(0.0, deadline_mono - _mono())
  return datetime.fromtimestamp(time.time() + remaining, tz=timezone.utc).isoformat()


def _prune(hits: deque[float], *, window_sec: float = 60.0) -> None:
  cutoff = _mono() - window_sec
  while hits and hits[0] < cutoff:
    hits.popleft()


def check_user_rate_limit(*, scope: str, user_id: int, limit_per_min: int) -> None:
  key = f"{scope}:{user_id}"
  with _guard_lock:
    hits = _user_hits[key]
    _prune(hits)
    if len(hits) >= max(1, int(limit_per_min)):
      raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
          "code": "rate_limited",
          "message": "Bạn thao tác quá nhanh. Vui lòng đợi vài giây rồi thử lại.",
        },
      )
    hits.append(_mono())


def is_cooldown_active(cooldown_key: str) -> bool:
  with _guard_lock:
    until = _cooldown_until.get(cooldown_key)
    if until is None:
      return False
    if _mono() >= until:
      _cooldown_until.pop(cooldown_key, None)
      return False
    return True


def cooldown_until_iso(cooldown_key: str) -> str | None:
  with _guard_lock:
    until = _cooldown_until.get(cooldown_key)
    if until is None or _mono() >= until:
      return None
    return _utc_iso_from_mono(until)


def mark_cooldown(cooldown_key: str, *, seconds: int) -> str:
  sec = min(max(int(seconds), 5), 600)
  with _guard_lock:
    _cooldown_until[cooldown_key] = _mono() + sec
    return _utc_iso_from_mono(_cooldown_until[cooldown_key])


def ensure_not_cooldown(cooldown_key: str, *, message: str | None = None) -> None:
  if not is_cooldown_active(cooldown_key):
    return
  until = cooldown_until_iso(cooldown_key)
  _LOG.warning("cost_control cooldown active key=%s until=%s", cooldown_key, until)
  raise HTTPException(
    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    detail={
      "code": "provider_cooldown",
      "message": message or "API tạm thời bị giới hạn. Vui lòng thử lại sau.",
      "cooldown_until": until,
    },
  )


def _flight_lock(flight_key: str) -> threading.Lock:
  with _guard_lock:
    lock = _flight_locks.get(flight_key)
    if lock is None:
      lock = threading.Lock()
      _flight_locks[flight_key] = lock
    return lock


class SingleFlightGuard:
  """Only one in-flight external operation per flight_key."""

  def __init__(self, flight_key: str) -> None:
    self.flight_key = flight_key
    self._lock = _flight_lock(flight_key)
    self.acquired = False

  def __enter__(self) -> SingleFlightGuard:
    self.acquired = self._lock.acquire(blocking=False)
    if not self.acquired:
      raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
          "code": "request_in_progress",
          "message": "Đang xử lý yêu cầu tương tự — vui lòng đợi hoàn tất.",
        },
      )
    return self

  def __exit__(self, exc_type, exc, tb) -> None:
    if self.acquired:
      self._lock.release()
