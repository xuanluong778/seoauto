"""Liveness (/health) and readiness (/ready) probes for load balancers."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

_LOG = logging.getLogger(__name__)

_celery_workers_cache: dict[str, Any] = {"at": 0.0, "payload": {}}
_readiness_full_cache: dict[str, Any] = {"at": 0.0, "body": None, "ready": False, "lite": True}
_redis_probe_client = None


def _celery_cache_sec() -> float:
    try:
        return max(0.0, min(10.0, float(os.getenv("READY_CELERY_CACHE_SEC", "2"))))
    except ValueError:
        return 2.0


def _full_cache_sec() -> float:
    try:
        return max(0.0, min(10.0, float(os.getenv("READY_FULL_CACHE_SEC", "2"))))
    except ValueError:
        return 2.0


def _shared_redis():
    """Reuse one Redis client for probe pings (avoid connect storm under /ready load)."""
    global _redis_probe_client
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    if _redis_probe_client is not None:
        try:
            _redis_probe_client.ping()
            return _redis_probe_client
        except Exception:
            _redis_probe_client = None
    try:
        import redis

        _redis_probe_client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        _redis_probe_client.ping()
        return _redis_probe_client
    except Exception:
        _redis_probe_client = None
        return None


def check_database(timeout_sec: float = 2.0) -> dict[str, Any]:
    started = time.monotonic()
    try:
        from sqlalchemy import text

        from app.db import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "ok": True,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        _LOG.warning("ready_db_failed: %s", exc)
        return {
            "ok": False,
            "error": type(exc).__name__,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def check_redis(timeout_sec: float = 1.0) -> dict[str, Any]:
    started = time.monotonic()
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return {"ok": False, "error": "REDIS_URL_unset", "latency_ms": 0}
    try:
        client = _shared_redis()
        if client is None:
            raise RuntimeError("redis_unavailable")
        pong = client.ping()
        return {
            "ok": bool(pong),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        _LOG.warning("ready_redis_failed: %s", exc)
        return {
            "ok": False,
            "error": type(exc).__name__,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def check_queue_broker() -> dict[str, Any]:
    """Queue readiness = Redis broker reachable (Celery uses REDIS_URL)."""
    return check_redis()


def check_celery_workers(timeout_sec: float = 1.0) -> dict[str, Any]:
    """
    Soft check: Celery control ping.

    Not required for /ready overall (workers scale independently), but reported
    for observability. Env READY_REQUIRE_CELERY_WORKERS=1 to fail ready when empty.
    """
    cache_sec = _celery_cache_sec()
    now = time.monotonic()
    if cache_sec > 0 and (now - float(_celery_workers_cache.get("at") or 0)) < cache_sec:
        cached = _celery_workers_cache.get("payload")
        if isinstance(cached, dict) and cached:
            return dict(cached)
    started = time.monotonic()
    try:
        from app.queue.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=timeout_sec)
        pinged = inspector.ping() if inspector else None
        workers = list(pinged.keys()) if isinstance(pinged, dict) else []
        ok = bool(workers)
        payload = {
            "ok": ok,
            "workers": workers[:10],
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
        _celery_workers_cache["at"] = time.monotonic()
        _celery_workers_cache["payload"] = payload
        return payload
    except Exception as exc:
        _LOG.warning("ready_celery_workers_failed: %s", exc)
        payload = {
            "ok": False,
            "error": type(exc).__name__,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
        _celery_workers_cache["at"] = time.monotonic()
        _celery_workers_cache["payload"] = payload
        return payload


def check_beat_singleton_lock() -> dict[str, Any]:
    """
    Report Redis beat lock key status (set by scheduled tick tasks).
    Presence of lock with TTL means a tick recently held singleton.
    """
    started = time.monotonic()
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return {"ok": False, "error": "REDIS_URL_unset", "latency_ms": 0}
    try:
        client = _shared_redis()
        if client is None:
            raise RuntimeError("redis_unavailable")
        auto_ttl = client.ttl("celery:beat:lock:email.automation_tick")
        mkt_ttl = client.ttl("celery:beat:lock:email.marketing_tick")
        # Redis TTL: -2 missing, -1 no expire, >=0 seconds left
        return {
            "ok": True,
            "automation_lock_ttl": auto_ttl,
            "marketing_lock_ttl": mkt_ttl,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def check_queue_fairness() -> dict[str, Any]:
    try:
        from app.services.queue_fairness import slot_stats

        return {
            "ok": True,
            "technical": slot_stats("technical"),
            "bulk": slot_stats("bulk"),
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def readiness_payload(*, lite: bool | None = None) -> tuple[dict[str, Any], bool]:
    """
    Readiness probe payload.

    lite=True (default): DB + Redis only — load-balancer safe, no Celery inspect storm.
    lite=False: full observability checks (use ?full=1 sparingly).
    """
    if lite is None:
        lite = os.getenv("READY_LITE", "1").strip().lower() not in ("0", "false", "no", "off")
    cache_sec = _full_cache_sec()
    now = time.monotonic()
    if cache_sec > 0:
        age = now - float(_readiness_full_cache.get("at") or 0)
        if age < cache_sec and _readiness_full_cache.get("lite") == lite:
            cached_body = _readiness_full_cache.get("body")
            if isinstance(cached_body, dict):
                return dict(cached_body), bool(_readiness_full_cache.get("ready"))

    if lite:
        db = check_database()
        redis = check_redis()
        ready = bool(db.get("ok")) and bool(redis.get("ok"))
        body = {
            "status": "ready" if ready else "not_ready",
            "lite": True,
            "checks": {
                "database": db,
                "redis": redis,
            },
        }
    else:
        db = check_database()
        redis = check_redis()
        queue = {"ok": redis.get("ok"), "via": "redis_broker", "latency_ms": redis.get("latency_ms")}
        workers = check_celery_workers()
        beat = check_beat_singleton_lock()
        fairness = check_queue_fairness()
        require_workers = os.getenv("READY_REQUIRE_CELERY_WORKERS", "0").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        ready = bool(db.get("ok")) and bool(redis.get("ok"))
        if require_workers and not workers.get("ok"):
            ready = False
        body = {
            "status": "ready" if ready else "not_ready",
            "lite": False,
            "checks": {
                "database": db,
                "redis": redis,
                "queue_broker": queue,
                "celery_workers": workers,
                "beat_locks": beat,
                "queue_fairness": fairness,
            },
        }

    _readiness_full_cache["at"] = time.monotonic()
    _readiness_full_cache["body"] = body
    _readiness_full_cache["ready"] = ready
    _readiness_full_cache["lite"] = lite
    return body, ready
