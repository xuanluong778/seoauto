"""Ops alerting with SLO thresholds and deduplication (WAVE 9)."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from app.services.observability_rollout import alert_dedup_ttl_sec, ops_alerting_enabled, slo_thresholds

_LOG = logging.getLogger("seoauto.ops_alert")

_dedup_cache: dict[str, float] = {}
_recovery_state: dict[str, bool] = {}


def reset_alert_state_for_tests() -> None:
    """Test-only: clear dedup/recovery between isolated alert scenarios."""
    _dedup_cache.clear()
    _recovery_state.clear()


def _dedup_key(alert_type: str, detail: str = "") -> str:
    raw = f"{alert_type}:{detail}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _should_fire(alert_type: str, detail: str = "") -> bool:
    key = _dedup_key(alert_type, detail)
    now = time.time()
    ttl = float(alert_dedup_ttl_sec())
    expired = [k for k, ts in _dedup_cache.items() if now - ts > ttl]
    for k in expired:
        _dedup_cache.pop(k, None)
    if key in _dedup_cache:
        return False
    _dedup_cache[key] = now
    return True


def _mark_recovery(alert_type: str, recovered: bool) -> None:
    prev = _recovery_state.get(alert_type)
    if prev is True and recovered:
        _LOG.info(json.dumps({"event": "ops_alert_recovery", "alert_type": alert_type}))
    _recovery_state[alert_type] = not recovered


def evaluate_alerts(metrics: dict[str, Any], *, force: bool = False) -> list[dict[str, Any]]:
    """Return fired alerts (after dedup). Empty when healthy."""
    if not ops_alerting_enabled() and not force:
        return []

    slo = slo_thresholds()
    fired: list[dict[str, Any]] = []

    http = metrics.get("http") or {}
    total = int(http.get("total_requests") or 0)
    err5 = int(http.get("error_5xx") or 0)
    p95 = float(http.get("p95_ms") or 0)
    if total >= 20:
        rate5 = err5 / total * 100.0
        if rate5 > float(slo["api_5xx_rate_pct"]):
            alert_type = "api_5xx_rate"
            if _should_fire(alert_type, f"{rate5:.2f}"):
                fired.append(
                    {
                        "type": alert_type,
                        "severity": "critical",
                        "message": f"API 5xx rate {rate5:.2f}% > SLO {slo['api_5xx_rate_pct']}%",
                        "value": rate5,
                    }
                )
            _mark_recovery(alert_type, False)
        else:
            _mark_recovery("api_5xx_rate", True)

    if p95 and p95 > float(slo["api_p95_ms"]):
        alert_type = "api_p95"
        if _should_fire(alert_type, f"{p95:.0f}"):
            fired.append(
                {
                    "type": alert_type,
                    "severity": "warning",
                    "message": f"API p95 {p95:.0f}ms > SLO {slo['api_p95_ms']}ms",
                    "value": p95,
                }
            )
        _mark_recovery(alert_type, False)
    else:
        _mark_recovery("api_p95", True)

    queue = metrics.get("queue") or {}
    qdepth = int(queue.get("queued_count") or 0)
    if qdepth > int(slo["queue_depth_max"]):
        alert_type = "queue_backlog"
        if _should_fire(alert_type, str(qdepth)):
            fired.append(
                {
                    "type": alert_type,
                    "severity": "critical",
                    "message": f"Job queue backlog {qdepth} > SLO {slo['queue_depth_max']}",
                    "value": qdepth,
                }
            )
        _mark_recovery(alert_type, False)
    else:
        _mark_recovery("queue_backlog", True)

    wait_p95 = queue.get("job_wait_p95_ms")
    if wait_p95 is not None and float(wait_p95) > float(slo["job_wait_p95_ms"]):
        alert_type = "queue_wait"
        if _should_fire(alert_type, str(wait_p95)):
            fired.append(
                {
                    "type": alert_type,
                    "severity": "warning",
                    "message": f"Job wait p95 {wait_p95}ms > SLO",
                    "value": wait_p95,
                }
            )
        _mark_recovery(alert_type, False)
    else:
        _mark_recovery("queue_wait", True)

    celery = metrics.get("celery") or {}
    workers = int(celery.get("workers_online") or 0)
    if workers < int(slo["celery_workers_min"]):
        alert_type = "worker_down"
        if _should_fire(alert_type, str(workers)):
            fired.append(
                {
                    "type": alert_type,
                    "severity": "critical",
                    "message": f"Celery workers online {workers} < SLO {slo['celery_workers_min']}",
                    "value": workers,
                }
            )
        _mark_recovery(alert_type, False)
    else:
        _mark_recovery("worker_down", True)

    db_probe = metrics.get("db_probe") or {}
    redis_probe = metrics.get("redis_probe") or {}
    if not db_probe.get("ok", True):
        alert_type = "db_unhealthy"
        if _should_fire(alert_type):
            fired.append({"type": alert_type, "severity": "critical", "message": "Database probe failed"})
        _mark_recovery(alert_type, False)
    else:
        _mark_recovery("db_unhealthy", True)

    if not redis_probe.get("ok", True):
        alert_type = "redis_unhealthy"
        if _should_fire(alert_type):
            fired.append({"type": alert_type, "severity": "critical", "message": "Redis probe failed"})
        _mark_recovery(alert_type, False)
    else:
        _mark_recovery("redis_unhealthy", True)

    db_pool = metrics.get("db_pool") or {}
    ps = int(db_pool.get("pool_size") or 0)
    co = int(db_pool.get("checked_out") or 0)
    mo = int(db_pool.get("overflow") or 0)
    budget = ps + mo
    if budget > 0 and co / budget * 100.0 > float(slo["db_pool_util_pct"]):
        alert_type = "db_pool_saturation"
        if _should_fire(alert_type, str(co)):
            fired.append(
                {
                    "type": alert_type,
                    "severity": "warning",
                    "message": f"DB pool checked_out {co}/{budget}",
                    "value": co,
                }
            )

    redis_q = metrics.get("redis") or {}
    mem_mb = redis_q.get("memory_mb")
    if mem_mb is not None and float(mem_mb) > float(slo["redis_memory_mb_max"]):
        alert_type = "redis_memory"
        if _should_fire(alert_type, str(mem_mb)):
            fired.append(
                {
                    "type": alert_type,
                    "severity": "warning",
                    "message": f"Redis memory {mem_mb}MB > SLO",
                    "value": mem_mb,
                }
            )

    auth = metrics.get("auth") or {}
    c401 = int(auth.get("401_count") or 0)
    if c401 > int(slo["auth_401_spike"]):
        alert_type = "auth_401_spike"
        if _should_fire(alert_type, str(c401)):
            fired.append(
                {
                    "type": alert_type,
                    "severity": "warning",
                    "message": f"Auth 401 spike {c401}",
                    "value": c401,
                }
            )
        _mark_recovery(alert_type, False)
    else:
        _mark_recovery("auth_401_spike", True)

    for alert in fired:
        _LOG.warning(json.dumps({"event": "ops_alert", **alert}))

    return fired


def simulate_alert_test() -> dict[str, Any]:
    """Synthetic bad metrics → alert → recovery (for WAVE 9 gates)."""
    reset_alert_state_for_tests()
    bad = {
        "http": {"total_requests": 100, "error_5xx": 10, "p95_ms": 5000},
        "queue": {"queued_count": 999, "job_wait_p95_ms": 200000},
        "celery": {"workers_online": 0},
        "db_probe": {"ok": False},
        "redis_probe": {"ok": False},
        "auth": {"401_count": 500},
    }
    first = evaluate_alerts(bad, force=True)
    dup = evaluate_alerts(bad, force=True)
    good = {
        "http": {"total_requests": 100, "error_5xx": 0, "p95_ms": 200},
        "queue": {"queued_count": 0},
        "celery": {"workers_online": 5},
        "db_probe": {"ok": True},
        "redis_probe": {"ok": True},
        "auth": {"401_count": 0},
    }
    evaluate_alerts(good, force=True)
    recovery = recovery_state_snapshot()
    alert_types = [a["type"] for a in first]
    recovery_detected = bool(alert_types) and all(
        recovery.get(t) is False for t in alert_types
    )
    return {
        "first_alert_count": len(first),
        "duplicate_suppressed": len(dup) == 0,
        "alert_types": alert_types,
        "recovery_states": recovery,
        "recovery_detected": recovery_detected,
    }


def recovery_state_snapshot() -> dict[str, bool]:
    return dict(_recovery_state)
