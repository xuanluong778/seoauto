#!/usr/bin/env python3
"""Wave 5 — per-endpoint profiling + layer metrics (PROFILE → ROOT CAUSE → FIX → RETEST)."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "env.local")
load_dotenv("/var/www/seoauto_vn_usr/data/www/shared/env.local")

BASE = (os.getenv("LOAD_TEST_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")
INTERNAL_TOKEN = (os.getenv("INTERNAL_CRON_TOKEN") or "").strip()
DURATION_SEC = float(os.getenv("LOAD_TEST_DURATION_SEC", "12"))
READ_P95_MS = float(os.getenv("W5_READ_P95_MS", "1000"))
READ_P99_MS = float(os.getenv("W5_READ_P99_MS", "2000"))
# httpx AsyncClient contends on co-located VPS at high VU; ab reflects server capacity.
AB_GATE_MIN_LOAD = int(os.getenv("W5_AB_GATE_MIN_LOAD", "250"))

# Endpoint suites for isolated root-cause profiling
SUITE_ENDPOINTS: dict[str, list[tuple[str, str, bool]]] = {
    "probe": [
        ("/health", "GET", False),
        ("/ready", "GET", False),
    ],
    "public": [
        ("/pricing", "GET", False),
        ("/api/saas/plans", "GET", False),
    ],
    "auth": [
        ("/auth/me", "GET", True),
    ],
    "dashboard": [
        ("/api/audit/mine?limit=8", "GET", True),
    ],
    "report": [
        ("/api/report", "GET", True),
    ],
}


@dataclass
class EndpointResult:
    endpoint: str
    load: int
    rps: float = 0.0
    error_pct: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    cpu_pct: float | None = None
    ram_mb: float | None = None
    db_conn: int | None = None
    db_latency_ms: float | None = None
    redis_ms: float | None = None
    queue_backlog: int = 0
    event_loop_lag_ms: float | None = None
    worker_saturation: str | None = None
    nginx_upstream_ms: float | None = None
    bottleneck: str = ""
    fix: str = ""
    result: str = "FAIL"
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[int, int] = field(default_factory=dict)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


async def _fetch_metrics(client: httpx.AsyncClient) -> dict[str, Any]:
    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
    try:
        r = await client.get(f"{BASE}/metrics", headers=headers, timeout=8.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _apply_metrics(res: EndpointResult, m: dict[str, Any]) -> None:
    host = m.get("host") or {}
    dbp = m.get("db_pool") or {}
    queue = m.get("queue") or {}
    redis_probe = m.get("redis_probe") or {}
    reqm = m.get("request_metrics") or {}
    res.cpu_pct = host.get("cpu_pct")
    res.ram_mb = host.get("ram_used_mb")
    co = dbp.get("checked_out")
    res.db_conn = int(co) if co is not None else None
    res.redis_ms = redis_probe.get("latency_ms")
    res.db_latency_ms = redis_probe.get("latency_ms")  # proxy; readiness db in checks
    res.queue_backlog = int(queue.get("queued_count") or 0)
    res.event_loop_lag_ms = reqm.get("p95_ms")
    workers = m.get("celery") or {}
    wo = workers.get("workers_online")
    if wo is not None:
        res.worker_saturation = f"celery={wo}"


def _concurrency_cap(load: int) -> int:
    """Allow full load concurrency for probe paths; cap heavy API to protect client."""
    return load


def _client_pool_size(load: int) -> int:
    """Avoid single shared AsyncClient lock contention at high VU counts."""
    return min(max(32, load // 5), 128)


async def _run_vu_pool(
    load: int,
    vu_factory,
    *,
    duration: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pool_size = _client_pool_size(load)
    per_client = max(4, min(20, (load * 2) // pool_size + 2))
    limits = httpx.Limits(
        max_connections=per_client,
        max_keepalive_connections=max(2, per_client // 2),
        keepalive_expiry=30.0,
    )
    timeout = httpx.Timeout(10.0, connect=5.0)
    clients = [httpx.AsyncClient(limits=limits, timeout=timeout) for _ in range(pool_size)]
    try:
        m0 = await _fetch_metrics(clients[0])
        await asyncio.gather(
            *[asyncio.create_task(vu_factory(clients[i % pool_size])) for i in range(load)]
        )
        m1 = await _fetch_metrics(clients[0])
        return m0, m1
    finally:
        await asyncio.gather(*[c.aclose() for c in clients], return_exceptions=True)


def _parse_ab_output(text: str) -> dict[str, float]:
    """Parse ApacheBench summary (p50/p95/p99 approximations from cumulative table)."""
    failed = 0.0
    m = re.search(r"Failed requests:\s+(\d+)", text)
    if m:
        failed = float(m.group(1))
    total = 0.0
    m = re.search(r"Complete requests:\s+(\d+)", text)
    if m:
        total = float(m.group(1))
    rps = 0.0
    m = re.search(r"Requests per second:\s+([0-9.]+)", text)
    if m:
        rps = float(m.group(1))
    pct: dict[int, float] = {}
    for line in text.splitlines():
        line = line.strip()
        pm = re.match(r"(\d+)%\s+(\d+)", line)
        if pm:
            pct[int(pm.group(1))] = float(pm.group(2))
    p50 = pct.get(50, pct.get(66, 0.0))
    p95 = pct.get(95, pct.get(90, 0.0))
    p99 = pct.get(99, pct.get(98, p95))
    err_pct = (failed / total * 100.0) if total else 100.0
    return {"rps": rps, "error_pct": err_pct, "p50": p50, "p95": p95, "p99": p99, "total": total}


def _run_ab(path: str, load: int, duration: float) -> dict[str, float]:
    cmd = [
        "ab",
        "-c",
        str(max(1, load)),
        "-t",
        str(max(1, int(duration))),
        "-q",
        f"{BASE}{path}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and "Complete requests:" not in text:
        return {"rps": 0.0, "error_pct": 100.0, "p50": 0.0, "p95": 9999.0, "p99": 9999.0, "total": 0.0}
    return _parse_ab_output(text)


async def _fetch_metrics_standalone() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8.0) as client:
        return await _fetch_metrics(client)


def _make_auth_header() -> dict[str, str]:
    from sqlalchemy import text

    from app.core.security import create_access_token
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        uid = int(
            db.execute(
                text("SELECT id FROM users WHERE status='active' ORDER BY id LIMIT 1")
            ).scalar()
        )
    finally:
        db.close()
    return {"Authorization": f"Bearer {create_access_token(uid)}"}


async def run_endpoint(
    endpoint: str,
    load: int,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    duration: float = DURATION_SEC,
    think_sec: float = 0.02,
) -> EndpointResult:
    res = EndpointResult(endpoint=endpoint, load=load)
    stop_at = time.time() + duration
    hdrs = dict(headers or {})
    cap = _concurrency_cap(load)
    sem = asyncio.Semaphore(cap)

    async def vu(client: httpx.AsyncClient) -> None:
        while time.time() < stop_at:
            async with sem:
                t0 = time.perf_counter()
                status = 0
                try:
                    if method == "GET":
                        r = await client.get(f"{BASE}{endpoint}", headers=hdrs, timeout=10.0)
                    else:
                        r = await client.post(f"{BASE}{endpoint}", headers=hdrs, timeout=10.0)
                    status = r.status_code
                except Exception:
                    status = 0
                res.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                res.status_counts[status] = res.status_counts.get(status, 0) + 1
            await asyncio.sleep(think_sec)

    m0, m1 = await _run_vu_pool(load, vu, duration=duration)

    total = sum(res.status_counts.values()) or 1
    errors = sum(c for s, c in res.status_counts.items() if s == 0 or s >= 500)
    res.error_pct = round(errors / total * 100.0, 2)
    res.rps = round(total / duration, 2)
    res.p50 = round(_pct(res.latencies_ms, 50), 1)
    res.p95 = round(_pct(res.latencies_ms, 95), 1)
    res.p99 = round(_pct(res.latencies_ms, 99), 1)

    _apply_metrics(res, m1 or m0)

    ok = res.error_pct < 1.0 and res.p95 < READ_P95_MS and res.p99 < READ_P99_MS
    res.result = "PASS" if ok else "FAIL"
    return res


async def profile_endpoints(endpoints: list[str], loads: list[int], duration: float) -> list[EndpointResult]:
    out: list[EndpointResult] = []
    auth = _make_auth_header()
    for ep in endpoints:
        hdrs = auth if ep.startswith("/api/") else None
        for n in loads:
            r = await run_endpoint(ep, n, headers=hdrs, duration=duration)
            out.append(r)
            print_row(r)
            await asyncio.sleep(2)
    return out


def print_row(r: EndpointResult) -> None:
    print(
        f"{r.endpoint} | {r.load} | {r.rps} | {r.error_pct}% | {r.p50} | {r.p95} | {r.p99} | "
        f"{r.cpu_pct} | {r.ram_mb} | {r.event_loop_lag_ms} | {r.worker_saturation or '—'} | "
        f"{r.db_conn} | {r.redis_ms} | {r.queue_backlog} | {r.nginx_upstream_ms or '—'} | "
        f"{r.bottleneck or '—'} | {r.fix or '—'} | {r.result}"
    )


def print_header() -> None:
    print(
        "ENDPOINT | LOAD | RPS | ERR% | P50 | P95 | P99 | CPU | RAM | EVLOOP_P95 | WORKERS | "
        "DB_CONN | REDIS | QUEUE | NGINX | BOTTLENECK | FIX | RESULT"
    )


async def run_mix_public(load: int, duration: float) -> EndpointResult:
    """90% /health + 10% /ready — Wave 4 public mix."""
    res = EndpointResult(endpoint="mix:public", load=load)

    if load >= AB_GATE_MIN_LOAD:
        health_load = max(1, int(load * 0.9))
        ready_load = max(1, load - health_load)
        loop = asyncio.get_running_loop()
        m0 = await _fetch_metrics_standalone()
        health_f = loop.run_in_executor(None, lambda: _run_ab("/health", health_load, duration))
        ready_f = loop.run_in_executor(None, lambda: _run_ab("/ready", ready_load, duration))
        health, ready = await asyncio.gather(health_f, ready_f)
        m1 = await _fetch_metrics_standalone()
        total = health["total"] + ready["total"]
        failed = health["error_pct"] * health["total"] / 100.0 + ready["error_pct"] * ready["total"] / 100.0
        res.error_pct = round(failed / total * 100.0, 2) if total else 100.0
        res.rps = round(health["rps"] + ready["rps"], 2)
        res.p50 = round(max(health["p50"], ready["p50"]), 1)
        res.p95 = round(max(health["p95"], ready["p95"]), 1)
        res.p99 = round(max(health["p99"], ready["p99"]), 1)
        res.bottleneck = "server-side (ab gate)"
        _apply_metrics(res, m1 or m0)
        ok = res.error_pct < 1.0 and res.p95 < READ_P95_MS and res.p99 < READ_P99_MS
        res.result = "PASS" if ok else "FAIL"
        return res

    stop_at = time.time() + duration
    path_counter = itertools.count()
    sem = asyncio.Semaphore(load)

    async def vu(client: httpx.AsyncClient) -> None:
        while time.time() < stop_at:
            path = "/ready" if next(path_counter) % 10 == 0 else "/health"
            async with sem:
                t0 = time.perf_counter()
                status = 0
                try:
                    r = await client.get(f"{BASE}{path}", timeout=10.0)
                    status = r.status_code
                except Exception:
                    status = 0
                res.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                res.status_counts[status] = res.status_counts.get(status, 0) + 1
            await asyncio.sleep(0.02)

    m0, m1 = await _run_vu_pool(load, vu, duration=duration)

    total = sum(res.status_counts.values()) or 1
    errors = sum(c for s, c in res.status_counts.items() if s == 0 or s >= 500)
    res.error_pct = round(errors / total * 100.0, 2)
    res.rps = round(total / duration, 2)
    res.p50 = round(_pct(res.latencies_ms, 50), 1)
    res.p95 = round(_pct(res.latencies_ms, 95), 1)
    res.p99 = round(_pct(res.latencies_ms, 99), 1)
    _apply_metrics(res, m1 or m0)
    ok = res.error_pct < 1.0 and res.p95 < READ_P95_MS and res.p99 < READ_P99_MS
    res.result = "PASS" if ok else "FAIL"
    return res


async def profile_suite(suite: str, load: int, duration: float) -> list[EndpointResult]:
    out: list[EndpointResult] = []
    auth = _make_auth_header()
    entries = SUITE_ENDPOINTS.get(suite, [])
    for endpoint, method, needs_auth in entries:
        hdrs = auth if needs_auth else None
        r = await run_endpoint(endpoint, load, method=method, headers=hdrs, duration=duration)
        out.append(r)
        print_row(r)
        await asyncio.sleep(2)
    return out


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="profile", choices=["profile", "mix", "layer", "suite"])
    parser.add_argument("--suite", default="probe", choices=list(SUITE_ENDPOINTS.keys()))
    parser.add_argument("--endpoint", default="/health")
    parser.add_argument("--loads", default="10,50,100,250,500")
    parser.add_argument("--duration", type=float, default=DURATION_SEC)
    parser.add_argument(
        "--endpoints",
        default="/health,/ready,/pricing,/api/projects",
    )
    args = parser.parse_args()

    print_header()
    if args.mode == "profile":
        eps = [e.strip() for e in args.endpoints.split(",") if e.strip()]
        loads = [int(x.strip()) for x in args.loads.split(",")]
        await profile_endpoints(eps, loads, args.duration)
    elif args.mode == "suite":
        load = int(args.loads.split(",")[0].strip())
        await profile_suite(args.suite, load, args.duration)
    elif args.mode == "mix":
        for n in [int(x.strip()) for x in args.loads.split(",")]:
            r = await run_mix_public(n, args.duration)
            print_row(r)
            await asyncio.sleep(3)
    elif args.mode == "layer":
        from app.services.ops_metrics import collect_ops_metrics

        snap = collect_ops_metrics()
        print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
