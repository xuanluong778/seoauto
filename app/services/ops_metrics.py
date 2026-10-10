"""Operational metrics snapshot: DB pool, queue backlog, worker, CPU/RAM."""

from __future__ import annotations

import os
import time
from typing import Any


def _read_proc_mem_mb() -> dict[str, float | None]:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            lines = fh.readlines()
        kv = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip()] = v.strip()
        rss_kb = float(kv.get("VmRSS", "0").split()[0])
        return {"process_rss_mb": round(rss_kb / 1024.0, 1)}
    except OSError:
        return {"process_rss_mb": None}


def _read_host_mem_cpu() -> dict[str, Any]:
    out: dict[str, Any] = {"cpu_pct": None, "ram_used_mb": None, "ram_total_mb": None}
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            mem = {}
            for line in fh:
                parts = line.split(":")
                if len(parts) == 2:
                    mem[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        out["ram_total_mb"] = round(total / 1024.0, 1) if total else None
        if total:
            out["ram_used_mb"] = round((total - avail) / 1024.0, 1)
            out["ram_used_pct"] = round((total - avail) / total * 100.0, 1)
    except OSError:
        pass
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            cpu_line = fh.readline().split()
        if len(cpu_line) >= 5:
            vals = [int(x) for x in cpu_line[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
            time.sleep(0.05)
            with open("/proc/stat", encoding="utf-8") as fh:
                cpu_line2 = fh.readline().split()
            vals2 = [int(x) for x in cpu_line2[1:]]
            idle2 = vals2[3] + (vals2[4] if len(vals2) > 4 else 0)
            total2 = sum(vals2)
            dt = total2 - total
            if dt > 0:
                out["cpu_pct"] = round((1.0 - (idle2 - idle) / dt) * 100.0, 1)
    except OSError:
        pass
    return out


def db_pool_stats() -> dict[str, Any]:
    try:
        from app.db import engine

        pool = engine.pool
        return {
            "pool_size": getattr(pool, "size", lambda: None)(),
            "checked_in": getattr(pool, "checkedin", lambda: None)(),
            "checked_out": getattr(pool, "checkedout", lambda: None)(),
            "overflow": getattr(pool, "overflow", lambda: None)(),
        }
    except Exception as exc:
        return {"error": type(exc).__name__}


def queue_backlog_stats() -> dict[str, Any]:
    from app.services.job_store import list_jobs_by_states

    queued = list_jobs_by_states(states=("QUEUED", "PENDING"), limit=100)
    running = list_jobs_by_states(states=("RUNNING",), limit=100)
    by_type: dict[str, int] = {}
    wait_ms: list[int] = []
    now = time.time()
    for job in queued:
        by_type[job.job_type] = by_type.get(job.job_type, 0) + 1
        created = getattr(job, "created_at", None)
        if created is not None:
            try:
                wait_ms.append(int((now - created.timestamp()) * 1000))
            except (AttributeError, OSError, ValueError):
                pass
    wait_ms.sort()
    p95_wait = wait_ms[int(len(wait_ms) * 0.95)] if wait_ms else None
    return {
        "queued_count": len(queued),
        "running_count": len(running),
        "queued_by_type": by_type,
        "job_wait_p95_ms": p95_wait,
        "oldest_queued_job_ids": [j.job_id for j in queued[:5]],
    }


def celery_worker_stats(timeout_sec: float = 0.8) -> dict[str, Any]:
    try:
        from app.queue.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=timeout_sec)
        ping = inspector.ping() if inspector else None
        active = inspector.active() if inspector else None
        reserved = inspector.reserved() if inspector else None
        worker_count = len(ping or {})
        active_tasks = sum(len(v or []) for v in (active or {}).values())
        reserved_tasks = sum(len(v or []) for v in (reserved or {}).values())
        return {
            "workers_online": worker_count,
            "active_tasks": active_tasks,
            "reserved_tasks": reserved_tasks,
            "ping_ok": worker_count > 0,
        }
    except Exception as exc:
        return {"error": type(exc).__name__, "workers_online": 0, "ping_ok": False}


def fairness_slot_stats() -> dict[str, Any]:
    try:
        from app.services.queue_fairness import _redis

        client = _redis()
        if client is None:
            return {"redis": False}
        tech_keys = list(client.scan_iter("queue:slots:technical:*", count=50))
        bulk_keys = list(client.scan_iter("queue:slots:bulk:*", count=50))
        return {
            "redis": True,
            "technical_slot_keys": len(tech_keys),
            "bulk_slot_keys": len(bulk_keys),
        }
    except Exception as exc:
        return {"error": type(exc).__name__}


def redis_queue_stats() -> dict[str, Any]:
    """Celery Redis queue depths + memory/latency probe."""
    import os

    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        return {"configured": False}
    try:
        import redis

        from app.queue.celery_queues import ALL_QUEUES

        client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        t0 = time.perf_counter()
        client.ping()
        ping_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        info = client.info("memory")
        depths: dict[str, int] = {}
        for q in (*ALL_QUEUES, "celery"):
            try:
                depths[q] = int(client.llen(q))
            except Exception:
                depths[q] = -1
        return {
            "configured": True,
            "ping_ms": ping_ms,
            "memory_mb": round((info.get("used_memory", 0) or 0) / (1024 * 1024), 1),
            "keys": int(client.dbsize()),
            "queue_depth": depths,
            "max_depth": max(v for v in depths.values() if v >= 0) if depths else 0,
        }
    except Exception as exc:
        return {"configured": True, "error": type(exc).__name__}


def pg_connection_stats() -> dict[str, Any]:
    import os

    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url.startswith("postgresql"):
        return {"pg": False}
    try:
        import psycopg2

        conn = psycopg2.connect(db_url.replace("postgresql+psycopg2://", "postgresql://"))
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        total = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'active'"
        )
        active = int(cur.fetchone()[0])
        cur.close()
        conn.close()
        return {"pg": True, "connections_total": total, "connections_active": active}
    except Exception as exc:
        return {"pg": True, "error": type(exc).__name__}


def domain_failure_stats() -> dict[str, Any]:
    """Recent failed generations / WP jobs from DB (read-only)."""
    out: dict[str, Any] = {}
    try:
        from app.db import SessionLocal
        from sqlalchemy import func, text

        db = SessionLocal()
        try:
            if db.bind.dialect.name == "postgresql":
                row = db.execute(
                    text(
                        "SELECT count(*) FROM content_ai_generations "
                        "WHERE state = 'FAILED' AND updated_at > now() - interval '1 hour'"
                    )
                ).scalar()
                out["content_ai_failed_1h"] = int(row or 0)
                row2 = db.execute(
                    text(
                        "SELECT count(*) FROM keyword_cluster_jobs "
                        "WHERE state IN ('FAILED','ERROR') AND updated_at > now() - interval '1 hour'"
                    )
                ).scalar()
                out["jobs_failed_1h"] = int(row2 or 0)
            else:
                from app.models.content_ai_generation import ContentAiGeneration

                out["content_ai_failed_1h"] = (
                    db.query(func.count(ContentAiGeneration.id))
                    .filter(ContentAiGeneration.state == "FAILED")
                    .scalar()
                    or 0
                )
        finally:
            db.close()
    except Exception as exc:
        out["error"] = type(exc).__name__
    return out


def celery_beat_stats() -> dict[str, Any]:
    try:
        from app.services.health_probes import check_beat_singleton_lock

        lock = check_beat_singleton_lock()
        return {
            "beat_lock_ok": bool(lock.get("ok")),
            "automation_lock_ttl": lock.get("automation_lock_ttl"),
            "marketing_lock_ttl": lock.get("marketing_lock_ttl"),
        }
    except Exception as exc:
        return {"error": type(exc).__name__}


def collect_ops_metrics() -> dict[str, Any]:
    from app.db import connection_budget
    from app.services.auth_ops_metrics import auth_snapshot
    from app.services.health_probes import check_database, check_redis
    from app.services.llm_ops_metrics import llm_snapshot
    from app.services.observability_rollout import observability_wave9_enabled, slo_thresholds
    from app.services.ops_alerting import evaluate_alerts, recovery_state_snapshot
    from app.services.request_metrics import latency_snapshot

    host = _read_host_mem_cpu()
    proc = _read_proc_mem_mb()
    payload = {
        "ts": int(time.time()),
        "http": latency_snapshot(),
        "host": host,
        "process": proc,
        "db_pool": db_pool_stats(),
        "db_connection_budget": connection_budget(),
        "db_connections": pg_connection_stats(),
        "db_probe": check_database(timeout_sec=1.0),
        "redis": redis_queue_stats(),
        "redis_probe": check_redis(timeout_sec=0.8),
        "queue": queue_backlog_stats(),
        "celery": celery_worker_stats(),
        "celery_beat": celery_beat_stats(),
        "fairness": fairness_slot_stats(),
        "llm": llm_snapshot(),
        "auth": auth_snapshot(),
        "domain_failures": domain_failure_stats(),
        "env": {
            "web_workers": os.getenv("UVICORN_WORKERS", "1"),
            "celery_concurrency": os.getenv("CELERY_CONCURRENCY", "1"),
            "db_pool_size": os.getenv("DB_POOL_SIZE", "10"),
        },
    }
    if observability_wave9_enabled():
        payload["slo"] = slo_thresholds()
        payload["alerts"] = evaluate_alerts(payload)
        payload["alert_recovery"] = recovery_state_snapshot()
    return payload
