"""
Aggregate crawl metrics in Redis for dashboards / alerting.

Keys (counters, no expiry by default — trim in prod with periodic job):
  crawl:metrics:success
  crawl:metrics:block
  crawl:metrics:timeout
  crawl:metrics:time_sum_ms
  crawl:metrics:time_count
"""

from __future__ import annotations

import os
import time
from typing import Any


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
    except Exception:
        return None


def record_crawl_outcome(*, crawl_status: str, crawl_time_sec: float | None) -> None:
    r = _redis()
    if not r:
        return
    try:
        st = (crawl_status or "").lower()
        if st == "success":
            r.incr("crawl:metrics:success", 1)
        elif st == "blocked":
            r.incr("crawl:metrics:block", 1)
        elif st == "timeout":
            r.incr("crawl:metrics:timeout", 1)
        if crawl_time_sec is not None:
            ms = int(float(crawl_time_sec) * 1000)
            r.incrby("crawl:metrics:time_sum_ms", ms)
            r.incr("crawl:metrics:time_count", 1)
    except Exception:
        pass


def snapshot_metrics() -> dict[str, Any]:
    r = _redis()
    if not r:
        return {"redis": False}
    try:
        ok = int(r.get("crawl:metrics:success") or 0)
        blk = int(r.get("crawl:metrics:block") or 0)
        to = int(r.get("crawl:metrics:timeout") or 0)
        tsum = int(r.get("crawl:metrics:time_sum_ms") or 0)
        tcnt = int(r.get("crawl:metrics:time_count") or 0)
        avg = (tsum / tcnt / 1000.0) if tcnt else 0.0
        total = ok + blk + to
        workers = 0
        try:
            for _ in r.scan_iter("crawl:worker:heartbeat:*", count=50):
                workers += 1
        except Exception:
            pass
        return {
            "redis": True,
            "success": ok,
            "blocked": blk,
            "timeout": to,
            "total_recorded": total,
            "success_rate": (ok / total) if total else None,
            "block_rate": (blk / total) if total else None,
            "avg_crawl_time_sec": round(avg, 3),
            "active_workers_heartbeat": workers,
            "ts": time.time(),
        }
    except Exception as exc:
        return {"redis": True, "error": str(exc)}


def worker_heartbeat(worker_id: str, ttl_sec: int = 45) -> None:
    r = _redis()
    if not r:
        return
    try:
        r.setex(f"crawl:worker:heartbeat:{worker_id}", max(10, ttl_sec), "1")
    except Exception:
        pass
