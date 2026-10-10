#!/usr/bin/env python3
"""FINAL SAAS RELIABILITY — mixed authenticated load 100→250→500→1000.

Reuses WAVE7 flow cycle. Gates:
  error < 0.5%; read p95 < 800ms (probe); mixed p95 < 1.5s; queue drain; no OOM.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "baseline" / "final_saas_reliability"
BASE = (os.getenv("LOAD_TEST_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")
DURATION = float(os.getenv("FINAL_LOAD_DURATION_SEC", "12"))
LOADS = [int(x) for x in (os.getenv("FINAL_LOAD_TIERS", "100,250,500,1000").split(",")) if x.strip()]

from scripts.wave7_full_system import (  # noqa: E402
    _fetch_metrics,
    _load_env,
    _load_test_user_ids,
    _make_tokens,
    _probe_read_latency,
    _run_mixed_load,
)


def _snap(metrics: dict[str, Any]) -> dict[str, Any]:
    host = metrics.get("host") or {}
    queue = metrics.get("queue") or {}
    redis = metrics.get("redis") or {}
    return {
        "ram_used_mb": host.get("ram_used_mb"),
        "cpu_pct": host.get("cpu_pct"),
        "db_connections": metrics.get("db_connections"),
        "redis_memory_mb": redis.get("memory_mb"),
        "queue_depth": redis.get("queue_depth") or queue.get("queued_by_type"),
        "queued_count": queue.get("queued_count"),
        "workers_online": (metrics.get("celery") or {}).get("workers_online"),
        "http_p95_ms": (metrics.get("http") or {}).get("p95_ms"),
    }


async def main() -> dict[str, Any]:
    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)

    import httpx

    uid = _load_test_user_ids(1)[0]
    read_probe = await _probe_read_latency(_make_tokens([uid])[uid])
    numeric = [float(v) for v in read_probe.values() if isinstance(v, (int, float))]
    read_p95 = max(numeric) if numeric else float(read_probe.get("p95_ms") or 9999)

    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        before = _snap(await _fetch_metrics(client))

    for n in LOADS:
        print(f"=== LOAD {n} concurrent ({DURATION}s) ===", flush=True)
        run = await _run_mixed_load(n, DURATION)
        results.append(run)
        print(
            f"  rps={run.get('rps')} err%={run.get('error_pct')} "
            f"p95={run.get('server_p95_ms') or run.get('p95_ms')} gate={run.get('gate')}",
            flush=True,
        )
        await asyncio.sleep(6)

    async with httpx.AsyncClient(timeout=10.0) as client:
        after = _snap(await _fetch_metrics(client))

    queue_depth = int(after.get("queued_count") or 0)
    qd = after.get("queue_depth") or {}
    if isinstance(qd, dict) and qd:
        queue_depth = max(queue_depth, max(int(v or 0) for v in qd.values()))

    gates: dict[str, str] = {}
    for run in results:
        n = int(run.get("concurrency") or 0)
        raw_err = run.get("error_pct")
        err = float(100 if raw_err is None else raw_err)
        # Prefer server-side http p95; client p95 at high VU includes asyncio queueing.
        raw_server = run.get("server_p95_ms")
        raw_client = run.get("p95_ms")
        if raw_server is not None and float(raw_server) < 9000:
            p95 = float(raw_server)
        else:
            p95 = float(raw_client if raw_client is not None else 99999)
        gates[f"LOAD_{n}"] = "PASS" if err < 0.5 and p95 < 1500.0 else "FAIL"
        run["evaluated_p95_ms"] = p95
        run["evaluated_error_pct"] = err
        run["final_gate"] = gates[f"LOAD_{n}"]

    gates["READ_P95"] = "PASS" if read_p95 < 800.0 else "FAIL"
    gates["QUEUE_DRAIN"] = "PASS" if queue_depth == 0 else "FAIL"
    ram_before = float(before.get("ram_used_mb") or 0)
    ram_after = float(after.get("ram_used_mb") or 0)
    gates["NO_OOM"] = "PASS" if (ram_after - ram_before) < 1500 else "FAIL"

    report = {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "duration_sec": DURATION,
        "read_probe": read_probe,
        "read_p95_ms": round(read_p95, 2),
        "loads": results,
        "before": before,
        "after": after,
        "gates": gates,
        "SAAS_LOAD": "PASS" if all(v == "PASS" for v in gates.values()) else "FAIL",
    }
    out_path = OUT / "final_load_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"gates": gates, "SAAS_LOAD": report["SAAS_LOAD"], "out": str(out_path)}, indent=2))
    return report


if __name__ == "__main__":
    asyncio.run(main())
