"""WAVE 9 — observability feature flags and SLO thresholds."""

from __future__ import annotations

import os


def observability_wave9_enabled() -> bool:
    return os.getenv("OBSERVABILITY_WAVE9", "1").strip().lower() in ("1", "true", "yes", "on")


def structured_request_logging_enabled() -> bool:
    return os.getenv("STRUCTURED_REQUEST_LOG", "1").strip().lower() in ("1", "true", "yes", "on")


def ops_alerting_enabled() -> bool:
    return os.getenv("OPS_ALERTING_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def slo_thresholds() -> dict[str, float | int]:
    return {
        "api_p95_ms": float(os.getenv("SLO_API_P95_MS", "1500")),
        "api_5xx_rate_pct": float(os.getenv("SLO_API_5XX_RATE_PCT", "1.0")),
        "queue_depth_max": int(os.getenv("SLO_QUEUE_DEPTH_MAX", "500")),
        "job_wait_p95_ms": float(os.getenv("SLO_JOB_WAIT_P95_MS", "120000")),
        "db_pool_util_pct": float(os.getenv("SLO_DB_POOL_UTIL_PCT", "90")),
        "redis_memory_mb_max": float(os.getenv("SLO_REDIS_MEMORY_MB_MAX", "512")),
        "celery_workers_min": int(os.getenv("SLO_CELERY_WORKERS_MIN", "1")),
        "auth_401_spike": int(os.getenv("SLO_AUTH_401_SPIKE", "200")),
    }


def alert_dedup_ttl_sec() -> int:
    try:
        return max(60, int(os.getenv("OPS_ALERT_DEDUP_TTL_SEC", "900")))
    except ValueError:
        return 900
