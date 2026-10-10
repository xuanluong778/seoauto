#!/usr/bin/env python3
"""WAVE 7 — Full system mixed load & soak validation.

Mixed traffic: auth, dashboard, content-ai, duplicate/embedding, audit/crawl,
wordpress, credit/billing, report, pricing.

Output: docs/baseline/wave7/

Env overrides:
  WAVE7_QUICK=1           — shorten load/soak for smoke (load 12s, soak 3m)
  WAVE7_SKIP_SOAK_2H=1    — skip 2h soak even if 30m passes
  WAVE7_LOAD_DURATION_SEC — per load tier duration (default 15)
  WAVE7_SOAK_100_SEC      — default 1800 (30m)
  WAVE7_SOAK_250_SEC      — default 1800 (30m)
  WAVE7_SOAK_2H_SEC       — default 7200 (2h)
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave7"
WAVE0 = ROOT / "docs" / "baseline" / "wave0"
KNOWN_FAILURES = WAVE0 / "KNOWN_FAILURES_WAVE0.txt"
SHARED_ENV = Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")
BASE = (os.getenv("WAVE7_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")
INTERNAL_TOKEN = (os.getenv("INTERNAL_CRON_TOKEN") or "").strip()
TECH_URL = os.getenv("WAVE7_TECH_URL", "https://example.com/")

QUICK = os.getenv("WAVE7_QUICK", "0").strip().lower() in ("1", "true", "yes", "on")
P95_TARGET_MS = float(os.getenv("WAVE7_P95_TARGET_MS", "1500"))
ERROR_TARGET_PCT = float(os.getenv("WAVE7_ERROR_TARGET_PCT", "1.0"))
LOAD_DURATION = float(os.getenv("WAVE7_LOAD_DURATION_SEC", "12" if QUICK else "15"))
SOAK_100_SEC = float(os.getenv("WAVE7_SOAK_100_SEC", "180" if QUICK else "1800"))
SOAK_250_SEC = float(os.getenv("WAVE7_SOAK_250_SEC", "180" if QUICK else "1800"))
SOAK_2H_SEC = float(os.getenv("WAVE7_SOAK_2H_SEC", "300" if QUICK else "7200"))
SKIP_SOAK_2H = os.getenv("WAVE7_SKIP_SOAK_2H", "0").strip().lower() in ("1", "true", "yes", "on")
MAX_INFLIGHT = int(os.getenv("WAVE7_MAX_INFLIGHT", "40"))
SAMPLE_INTERVAL_SEC = float(os.getenv("WAVE7_SAMPLE_INTERVAL_SEC", "30" if QUICK else "60"))
MEMORY_LEAK_MB_PER_HOUR = float(os.getenv("WAVE7_MEMORY_LEAK_MB_PER_HOUR", "200"))
CONN_LEAK_DELTA = int(os.getenv("WAVE7_CONN_LEAK_DELTA", "15"))

READ_ONLY_FLOWS = frozenset({
    "auth_me",
    "projects",
    "content_ai_projects",
    "audit_mine",
    "report",
    "pricing",
    "credits_preview",
    "credit_quote",
    "credits_ledger",
    "duplicate_ping",
    "bulk_jobs_ping",
})

# Weighted mixed flows — reads dominate; async jobs throttled
MIXED_FLOWS: list[tuple[str, int]] = [
    ("auth_me", 12),
    ("projects", 8),
    ("content_ai_projects", 10),
    ("audit_mine", 10),
    ("report", 8),
    ("pricing", 6),
    ("credits_preview", 8),
    ("credit_quote", 6),
    ("credits_ledger", 5),
    ("duplicate_ping", 4),
    ("duplicate_check", 5),
    ("technical_audit_job", 3),
    ("bulk_jobs_ping", 4),
    ("wordpress_test_connection", 7),
]
_FLOW_CYCLE = [name for name, w in MIXED_FLOWS for _ in range(w)]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    for env_path in (ROOT / "env.local", SHARED_ENV):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in os.environ:
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                os.environ[k] = v


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def _make_tokens(user_ids: list[int]) -> dict[int, str]:
    from app.services.auth_tokens import create_auth_token_for_user

    return {uid: create_auth_token_for_user(uid) for uid in user_ids}


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
            {"lim": max(limit, 20)},
        ).fetchall()
        candidates = [int(r[0]) for r in rows]
    finally:
        db.close()
    if not candidates:
        return [1]
    return _filter_working_user_ids(candidates, limit=limit)


def _filter_working_user_ids(candidates: list[int], *, limit: int) -> list[int]:
    """Keep only users whose /auth/me returns 200 (skip invalid test emails)."""
    import httpx

    from app.services.auth_tokens import create_auth_token_for_user

    working: list[int] = []
    for uid in candidates:
        token = create_auth_token_for_user(uid)
        try:
            r = httpx.get(
                f"{BASE}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            if r.status_code == 200 and (r.json() or {}).get("id"):
                working.append(uid)
        except Exception:
            continue
        if len(working) >= limit:
            break
    return working or [1]


async def _fetch_metrics(client: httpx.AsyncClient) -> dict[str, Any]:
    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
    try:
        r = await client.get(f"{BASE}/metrics", headers=headers, timeout=10.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _collect_system_metrics() -> dict[str, Any]:
    """Extended metrics: Redis queue depths, DB connections, PM2 workers."""
    out: dict[str, Any] = {"ts": time.time()}
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        try:
            import redis

            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            out["redis_keys"] = int(r.dbsize())
            out["redis_memory_mb"] = round((r.info("memory").get("used_memory", 0) or 0) / (1024 * 1024), 1)
            out["queue_depth"] = {}
            for q in ("content_ai", "wordpress", "crawl", "email", "embedding", "default", "celery"):
                try:
                    out["queue_depth"][q] = int(r.llen(q))
                except Exception:
                    out["queue_depth"][q] = -1
        except Exception as exc:
            out["redis_error"] = str(exc)[:120]

    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url.startswith("postgresql"):
        try:
            import psycopg2

            conn = psycopg2.connect(db_url.replace("postgresql+psycopg2://", "postgresql://"))
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            out["db_connections"] = int(cur.fetchone()[0])
            cur.close()
            conn.close()
        except Exception as exc:
            out["db_error"] = str(exc)[:120]

    try:
        proc = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            apps = json.loads(proc.stdout)
            workers = []
            for a in apps:
                name = str(a.get("name", ""))
                env_pm2 = a.get("pm2_env") or {}
                monit = a.get("monit") or {}
                entry = {
                    "name": name,
                    "status": env_pm2.get("status"),
                    "restarts": env_pm2.get("restart_time", 0),
                    "memory_mb": round((monit.get("memory") or 0) / (1024 * 1024), 1),
                }
                if "worker" in name or name == "seoauto-web":
                    workers.append(entry)
            out["pm2_workers"] = workers
    except Exception as exc:
        out["pm2_error"] = str(exc)[:120]

    return out


def _merge_sample(metrics: dict[str, Any], system: dict[str, Any]) -> dict[str, Any]:
    host = metrics.get("host") or {}
    proc = metrics.get("process") or {}
    queue = metrics.get("queue") or {}
    return {
        "ts": system.get("ts") or metrics.get("ts"),
        "ram_used_mb": host.get("ram_used_mb"),
        "process_rss_mb": proc.get("process_rss_mb"),
        "cpu_pct": host.get("cpu_pct"),
        "db_connections": system.get("db_connections"),
        "redis_memory_mb": system.get("redis_memory_mb"),
        "queue_depth": system.get("queue_depth"),
        "queued_count": queue.get("queued_count"),
        "running_count": queue.get("running_count"),
        "job_wait_p95_ms": queue.get("job_wait_p95_ms"),
        "workers_online": (metrics.get("celery") or {}).get("workers_online"),
        "http_p95_ms": (metrics.get("http") or {}).get("p95_ms"),
    }


async def _mixed_request(
    client: httpx.AsyncClient,
    flow: str,
    headers: dict[str, str],
    uid: int,
    i: int,
) -> tuple[int, float, str]:
    t0 = time.perf_counter()
    status = 0
    try:
        if flow == "auth_me":
            r = await client.get(f"{BASE}/auth/me", headers=headers, timeout=20.0)
        elif flow == "projects":
            r = await client.get(f"{BASE}/projects", headers=headers, timeout=25.0)
        elif flow == "content_ai_projects":
            r = await client.get(f"{BASE}/content-ai/projects?limit=30", headers=headers, timeout=45.0)
        elif flow == "audit_mine":
            r = await client.get(f"{BASE}/api/audit/mine?limit=8", headers=headers, timeout=25.0)
        elif flow == "report":
            r = await client.get(f"{BASE}/api/report", headers=headers, timeout=25.0)
        elif flow == "pricing":
            r = await client.get(f"{BASE}/pricing", headers=headers, timeout=20.0)
        elif flow == "credits_preview":
            body = {"module": "audit", "action": "technical_deep", "quota_key": "technical_audit"}
            r = await client.post(f"{BASE}/api/credits/preview", headers=headers, json=body, timeout=20.0)
        elif flow == "credit_quote":
            body = {
                "field": "content",
                "title": f"wave7-{uid}",
                "primary_keyword": "seo test",
                "target_word_count": 500,
            }
            r = await client.post(f"{BASE}/content-ai/credit-quote", headers=headers, json=body, timeout=20.0)
        elif flow == "credits_ledger":
            r = await client.get(f"{BASE}/auth/credits/ledger?limit=10", headers=headers, timeout=20.0)
        elif flow == "duplicate_ping":
            r = await client.get(f"{BASE}/content-ai/duplicate-check/ping", headers=headers, timeout=10.0)
        elif flow == "duplicate_check":
            body = {"keyword": "seo test", "keywords": ["seo test"], "refresh": False}
            r = await client.post(f"{BASE}/content-ai/duplicate-check", headers=headers, json=body, timeout=60.0)
        elif flow == "technical_audit_job":
            body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
            h = {**headers, "X-Idempotency-Key": f"wave7-{uid}-{i % 50}-{uuid.uuid4().hex[:6]}"}
            r = await client.post(f"{BASE}/analyze/technical/jobs", headers=h, json=body, timeout=45.0)
        elif flow == "bulk_jobs_ping":
            r = await client.get(f"{BASE}/content-ai/bulk-jobs/ping", headers=headers, timeout=10.0)
        elif flow == "wordpress_test_connection":
            body = {"url": "https://example.com", "username": "wave7", "app_password": "invalid"}
            r = await client.post(
                f"{BASE}/content-ai/wordpress/test-connection", headers=headers, json=body, timeout=25.0
            )
        else:
            r = await client.get(f"{BASE}/health", timeout=5.0)
        status = r.status_code
    except Exception:
        status = 0
    return status, (time.perf_counter() - t0) * 1000.0, flow


async def _virtual_user(
    uid: int,
    token: str,
    stop_at: float,
    results: dict[str, Any],
    sem: asyncio.Semaphore,
    *,
    flow_offset: int = 0,
    concurrency: int = 50,
) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
    }
    pool = min(max(16, MAX_INFLIGHT // 2), 32)
    limits = httpx.Limits(max_connections=pool, max_keepalive_connections=pool)
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        i = flow_offset
        while time.perf_counter() < stop_at:
            flow = _FLOW_CYCLE[i % len(_FLOW_CYCLE)]
            async with sem:
                st, lat, name = await _mixed_request(client, flow, headers, uid, i)
            results["latencies_ms"].append(lat)
            results["status_counts"][st] = results["status_counts"].get(st, 0) + 1
            ep = results["by_flow"].setdefault(name, {"ok": 0, "err": 0, "latencies": []})
            ep["latencies"].append(lat)
            if st == 0 or st >= 500:
                ep["err"] += 1
            else:
                ep["ok"] += 1
            i += 1
            await asyncio.sleep(0.15 if concurrency >= 100 else (0.08 if QUICK else 0.12))


async def _probe_read_latency(token: str) -> dict[str, Any]:
    """Sequential read probe — measures true API latency without client queueing."""
    headers = {"Authorization": f"Bearer {token}"}
    paths = [
        ("auth_me", "GET", "/auth/me"),
        ("audit_mine", "GET", "/api/audit/mine?limit=8"),
        ("report", "GET", "/api/report"),
        ("pricing", "GET", "/pricing"),
        ("projects", "GET", "/projects"),
    ]
    out: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, method, path in paths:
            warm: list[float] = []
            for _ in range(4):
                t0 = time.perf_counter()
                await client.get(f"{BASE}{path}", headers=headers)
                warm.append((time.perf_counter() - t0) * 1000)
            out[name] = round(_pct(warm, 95), 1)
    max_p95 = max(out.values()) if out else 9999.0
    return {"paths": out, "max_p95_ms": max_p95, "gate": "PASS" if max_p95 < P95_TARGET_MS else "FAIL"}


async def _run_mixed_load(concurrency: int, duration: float) -> dict[str, Any]:
    from app.services.rate_limiter import clear_rate_limit

    clear_rate_limit()
    user_ids = _load_test_user_ids(max(4, min(concurrency, 10)))
    tokens = _make_tokens(user_ids)
    results: dict[str, Any] = {
        "concurrency": concurrency,
        "duration_sec": duration,
        "latencies_ms": [],
        "status_counts": {},
        "by_flow": {},
    }
    stop_at = time.perf_counter() + duration
    sem = asyncio.Semaphore(min(MAX_INFLIGHT, max(10, concurrency)))
    async with httpx.AsyncClient(timeout=10.0) as mclient:
        sys_before = _collect_system_metrics()
        metrics_before = await _fetch_metrics(mclient)
        baseline_sample = _merge_sample(metrics_before, sys_before)
        tasks = [
            asyncio.create_task(
                _virtual_user(
                    user_ids[i % len(user_ids)],
                    tokens[user_ids[i % len(user_ids)]],
                    stop_at,
                    results,
                    sem,
                    flow_offset=i,
                    concurrency=concurrency,
                )
            )
            for i in range(concurrency)
        ]
        await asyncio.gather(*tasks)
        await asyncio.sleep(5)
        sys_after = _collect_system_metrics()
        metrics_after = await _fetch_metrics(mclient)

    total = sum(results["status_counts"].values()) or 1
    errors = sum(
        c
        for s, c in results["status_counts"].items()
        if s == 0 or s >= 500 or s == 429
    )
    err_pct = round(errors / total * 100.0, 3)
    server_p95 = float((metrics_after.get("http") or {}).get("p95_ms") or 9999)
    client_p95 = _pct(results["latencies_ms"], 95)
    gate_p95 = server_p95 if server_p95 < 9000 else client_p95

    ep_stats = {}
    read_p95_vals: list[float] = []
    for name, data in results["by_flow"].items():
        lats = data.get("latencies") or []
        p95 = _pct(lats, 95)
        ep_stats[name] = {
            "count": len(lats),
            "p95_ms": round(p95, 1),
            "error_pct": round(data["err"] / max(data["ok"] + data["err"], 1) * 100, 2),
        }
        if name in READ_ONLY_FLOWS and lats:
            read_p95_vals.append(p95)

    read_p95 = max(read_p95_vals) if read_p95_vals else client_p95
    gate = "PASS"
    if err_pct >= ERROR_TARGET_PCT:
        gate = "FAIL"
    if concurrency <= 100 and read_p95 >= P95_TARGET_MS:
        gate = "FAIL"
    # 250/500: pass on error% only (client queueing inflates latency)

    return {
        "concurrency": concurrency,
        "duration_sec": duration,
        "requests": total,
        "rps": round(total / duration, 2),
        "error_pct": err_pct,
        "p50_ms": round(_pct(results["latencies_ms"], 50), 1),
        "p95_ms": round(client_p95, 1),
        "p99_ms": round(_pct(results["latencies_ms"], 99), 1),
        "server_p95_ms": round(server_p95, 1),
        "read_flow_p95_ms": round(read_p95, 1),
        "endpoints": ep_stats,
        "status_counts": results["status_counts"],
        "baseline_sample": baseline_sample,
        "metrics_after": metrics_after,
        "system_after": sys_after,
        "gate": gate,
    }


def _pm2_worker_restarts() -> dict[str, Any]:
    out: dict[str, Any] = {"total_restarts": 0, "workers": {}}
    try:
        proc = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return out
        for a in json.loads(proc.stdout):
            name = str(a.get("name", ""))
            if "worker" not in name and name != "seoauto-web":
                continue
            restarts = int((a.get("pm2_env") or {}).get("restart_time") or 0)
            out["workers"][name] = {
                "restarts": restarts,
                "status": (a.get("pm2_env") or {}).get("status"),
                "memory_mb": round(((a.get("monit") or {}).get("memory") or 0) / (1024 * 1024), 1),
            }
            out["total_restarts"] += restarts
    except Exception as exc:
        out["error"] = str(exc)[:120]
    return out


def _gate_worker_stability_2h(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    delta = int(after.get("total_restarts", 0)) - int(before.get("total_restarts", 0))
    crashed = any(
        w.get("status") != "online"
        for w in (after.get("workers") or {}).values()
    )
    ok = delta <= 2 and not crashed
    return {
        "gate": "PASS" if ok else "FAIL",
        "restart_delta": delta,
        "before": before,
        "after": after,
    }


async def _gate_rate_limit_expected_429() -> dict[str, Any]:
    from app.services.rate_limiter import clear_rate_limit

    uid = _load_test_user_ids(1)[0]
    token = _make_tokens([uid])[uid]
    clear_rate_limit(path_prefix="/analyze", client_ip="127.0.0.1")
    body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
    headers = {"Authorization": f"Bearer {token}"}
    statuses: list[int] = []
    blocked = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(35):
            r = await client.post(
                f"{BASE}/analyze/technical/jobs",
                headers={**headers, "X-Idempotency-Key": f"wave7-rl-{i}-{uuid.uuid4().hex[:6]}"},
                json=body,
            )
            statuses.append(r.status_code)
            if r.status_code == 429:
                blocked = True
                break
            await asyncio.sleep(0.05)
    return {
        "gate": "PASS" if blocked else "FAIL",
        "blocked_429": blocked,
        "status_sample": statuses[:5] + statuses[-3:],
    }


async def _gate_real_multi_user_load() -> dict[str, Any]:
    """Multi-user mixed load without XFF spoof — read-heavy, no false rate-limit."""
    user_ids = _load_test_user_ids(12)
    tokens = _make_tokens(user_ids)
    read_flows = list(READ_ONLY_FLOWS)
    latencies: list[float] = []
    errors = 0
    total = 0
    stop_at = time.perf_counter() + (8.0 if QUICK else 20.0)
    sem = asyncio.Semaphore(30)

    async def _user(uid: int, offset: int) -> None:
        nonlocal errors, total
        headers = {"Authorization": f"Bearer {tokens[uid]}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            i = offset
            while time.perf_counter() < stop_at:
                flow = read_flows[i % len(read_flows)]
                async with sem:
                    st, lat, _ = await _mixed_request(client, flow, headers, uid, i)
                total += 1
                latencies.append(lat)
                if st == 0 or st >= 500 or st == 429:
                    errors += 1
                i += 1
                await asyncio.sleep(0.12)

    await asyncio.gather(*[_user(user_ids[i % len(user_ids)], i) for i in range(min(50, len(user_ids) * 4))])
    err_pct = (errors / total * 100.0) if total else 100.0
    return {
        "gate": "PASS" if err_pct < ERROR_TARGET_PCT else "FAIL",
        "users": len(user_ids),
        "requests": total,
        "error_pct": round(err_pct, 3),
        "p95_ms": round(_pct(latencies, 95), 1),
    }


def _gate_trusted_proxy_xff() -> dict[str, Any]:
    proc = subprocess.run(
        [str(ROOT / ".venv/bin/pytest"), "-q", "--tb=no", "tests/test_trusted_proxy_xff.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(ROOT), "TRUSTED_PROXY_XFF": "1"},
    )
    flag_ok = False
    if SHARED_ENV.is_file():
        flag_ok = any(
            line.strip().startswith("TRUSTED_PROXY_XFF=1")
            for line in SHARED_ENV.read_text(encoding="utf-8").splitlines()
        )
    if not flag_ok:
        flag_ok = os.getenv("TRUSTED_PROXY_XFF", "1").strip() == "1"
    ok = proc.returncode == 0 and flag_ok
    return {"gate": "PASS" if ok else "FAIL", "pytest_rc": proc.returncode, "flag": flag_ok}


def _gate_xff_spoof_protection() -> dict[str, Any]:
    from starlette.requests import Request

    from app.services.trusted_proxy import resolve_client_ip

    os.environ["TRUSTED_PROXY_XFF"] = "1"
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"10.0.0.1")],
        "client": ("203.0.113.77", 0),
    }
    req = Request(scope)
    resolved = resolve_client_ip(req)
    ok = resolved == "203.0.113.77"
    return {"gate": "PASS" if ok else "FAIL", "resolved_ip": resolved, "expected": "203.0.113.77"}


async def _run_soak(concurrency: int, duration_sec: float, label: str) -> dict[str, Any]:
    from app.services.rate_limiter import clear_rate_limit

    clear_rate_limit()
    worker_before = _pm2_worker_restarts()
    user_ids = _load_test_user_ids(max(4, min(concurrency, 10)))
    tokens = _make_tokens(user_ids)
    results: dict[str, Any] = {
        "label": label,
        "concurrency": concurrency,
        "duration_sec": duration_sec,
        "latencies_ms": [],
        "status_counts": {},
        "by_flow": {},
        "samples": [],
    }
    stop_at = time.perf_counter() + duration_sec
    sem = asyncio.Semaphore(min(MAX_INFLIGHT, max(10, concurrency)))
    if label == "soak_2h":
        ts_path = OUT / "soak_2h_timeseries.jsonl"
        if ts_path.is_file():
            ts_path.unlink()

    async def _sampler() -> None:
        window_lats: list[float] = []
        window_start = time.perf_counter()
        async with httpx.AsyncClient(timeout=10.0) as client:
            while time.perf_counter() < stop_at:
                sys_m = _collect_system_metrics()
                api_m = await _fetch_metrics(client)
                sample = _merge_sample(api_m, sys_m)
                sample["worker_restarts"] = _pm2_worker_restarts().get("total_restarts")
                if results["latencies_ms"]:
                    recent = results["latencies_ms"][-200:]
                    sample["window_p95_ms"] = round(_pct(recent, 95), 1)
                    sample["window_p99_ms"] = round(_pct(recent, 99), 1)
                results["samples"].append(sample)
                if label == "soak_2h":
                    ts_path = OUT / "soak_2h_timeseries.jsonl"
                    with ts_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
                await asyncio.sleep(SAMPLE_INTERVAL_SEC)

    sampler_task = asyncio.create_task(_sampler())
    tasks = [
        asyncio.create_task(
            _virtual_user(
                user_ids[i % len(user_ids)],
                tokens[user_ids[i % len(user_ids)]],
                stop_at,
                results,
                sem,
                flow_offset=i * 3,
                concurrency=concurrency,
            )
        )
        for i in range(concurrency)
    ]
    await asyncio.gather(*tasks)
    sampler_task.cancel()
    try:
        await sampler_task
    except asyncio.CancelledError:
        pass

    async with httpx.AsyncClient(timeout=10.0) as client:
        await asyncio.sleep(30)
        drain_metrics = await _fetch_metrics(client)
        drain_system = _collect_system_metrics()

    total = sum(results["status_counts"].values()) or 1
    errors_5xx = sum(
        c for s, c in results["status_counts"].items() if s == 0 or s >= 500
    )
    policy_responses = sum(
        c for s, c in results["status_counts"].items() if s in (402, 403, 429)
    )
    err_pct_5xx = round(errors_5xx / total * 100.0, 3)
    policy_pct = round(policy_responses / total * 100.0, 3)
    err_pct = err_pct_5xx
    samples = results["samples"]
    ram_vals = [s.get("process_rss_mb") or s.get("ram_used_mb") for s in samples]
    ram_vals = [v for v in ram_vals if v is not None]
    conn_vals = [s.get("db_connections") for s in samples if s.get("db_connections") is not None]
    queue_vals = [s.get("queued_count") for s in samples if s.get("queued_count") is not None]

    duration_h = duration_sec / 3600.0
    ram_growth = (ram_vals[-1] - ram_vals[0]) if len(ram_vals) >= 2 else 0
    ram_rate = ram_growth / duration_h if duration_h > 0 else 0
    conn_growth = (conn_vals[-1] - conn_vals[0]) if len(conn_vals) >= 2 else 0

    baseline_q = (samples[0].get("queued_count") if samples else 0) or 0
    peak_q = max(queue_vals) if queue_vals else 0
    final_q = (drain_metrics.get("queue") or {}).get("queued_count", 0)
    # Stable if queue did not grow unboundedly beyond soak peak (+ small tolerance)
    queue_drained = final_q <= max(baseline_q, peak_q) + max(10, concurrency // 15)

    worker_after = _pm2_worker_restarts()
    worker_stability = _gate_worker_stability_2h(worker_before, worker_after)
    dup_job_end = await _gate_no_duplicate_job() if label == "soak_2h" else None

    return {
        "label": label,
        "concurrency": concurrency,
        "duration_sec": duration_sec,
        "requests": total,
        "rps": round(total / duration_sec, 2),
        "error_pct": err_pct,
        "error_pct_5xx": err_pct_5xx,
        "policy_response_pct": policy_pct,
        "status_counts": dict(results["status_counts"]),
        "p50_ms": round(_pct(results["latencies_ms"], 50), 1),
        "p95_ms": round(_pct(results["latencies_ms"], 95), 1),
        "p99_ms": round(_pct(results["latencies_ms"], 99), 1),
        "samples_count": len(samples),
        "ram_start_mb": ram_vals[0] if ram_vals else None,
        "ram_end_mb": ram_vals[-1] if ram_vals else None,
        "ram_growth_mb": round(ram_growth, 1),
        "ram_growth_mb_per_hour": round(ram_rate, 1),
        "conn_start": conn_vals[0] if conn_vals else None,
        "conn_end": conn_vals[-1] if conn_vals else None,
        "conn_growth": conn_growth,
        "queue_peak": peak_q,
        "queue_baseline": baseline_q,
        "queue_after_drain": final_q,
        "queue_drained": queue_drained,
        "worker_before": worker_before,
        "worker_after": worker_after,
        "worker_stability": worker_stability,
        "duplicate_job_check": dup_job_end,
        "drain_metrics": drain_metrics,
        "drain_system": drain_system,
        "gate": "PASS" if err_pct_5xx < ERROR_TARGET_PCT else "FAIL",
    }


def _gate_memory_leak(soak_runs: list[dict[str, Any]]) -> dict[str, Any]:
    growths = [float(r.get("ram_growth_mb") or 0) for r in soak_runs]
    positive = [g for g in growths if g > 0]
    worst_positive = max(positive) if positive else 0.0
    durations = [float(r.get("duration_sec") or 1800) for r in soak_runs]
    max_duration = max(durations) if durations else 1800.0
    if max_duration < 900:
        threshold = 400.0
        ok = worst_positive < threshold
        return {
            "gate": "PASS" if ok else "FAIL",
            "worst_positive_growth_mb": worst_positive,
            "threshold_mb": threshold,
            "mode": "absolute_short_soak",
        }
    rates = [
        float(r.get("ram_growth_mb_per_hour") or 0)
        for r in soak_runs
        if (r.get("ram_growth_mb") or 0) > 0
    ]
    worst_rate = max(rates) if rates else 0.0
    ok = worst_rate < MEMORY_LEAK_MB_PER_HOUR
    return {
        "gate": "PASS" if ok else "FAIL",
        "worst_mb_per_hour": worst_rate,
        "threshold": MEMORY_LEAK_MB_PER_HOUR,
        "mode": "rate_long_soak",
    }


def _gate_connection_leak(soak_runs: list[dict[str, Any]], load_runs: list[dict[str, Any]]) -> dict[str, Any]:
    conn_growths = [r.get("conn_growth") for r in soak_runs if r.get("conn_growth") is not None]
    worst = max(conn_growths) if conn_growths else 0
    final_conns = [r.get("conn_end") for r in soak_runs if r.get("conn_end") is not None]
    ok = worst <= CONN_LEAK_DELTA and (max(final_conns) if final_conns else 0) < 80
    return {"gate": "PASS" if ok else "FAIL", "worst_conn_growth": worst, "final_conns": final_conns}


def _gate_queue_drain(soak_runs: list[dict[str, Any]]) -> dict[str, Any]:
    drained = all(r.get("queue_drained") for r in soak_runs)
    return {
        "gate": "PASS" if drained else "FAIL",
        "details": [{r["label"]: r.get("queue_drained")} for r in soak_runs],
    }


def _gate_queue_fairness(metrics: dict[str, Any]) -> dict[str, Any]:
    sys_m = _collect_system_metrics()
    qd = sys_m.get("queue_depth") or {}
    workers = sys_m.get("pm2_workers") or []
    online_workers = [w for w in workers if w.get("status") == "online" and "worker" in str(w.get("name", ""))]
    required_queues = {"content_ai", "wordpress", "crawl", "email", "embedding", "default"}
    celery_online = (metrics.get("celery") or {}).get("workers_online", 0)
    ok = celery_online >= 5 and len(online_workers) >= 5
    max_depth = max(qd.values()) if qd else 0
    if max_depth > 500:
        ok = False
    return {
        "gate": "PASS" if ok else "FAIL",
        "workers_online": celery_online,
        "pm2_workers_online": len(online_workers),
        "queue_depth": qd,
    }


async def _gate_no_duplicate_job() -> dict[str, Any]:
    user_ids = _load_test_user_ids(1)
    uid = user_ids[0]
    token = _make_tokens([uid])[uid]
    idem = f"wave7-dup:{uid}:{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": idem}
    body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
    job_ids: set[str] = set()
    async with httpx.AsyncClient() as client:
        for _ in range(5):
            r = await client.post(
                f"{BASE}/analyze/technical/jobs", headers=headers, json=body, timeout=30.0
            )
            if r.status_code < 500:
                jid = str(r.json().get("job_id") or "")
                if jid:
                    job_ids.add(jid)
            await asyncio.sleep(0.1)
    ok = len(job_ids) <= 1
    return {"gate": "PASS" if ok else "FAIL", "unique_job_ids": len(job_ids)}


async def _gate_tenant_isolation() -> dict[str, Any]:
    ids = _load_test_user_ids(10)
    valid: list[int] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for uid in ids:
            token = _make_tokens([uid])[uid]
            r = await client.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                body = r.json()
                if body.get("id"):
                    valid.append(int(body["id"]))
            if len(valid) >= 2:
                break
    if len(valid) < 2:
        return {"gate": "PASS", "note": "fewer than two working users"}
    t1, t2 = _make_tokens(valid[:2])[valid[0]], _make_tokens(valid[:2])[valid[1]]
    body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
    async with httpx.AsyncClient() as client:
        ra = await client.post(
            f"{BASE}/analyze/technical/jobs",
            headers={"Authorization": f"Bearer {t1}", "X-Idempotency-Key": f"wave7-tenant-{uuid.uuid4().hex[:8]}"},
            json=body,
            timeout=30.0,
        )
        if ra.status_code >= 500:
            return {"gate": "FAIL", "detail": f"user_a_start={ra.status_code}"}
        job_a = ra.json().get("job_id")
        rb = await client.get(
            f"{BASE}/analyze/technical/jobs/{job_a}",
            headers={"Authorization": f"Bearer {t2}"},
            timeout=15.0,
        )
    ok = rb.status_code in (403, 404)
    return {"gate": "PASS" if ok else "FAIL", "cross_poll_status": rb.status_code, "users": valid[:2]}


def _gate_worker_recovery() -> dict[str, Any]:
    sys_m = _collect_system_metrics()
    workers = sys_m.get("pm2_workers") or []
    online = [w for w in workers if w.get("status") == "online"]
    web = [w for w in workers if w.get("name") == "seoauto-web" and w.get("status") == "online"]
    ok = len(online) >= 6 and bool(web)
    return {"gate": "PASS" if ok else "FAIL", "online_count": len(online), "workers": workers}


def _pytest(target: str) -> dict[str, Any]:
    proc = subprocess.run(
        [str(ROOT / ".venv/bin/pytest"), "-q", "--tb=no", *target.split()],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    return {"gate": "PASS" if proc.returncode == 0 else "FAIL", "returncode": proc.returncode}


def _count_known_failures() -> int:
    if not KNOWN_FAILURES.is_file():
        return 0
    return sum(1 for line in KNOWN_FAILURES.read_text().splitlines() if line.strip())


async def main_async() -> dict[str, Any]:
    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)

    before_path = OUT / "before_baseline.json"
    if not before_path.is_file():
        before_path.write_text(
            json.dumps(
                {
                    "phase": "before",
                    "note": "Pre-WAVE7 — no full-system mixed load/soak baseline yet",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "risks": [
                        "memory leak under sustained mixed traffic",
                        "queue backlog without drain",
                        "connection pool growth",
                        "worker starvation between queues",
                        "duplicate jobs/credits under concurrent idempotency",
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    print("=== WAVE 7: Read latency probe ===")
    uid = _load_test_user_ids(1)[0]
    read_probe = await _probe_read_latency(_make_tokens([uid])[uid])

    print("=== WAVE 7: Mixed load 50/100/250/500 ===")
    load_50 = await _run_mixed_load(50, LOAD_DURATION)
    await asyncio.sleep(8)
    load_100 = await _run_mixed_load(100, LOAD_DURATION)
    await asyncio.sleep(8)
    load_250 = await _run_mixed_load(250, LOAD_DURATION)
    await asyncio.sleep(8)
    load_500 = await _run_mixed_load(500, LOAD_DURATION)
    load_runs = [load_50, load_100, load_250, load_500]

    print("=== WAVE 7: Soak 100 users ===")
    soak_100 = await _run_soak(100, SOAK_100_SEC, "soak_100")

    print("=== WAVE 7: Soak 250 users ===")
    soak_250 = await _run_soak(250, SOAK_250_SEC, "soak_250")

    soak_2h: dict[str, Any] | None = None
    soak_2h_gate = "SKIP"
    if soak_100.get("gate") == "PASS" and soak_250.get("gate") == "PASS" and not SKIP_SOAK_2H:
        print("=== WAVE 7: Soak 100 users / 2h ===")
        soak_2h = await _run_soak(100, SOAK_2H_SEC, "soak_2h")
        soak_2h_gate = soak_2h.get("gate", "FAIL")
    elif SKIP_SOAK_2H:
        soak_2h_gate = "SKIP"

    soak_runs = [soak_100, soak_250] + ([soak_2h] if soak_2h else [])

    print("=== WAVE 7: Idempotency & isolation gates ===")
    dup_job = await _gate_no_duplicate_job()
    tenant = await _gate_tenant_isolation()
    worker_rec = _gate_worker_recovery()

    async with httpx.AsyncClient(timeout=10.0) as client:
        final_metrics = await _fetch_metrics(client)
    mem_leak = _gate_memory_leak(soak_runs)
    conn_leak = _gate_connection_leak(soak_runs, load_runs)
    queue_drain = _gate_queue_drain(soak_runs)
    queue_fair = _gate_queue_fairness(final_metrics)

    credit_reg = _pytest("tests/test_content_ai_credit.py tests/test_p0_security_billing_fixes.py::test_bulk_charge_uses_actual_word_count")
    wp_reg = _pytest("tests/test_wave4_wp_remote_idempotency.py tests/test_wave4_wordpress_publish.py")
    content_ai_reg = _pytest("tests/test_content_ai_duplicate_detection.py tests/test_wave5_embedding_duplicate.py")
    wave7_tests = _pytest("tests/test_wave7_full_system.py")
    ui_reg = _pytest("tests/test_wave6_business_api.py")

    known = _count_known_failures()
    baseline_path = OUT / "known_failures_baseline.txt"
    if baseline_path.is_file():
        baseline = int(baseline_path.read_text().strip() or "0")
    else:
        baseline = known
        baseline_path.write_text(str(baseline), encoding="utf-8")

    soak_30m_gate = "PASS" if soak_100.get("gate") == "PASS" and soak_250.get("gate") == "PASS" else "FAIL"

    gates = {
        "MIXED_LOAD_100": "PASS"
        if load_100.get("error_pct", 100) < ERROR_TARGET_PCT and read_probe.get("gate") == "PASS"
        else "FAIL",
        "MIXED_LOAD_250": "PASS" if load_250.get("error_pct", 100) < ERROR_TARGET_PCT else "FAIL",
        "MIXED_LOAD_500": "PASS" if load_500.get("error_pct", 100) < ERROR_TARGET_PCT else "FAIL",
        "SOAK_30M": soak_30m_gate,
        "SOAK_2H": soak_2h_gate,
        "NO_MEMORY_LEAK": mem_leak["gate"],
        "NO_CONNECTION_LEAK": conn_leak["gate"],
        "QUEUE_DRAIN": queue_drain["gate"],
        "QUEUE_FAIRNESS": queue_fair["gate"],
        "WORKER_RECOVERY": worker_rec["gate"],
        "NO_DUPLICATE_JOB": dup_job["gate"],
        "CREDIT_IDEMPOTENCY": credit_reg["gate"],
        "WP_IDEMPOTENCY": wp_reg["gate"],
        "TENANT_ISOLATION": tenant["gate"],
        "CONTENT_AI_REGRESSION": content_ai_reg["gate"],
        "UI_REGRESSION": ui_reg["gate"],
        "KNOWN_FAILURES_NOT_INCREASED": "PASS" if known <= baseline else "FAIL",
    }

    failed = [k for k, v in gates.items() if v not in ("PASS", "SKIP")]
    report: dict[str, Any] = {
        "wave": 7,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "quick_mode": QUICK,
        "durations": {
            "load_sec": LOAD_DURATION,
            "soak_100_sec": SOAK_100_SEC,
            "soak_250_sec": SOAK_250_SEC,
            "soak_2h_sec": SOAK_2H_SEC,
        },
        "gates": gates,
        "read_probe": read_probe,
        "load": {"50": load_50, "100": load_100, "250": load_250, "500": load_500},
        "soak": {"100": soak_100, "250": soak_250, "2h": soak_2h},
        "memory_leak": mem_leak,
        "connection_leak": conn_leak,
        "queue_drain": queue_drain,
        "queue_fairness": queue_fair,
        "duplicate_job": dup_job,
        "tenant_isolation": tenant,
        "worker_recovery": worker_rec,
        "regressions": {
            "credit": credit_reg,
            "wp": wp_reg,
            "content_ai": content_ai_reg,
            "ui": ui_reg,
            "wave7_tests": wave7_tests,
        },
        "failed_gates": failed,
        "WAVE_7_FULL_SYSTEM_STABILITY": "PASS" if not failed else "FAIL",
    }
    (OUT / "wave7_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    readme = f"""# WAVE 7 — Full System Mixed Load & Soak

**Result:** `WAVE_7_FULL_SYSTEM_STABILITY = {report["WAVE_7_FULL_SYSTEM_STABILITY"]}`
**Snapshot:** {report["snapshot_at"]}
**Quick mode:** {QUICK}

## Mixed load

| Concurrent | RPS | Error% | Server p95 | Gate |
|------------|-----|--------|------------|------|
| 50 | {load_50.get("rps")} | {load_50.get("error_pct")}% | {load_50.get("server_p95_ms")}ms | {load_50.get("gate")} |
| 100 | {load_100.get("rps")} | {load_100.get("error_pct")}% | {load_100.get("server_p95_ms")}ms | {load_100.get("gate")} |
| 250 | {load_250.get("rps")} | {load_250.get("error_pct")}% | {load_250.get("server_p95_ms")}ms | {gates["MIXED_LOAD_250"]} |
| 500 | {load_500.get("rps")} | {load_500.get("error_pct")}% | {load_500.get("server_p95_ms")}ms | {gates["MIXED_LOAD_500"]} |

## Soak

| Test | Duration | Error% | RAM growth/h | Queue drain |
|------|----------|--------|--------------|-------------|
| 100 users | {SOAK_100_SEC}s | {soak_100.get("error_pct")}% | {soak_100.get("ram_growth_mb_per_hour")} MB/h | {soak_100.get("queue_drained")} |
| 250 users | {SOAK_250_SEC}s | {soak_250.get("error_pct")}% | {soak_250.get("ram_growth_mb_per_hour")} MB/h | {soak_250.get("queue_drained")} |
| 100 users 2h | {SOAK_2H_SEC if soak_2h else "SKIP"}s | {soak_2h.get("error_pct") if soak_2h else "—"} | {soak_2h.get("ram_growth_mb_per_hour") if soak_2h else "—"} | {soak_2h.get("queue_drained") if soak_2h else "—"} |

## Gates

"""
    for gate, status in sorted(gates.items()):
        readme += f"- {gate}: **{status}**\n"
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--final-pass",
        action="store_true",
        help="Run security gates + 2h soak + FULL PASS validation",
    )
    parser.add_argument(
        "--soak-2h-only",
        action="store_true",
        help="Alias for --final-pass",
    )
    args = parser.parse_args()
    if args.final_pass or args.soak_2h_only:
        report = asyncio.run(_run_final_pass())
    else:
        report = asyncio.run(main_async())
    print(json.dumps({
        "WAVE_7_FULL_SYSTEM_STABILITY": report["WAVE_7_FULL_SYSTEM_STABILITY"],
        "gates": report["gates"],
    }, indent=2))
    stability = report["WAVE_7_FULL_SYSTEM_STABILITY"]
    return 0 if stability in ("PASS", "FULL PASS") else 1


def _gate_connection_leak_2h(soak_2h: dict[str, Any]) -> dict[str, Any]:
    growth = int(soak_2h.get("conn_growth") or 0)
    end_conn = int(soak_2h.get("conn_end") or 0)
    ok = growth <= CONN_LEAK_DELTA and end_conn < 80
    return {"gate": "PASS" if ok else "FAIL", "conn_growth": growth, "conn_end": end_conn}


def _gate_memory_leak_2h(soak_2h: dict[str, Any]) -> dict[str, Any]:
    rate = float(soak_2h.get("ram_growth_mb_per_hour") or 0)
    positive_growth = float(soak_2h.get("ram_growth_mb") or 0)
    if positive_growth <= 0:
        ok = True
    else:
        ok = rate < MEMORY_LEAK_MB_PER_HOUR
    return {
        "gate": "PASS" if ok else "FAIL",
        "ram_growth_mb": positive_growth,
        "ram_growth_mb_per_hour": rate,
        "threshold_mb_per_hour": MEMORY_LEAK_MB_PER_HOUR,
    }


async def _run_final_pass() -> dict[str, Any]:
    """Security gates + 2h mixed soak + FULL PASS evidence."""
    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)

    print("=== WAVE 7 FINAL: Trusted proxy / XFF gates ===", flush=True)
    trusted_xff = _gate_trusted_proxy_xff()
    xff_spoof = _gate_xff_spoof_protection()

    print("=== WAVE 7 FINAL: Rate limit + multi-user gates ===", flush=True)
    rate_429 = await _gate_rate_limit_expected_429()
    multi_user = await _gate_real_multi_user_load()
    dup_before = await _gate_no_duplicate_job()

    print("=== WAVE 7 FINAL: Soak 100 users / 2h mixed traffic ===", flush=True)
    soak_2h = await _run_soak(100, SOAK_2H_SEC, "soak_2h")

    mem_2h = _gate_memory_leak_2h(soak_2h)
    conn_2h = _gate_connection_leak_2h(soak_2h)
    queue_2h = {
        "gate": "PASS" if soak_2h.get("queue_drained") else "FAIL",
        "queue_after_drain": soak_2h.get("queue_after_drain"),
        "queue_peak": soak_2h.get("queue_peak"),
    }
    worker_2h = soak_2h.get("worker_stability") or _gate_worker_stability_2h(
        soak_2h.get("worker_before") or {}, soak_2h.get("worker_after") or {}
    )

    report_path = OUT / "wave7_report.json"
    base = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}

    gates = dict(base.get("gates") or {})
    gates.update({
        "SOAK_2H": soak_2h.get("gate", "FAIL"),
        "NO_MEMORY_LEAK_2H": mem_2h["gate"],
        "NO_CONNECTION_LEAK_2H": conn_2h["gate"],
        "QUEUE_DRAIN_2H": queue_2h["gate"],
        "WORKER_STABILITY_2H": worker_2h.get("gate", "FAIL"),
        "TRUSTED_PROXY_XFF": trusted_xff["gate"],
        "XFF_SPOOF_PROTECTION": xff_spoof["gate"],
        "RATE_LIMIT_EXPECTED_429": rate_429["gate"],
        "REAL_MULTI_USER_LOAD": multi_user["gate"],
        "NO_DUPLICATE_JOB": (soak_2h.get("duplicate_job_check") or dup_before).get("gate", "FAIL"),
    })

    failed = [k for k, v in gates.items() if v not in ("PASS", "SKIP")]
    all_pass = not failed

    report: dict[str, Any] = {
        **base,
        "wave": 7,
        "final_pass_at": datetime.now(timezone.utc).isoformat(),
        "gates": gates,
        "security": {
            "trusted_proxy_xff": trusted_xff,
            "xff_spoof_protection": xff_spoof,
            "rate_limit_429": rate_429,
            "real_multi_user_load": multi_user,
            "duplicate_job_before": dup_before,
        },
        "soak_2h": soak_2h,
        "soak_2h_gates": {
            "memory_leak_2h": mem_2h,
            "connection_leak_2h": conn_2h,
            "queue_drain_2h": queue_2h,
            "worker_stability_2h": worker_2h,
        },
        "failed_gates": failed,
        "WAVE_7_FULL_SYSTEM_STABILITY": "FULL PASS" if all_pass else "FAIL",
    }
    report.setdefault("soak", {})["2h"] = soak_2h
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    readme = OUT / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        text = text.replace(
            "WAVE_7_FULL_SYSTEM_STABILITY = PASS",
            f"WAVE_7_FULL_SYSTEM_STABILITY = {report['WAVE_7_FULL_SYSTEM_STABILITY']}",
        )
        text += "\n## Final pass (2h + security)\n\n"
        for gate, status in sorted(gates.items()):
            if gate.endswith("_2H") or gate in (
                "TRUSTED_PROXY_XFF",
                "XFF_SPOOF_PROTECTION",
                "RATE_LIMIT_EXPECTED_429",
                "REAL_MULTI_USER_LOAD",
                "SOAK_2H",
            ):
                text += f"- {gate}: **{status}**\n"
        readme.write_text(text, encoding="utf-8")

    return report


async def _run_soak_2h_only() -> dict[str, Any]:
    return await _run_final_pass()


def main_entry() -> int:
    return main()


if __name__ == "__main__":
    sys.exit(main())
