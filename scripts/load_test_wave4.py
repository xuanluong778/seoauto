#!/usr/bin/env python3
"""Wave 4 progressive load + failure scenario harness for SEOAuto.vn."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import subprocess
import sys
import time
import uuid
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
DURATION_SEC = float(os.getenv("LOAD_TEST_DURATION_SEC", "20"))
TECH_URL = os.getenv("LOAD_TEST_TECH_URL", "https://example.com/")


@dataclass
class LoadResult:
    load: int
    rps: float = 0.0
    error_pct: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    cpu_pct: float | None = None
    ram_mb: float | None = None
    db_conn: int | None = None
    queue_backlog: int = 0
    result: str = "FAIL"
    notes: str = ""
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[int, int] = field(default_factory=dict)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def _make_tokens(user_ids: list[int]) -> dict[int, str]:
    from app.core.security import create_access_token

    return {uid: create_access_token(uid) for uid in user_ids}


def _load_test_user_ids(limit: int = 8) -> list[int]:
    from sqlalchemy import text

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT u.id FROM users u
                WHERE u.status = 'active'
                ORDER BY u.id ASC
                LIMIT :lim
                """
            ),
            {"lim": limit},
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if ids:
            return ids
    finally:
        db.close()
    return [1]


async def _fetch_metrics(client: httpx.AsyncClient) -> dict[str, Any]:
    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
    try:
        r = await client.get(f"{BASE}/metrics", headers=headers, timeout=5.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


async def _one_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> tuple[int, float]:
    t0 = time.perf_counter()
    status = 0
    try:
        if method == "GET":
            r = await client.get(f"{BASE}{path}", headers=headers, timeout=30.0)
        else:
            r = await client.post(f"{BASE}{path}", headers=headers, json=json_body, timeout=60.0)
        status = r.status_code
    except Exception:
        status = 0
    return status, (time.perf_counter() - t0) * 1000.0


async def _virtual_user(
    uid: int,
    token: str,
    stop_at: float,
    mix: str,
    results: LoadResult,
    *,
    idem_key: str | None = None,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    if idem_key:
        headers["X-Idempotency-Key"] = idem_key
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        i = 0
        while time.time() < stop_at:
            if mix == "public":
                path = ["/health", "/health", "/health", "/health", "/health", "/health", "/health", "/health", "/health", "/ready"][i % 10]
                st, lat = await _one_request(client, "GET", path)
            elif mix == "auth_read":
                path = ["/api/projects", "/content-ai/bulk-jobs/ping", "/health"][i % 3]
                st, lat = await _one_request(client, "GET", path, headers=headers)
            elif mix == "technical":
                body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
                st, lat = await _one_request(
                    client, "POST", "/analyze/technical/jobs", headers=headers, json_body=body
                )
            elif mix == "bulk":
                body = {
                    "keywords": [f"loadtest-{uid}-{i}"],
                    "target_website": "https://example.com",
                    "items": [],
                }
                st, lat = await _one_request(
                    client, "POST", "/content-ai/bulk-jobs/start", headers=headers, json_body=body
                )
            else:
                st, lat = await _one_request(client, "GET", "/health")
            results.latencies_ms.append(lat)
            results.status_counts[st] = results.status_counts.get(st, 0) + 1
            i += 1
            await asyncio.sleep(0.05 if mix == "public" else 0.2)


async def run_load(concurrency: int, mix: str = "public") -> LoadResult:
    user_ids = _load_test_user_ids(max(4, min(concurrency, 8)))
    tokens = _make_tokens(user_ids)
    res = LoadResult(load=concurrency)
    stop_at = time.time() + DURATION_SEC
    tasks = []
    for i in range(concurrency):
        uid = user_ids[i % len(user_ids)]
        tasks.append(asyncio.create_task(_virtual_user(uid, tokens[uid], stop_at, mix, res)))
    metrics_before = {}
    metrics_after = {}
    async with httpx.AsyncClient() as mc:
        metrics_before = await _fetch_metrics(mc)
        await asyncio.gather(*tasks)
        metrics_after = await _fetch_metrics(mc)

    total = sum(res.status_counts.values()) or 1
    errors = sum(c for s, c in res.status_counts.items() if s == 0 or s >= 500)
    res.error_pct = round(errors / total * 100.0, 2)
    elapsed = DURATION_SEC
    res.rps = round(total / elapsed, 2)
    res.p50 = round(_pct(res.latencies_ms, 50), 1)
    res.p95 = round(_pct(res.latencies_ms, 95), 1)
    res.p99 = round(_pct(res.latencies_ms, 99), 1)
    m = metrics_after or metrics_before
    host = m.get("host") or {}
    dbp = m.get("db_pool") or {}
    queue = m.get("queue") or {}
    res.cpu_pct = host.get("cpu_pct")
    res.ram_mb = host.get("ram_used_mb")
    checked = dbp.get("checked_out")
    res.db_conn = int(checked) if checked is not None else None
    res.queue_backlog = int(queue.get("queued_count") or 0)
    # PASS: <1% 5xx/timeout, p99 < 5s for public, queue not exploding
    ok = res.error_pct < 1.0 and res.p99 < 5000
    if mix in ("technical", "bulk"):
        ok = res.error_pct < 5.0 and res.p99 < 30000  # job enqueue paths tolerate 429/fairness
    if res.queue_backlog > concurrency * 3 and mix != "public":
        ok = False
        res.notes += " queue_backlog_high"
    res.result = "PASS" if ok else "FAIL"
    return res


def _print_row(r: LoadResult) -> None:
    print(
        f"{r.load} | {r.rps} | {r.error_pct}% | {r.p50} | {r.p95} | {r.p99} | "
        f"{r.cpu_pct} | {r.ram_mb} | {r.db_conn} | {r.queue_backlog} | {r.result}"
        + (f"  # {r.notes}" if r.notes else "")
    )


async def scenario_duplicate_submit() -> tuple[str, str]:
    user_ids = _load_test_user_ids(1)
    uid = user_ids[0]
    token = _make_tokens([uid])[uid]
    idem = f"wave4-dup:{uid}:{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": idem}
    body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
    job_ids: set[str] = set()
    async with httpx.AsyncClient() as client:
        for _ in range(5):
            r = await client.post(
                f"{BASE}/analyze/technical/jobs", headers=headers, json=body, timeout=30.0
            )
            if r.status_code < 500:
                data = r.json()
                jid = str(data.get("job_id") or "")
                if jid:
                    job_ids.add(jid)
            await asyncio.sleep(0.1)
    ok = len(job_ids) <= 1
    return ("PASS" if ok else "FAIL", f"unique_job_ids={len(job_ids)} ids={list(job_ids)[:3]}")


async def scenario_tenant_isolation() -> tuple[str, str]:
    ids = _load_test_user_ids(2)
    if len(ids) < 2:
        return ("SKIP", "need>=2 users")
    t1, t2 = _make_tokens([ids[0]])[ids[0]], _make_tokens([ids[1]])[ids[1]]
    idem_a = f"wave4-tenant-a:{uuid.uuid4().hex[:8]}"
    body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
    async with httpx.AsyncClient() as client:
        ra = await client.post(
            f"{BASE}/analyze/technical/jobs",
            headers={"Authorization": f"Bearer {t1}", "X-Idempotency-Key": idem_a},
            json=body,
            timeout=30.0,
        )
        if ra.status_code >= 500:
            return ("FAIL", f"user_a_start={ra.status_code}")
        job_a = ra.json().get("job_id")
        rb = await client.get(
            f"{BASE}/analyze/technical/jobs/{job_a}",
            headers={"Authorization": f"Bearer {t2}"},
            timeout=15.0,
        )
    ok = rb.status_code in (403, 404)
    return ("PASS" if ok else "FAIL", f"cross_poll_status={rb.status_code}")


def scenario_worker_crash_recovery() -> tuple[str, str]:
    from app.services.queue_fairness import _redis

    r = _redis()
    before = {}
    if r:
        for k in r.scan_iter("queue:slots:*", count=20):
            before[k] = r.zcard(k)
    subprocess.run(["pm2", "restart", "seoauto-worker"], capture_output=True, timeout=30)
    time.sleep(8)
    after = {}
    if r:
        for k in r.scan_iter("queue:slots:*", count=20):
            after[k] = r.zcard(k)
    stale = sum(after.values()) > sum(before.values()) + 2
    return ("PASS" if not stale else "FAIL", f"slots_before={sum(before.values())} after={sum(after.values())}")


def scenario_redis_reconnect() -> tuple[str, str]:
    from app.services.health_probes import check_redis

    ok1 = check_redis().get("ok")
    # Force new client by importing rate limiter redis reset
    try:
        import app.services.rate_limiter as rl

        rl._redis_client = None
    except Exception:
        pass
    ok2 = check_redis().get("ok")
    return ("PASS" if ok1 and ok2 else "FAIL", f"before={ok1} after={ok2}")


def scenario_db_reconnect() -> tuple[str, str]:
    from app.services.health_probes import check_database

    ok1 = check_database().get("ok")
    ok2 = check_database().get("ok")
    return ("PASS" if ok1 and ok2 else "FAIL", f"probe1={ok1} probe2={ok2}")


async def scenario_queue_recovery() -> tuple[str, str]:
    async with httpx.AsyncClient() as client:
        headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
        m1 = await _fetch_metrics(client)
        await asyncio.sleep(35)
        m2 = await _fetch_metrics(client)
    q1 = (m1.get("queue") or {}).get("queued_count", 0)
    q2 = (m2.get("queue") or {}).get("queued_count", 0)
    workers = (m2.get("celery") or {}).get("workers_online", 0)
    ok = workers >= 1
    return ("PASS" if ok else "FAIL", f"queued {q1}->{q2} workers={workers}")


async def main() -> int:
    global DURATION_SEC
    parser = argparse.ArgumentParser()
    parser.add_argument("--loads", default="10,50,100,250,500")
    parser.add_argument("--mix", default="public", choices=["public", "auth_read", "technical", "bulk"])
    parser.add_argument("--scenario", default="")
    parser.add_argument("--duration", type=float, default=DURATION_SEC)
    args = parser.parse_args()
    DURATION_SEC = args.duration

    if args.scenario:
        scenarios = {
            "duplicate": scenario_duplicate_submit,
            "tenant": scenario_tenant_isolation,
            "worker_crash": scenario_worker_crash_recovery,
            "redis": scenario_redis_reconnect,
            "db": scenario_db_reconnect,
            "queue_recovery": scenario_queue_recovery,
        }
        fn = scenarios.get(args.scenario)
        if not fn:
            print("unknown scenario", args.scenario)
            return 1
        if asyncio.iscoroutinefunction(fn):
            status, detail = await fn()
        else:
            status, detail = fn()
        print(f"{args.scenario.upper()} = {status}  ({detail})")
        return 0 if status == "PASS" else 1

    print("LOAD | RPS | ERROR% | P50 | P95 | P99 | CPU | RAM | DB_CONN | QUEUE_BACKLOG | RESULT")
    results: dict[int, LoadResult] = {}
    for raw in args.loads.split(","):
        n = int(raw.strip())
        r = await run_load(n, mix=args.mix)
        results[n] = r
        _print_row(r)
        await asyncio.sleep(3)

    out = {
        "10_USER_LOAD": results.get(10, LoadResult(10)).result,
        "50_USER_LOAD": results.get(50, LoadResult(50)).result,
        "100_USER_LOAD": results.get(100, LoadResult(100)).result,
        "250_USER_LOAD": results.get(250, LoadResult(250)).result,
        "500_USER_LOAD": results.get(500, LoadResult(500)).result,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
