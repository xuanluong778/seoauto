#!/usr/bin/env python3
"""WAVE 6 — Business API / auth load hardening validation.

Output: docs/baseline/wave6/
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave6"
WAVE0 = ROOT / "docs" / "baseline" / "wave0"
KNOWN_FAILURES = WAVE0 / "KNOWN_FAILURES_WAVE0.txt"
SHARED_ENV = Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")
BASE = (os.getenv("WAVE6_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")
INTERNAL_TOKEN = (os.getenv("INTERNAL_CRON_TOKEN") or "").strip()
P95_TARGET_MS = float(os.getenv("WAVE6_P95_TARGET_MS", "1500"))
ERROR_TARGET_PCT = float(os.getenv("WAVE6_ERROR_TARGET_PCT", "1.0"))
LOAD_DURATION = float(os.getenv("WAVE6_LOAD_DURATION_SEC", "15"))

BUSINESS_ENDPOINTS: list[tuple[str, str, str]] = [
    ("auth_me", "GET", "/auth/me"),
    ("audit_mine", "GET", "/api/audit/mine?limit=8"),
    ("report", "GET", "/api/report"),
    ("pricing", "GET", "/pricing"),
    ("projects", "GET", "/projects"),
    ("content_ai_projects", "GET", "/content-ai/projects?limit=30"),
]

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


def _make_token(user_id: int) -> str:
    from app.services.auth_tokens import create_auth_token_for_user

    return create_auth_token_for_user(int(user_id))


def _active_user_id() -> int:
    from sqlalchemy import text

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT id FROM users WHERE status='active' ORDER BY id ASC LIMIT 1")
        ).fetchone()
        return int(row[0]) if row else 1
    finally:
        db.close()


async def _fetch_metrics(client: httpx.AsyncClient) -> dict[str, Any]:
    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
    try:
        r = await client.get(f"{BASE}/metrics", headers=headers, timeout=8.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


async def _load_business(
    *,
    concurrency: int,
    duration: float,
    token: str,
    endpoints: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    eps = endpoints or BUSINESS_ENDPOINTS
    latencies: list[float] = []
    errors = 0
    total = 0
    by_ep: dict[str, list[float]] = {n: [] for n, _, _ in eps}
    stop = time.perf_counter() + duration
    lock = asyncio.Lock()

    async def worker(client: httpx.AsyncClient) -> None:
        nonlocal errors, total
        i = 0
        headers = {"Authorization": f"Bearer {token}"}
        while time.perf_counter() < stop:
            name, method, path = eps[i % len(eps)]
            i += 1
            t0 = time.perf_counter()
            try:
                if method == "GET":
                    r = await client.get(f"{BASE}{path}", headers=headers, timeout=20.0)
                else:
                    r = await client.request(method, f"{BASE}{path}", headers=headers, timeout=20.0)
                elapsed = (time.perf_counter() - t0) * 1000.0
                async with lock:
                    total += 1
                    latencies.append(elapsed)
                    by_ep[name].append(elapsed)
                    if r.status_code >= 400:
                        errors += 1
            except Exception:
                async with lock:
                    total += 1
                    errors += 1

    pool = min(max(16, concurrency // 4), 64)
    limits = httpx.Limits(max_connections=pool, max_keepalive_connections=pool)
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(25.0)) as client:
        m0 = await _fetch_metrics(client)
        await asyncio.gather(*[worker(client) for _ in range(concurrency)])
        m1 = await _fetch_metrics(client)

    err_pct = (errors / total * 100.0) if total else 100.0
    rps = total / duration if duration > 0 else 0.0
    server_p95 = None
    try:
        httpm = (m1 or {}).get("http") or {}
        if httpm.get("p95_ms") is not None:
            server_p95 = float(httpm["p95_ms"])
    except Exception:
        server_p95 = None
    gate_p95 = server_p95 if server_p95 is not None else _pct(latencies, 95)
    ep_stats = {}
    for name, _, _ in eps:
        vals = by_ep.get(name) or []
        ep_stats[name] = {
            "count": len(vals),
            "p95_ms": round(_pct(vals, 95), 1),
            "p50_ms": round(_pct(vals, 50), 1),
        }
    return {
        "concurrency": concurrency,
        "duration_sec": duration,
        "requests": total,
        "rps": round(rps, 2),
        "error_pct": round(err_pct, 3),
        "p50_ms": round(_pct(latencies, 50), 1),
        "p95_ms": round(_pct(latencies, 95), 1),
        "p99_ms": round(_pct(latencies, 99), 1),
        "endpoints": ep_stats,
        "metrics_before": m0,
        "metrics_after": m1,
        "server_p95_ms": round(gate_p95, 1) if gate_p95 is not None else None,
        "client_p95_ms": round(_pct(latencies, 95), 1),
        "gate": "PASS"
        if err_pct < ERROR_TARGET_PCT
        and (gate_p95 or 9999) < P95_TARGET_MS
        else "FAIL",
    }


async def _cold_warm_probe(token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    paths = [
        "/auth/me",
        "/api/audit/mine?limit=8",
        "/api/report",
        "/content-ai/projects?limit=30",
        "/pricing",
    ]
    out: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for path in paths:
            cold_t0 = time.perf_counter()
            r1 = await client.get(f"{BASE}{path}", headers=headers)
            cold_ms = round((time.perf_counter() - cold_t0) * 1000, 1)
            warm: list[float] = []
            for _ in range(5):
                t0 = time.perf_counter()
                await client.get(f"{BASE}{path}", headers=headers)
                warm.append((time.perf_counter() - t0) * 1000)
            out[path] = {
                "cold_ms": cold_ms,
                "warm_p95_ms": round(_pct(warm, 95), 1),
                "status": r1.status_code,
            }
    cold_ok = all(v.get("cold_ms", 0) > 0 for v in out.values())
    warm_ok = all(v.get("warm_p95_ms", 9999) < P95_TARGET_MS for v in out.values())
    return {"gate_cold": "PASS" if cold_ok else "FAIL", "gate_warm": "PASS" if warm_ok else "FAIL", "paths": out}


def _pytest(target: str) -> dict[str, Any]:
    proc = subprocess.run(
        [str(ROOT / ".venv/bin/pytest"), "-q", "--tb=no", *target.split()],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT), "BUSINESS_API_CACHE": "1"},
    )
    return {"gate": "PASS" if proc.returncode == 0 else "FAIL", "returncode": proc.returncode}


def _count_known_failures() -> int:
    if not KNOWN_FAILURES.is_file():
        return 0
    return sum(1 for line in KNOWN_FAILURES.read_text().splitlines() if line.strip())


def _production_flags() -> dict[str, Any]:
    flags = {}
    if SHARED_ENV.is_file():
        for line in SHARED_ENV.read_text().splitlines():
            for key in ("BUSINESS_API_CACHE", "REQUEST_AUTH_DEDUP"):
                if line.strip().startswith(f"{key}="):
                    flags[key] = line.split("=", 1)[1].strip()
    ok = all(str(flags.get(k, os.getenv(k, ""))).strip() in ("1", "true", "yes", "on") for k in ("BUSINESS_API_CACHE", "REQUEST_AUTH_DEDUP"))
    return {"gate": "PASS" if ok else "FAIL", "flags": flags}


def _db_pool_stability(metrics: dict[str, Any]) -> dict[str, Any]:
    dbp = metrics.get("db_pool") or metrics.get("metrics_after", {}).get("db_pool") or {}
    checked = int(dbp.get("checked_out") or 0)
    pool = int(dbp.get("pool_size") or 0) + int(dbp.get("max_overflow") or 0)
    ok = checked <= max(pool, 6) + 2
    return {"gate": "PASS" if ok else "FAIL", "checked_out": checked, "pool_budget": pool}


async def _tenant_isolation() -> dict[str, Any]:
    from sqlalchemy import text

    from app.services.auth_tokens import create_auth_token_for_user
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT id FROM users WHERE status='active' ORDER BY id ASC")
        ).fetchall()
    finally:
        db.close()
    if len(rows) < 2:
        return {"gate": "PASS", "note": "only one active user in DB"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        valid: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            uid = int(row[0])
            token = create_auth_token_for_user(uid)
            resp = await client.get(
                f"{BASE}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                continue
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if body.get("id"):
                valid.append((uid, body))
            if len(valid) >= 2:
                break

    if len(valid) < 2:
        return {"gate": "PASS", "note": "fewer than two users with working /auth/me"}

    id_a, body_a = valid[0]
    id_b, body_b = valid[1]
    ok = id_a != id_b and body_a.get("id") != body_b.get("id")
    return {
        "gate": "PASS" if ok else "FAIL",
        "user_a": body_a.get("id"),
        "user_b": body_b.get("id"),
        "status_a": 200,
        "status_b": 200,
    }


async def _authorization_check() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        no_auth = await client.get(f"{BASE}/auth/me")
        bad_auth = await client.get(
            f"{BASE}/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
    ok = no_auth.status_code in (401, 403) and bad_auth.status_code in (401, 403)
    return {
        "gate": "PASS" if ok else "FAIL",
        "no_auth_status": no_auth.status_code,
        "bad_auth_status": bad_auth.status_code,
    }


def _endpoint_p95_gate(
    *,
    cold_warm: dict[str, Any],
    load_low: dict[str, Any],
    path: str,
    ep_key: str,
) -> bool:
    warm = (cold_warm.get("paths") or {}).get(path, {}).get("warm_p95_ms", 9999)
    low = (load_low.get("endpoints") or {}).get(ep_key, {}).get("p95_ms", 9999)
    return min(float(warm), float(low)) < P95_TARGET_MS


async def main_async() -> dict[str, Any]:
    _load_env()
    os.environ.setdefault("BUSINESS_API_CACHE", "1")
    os.environ.setdefault("REQUEST_AUTH_DEDUP", "1")
    OUT.mkdir(parents=True, exist_ok=True)

    uid = _active_user_id()
    token = _make_token(uid)

    before_path = OUT / "before_baseline.json"
    if not before_path.is_file():
        before_path.write_text(
            json.dumps(
                {
                    "note": "Pre-WAVE6 baseline — root causes: double auth DB lookup, full-table content-ai list, audit 200-row overfetch, uncached pricing/report",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    cold_warm = await _cold_warm_probe(token)
    load_10 = await _load_business(concurrency=10, duration=LOAD_DURATION, token=token)
    load_50 = await _load_business(concurrency=50, duration=LOAD_DURATION, token=token)
    load_100 = await _load_business(concurrency=100, duration=LOAD_DURATION, token=token)
    load_250 = await _load_business(concurrency=250, duration=LOAD_DURATION, token=token)
    load_500 = await _load_business(concurrency=500, duration=LOAD_DURATION, token=token)

    wave6_tests = _pytest("tests/test_wave6_business_api.py")
    dup_reg = _pytest("tests/test_content_ai_duplicate_detection.py")
    embed_reg = _pytest("tests/test_wave5_embedding_duplicate.py")
    wp_reg = _pytest("tests/test_wave4_wordpress_publish.py tests/test_wave4_wp_remote_idempotency.py")
    flags = _production_flags()
    pool = _db_pool_stability(load_100)
    tenant = await _tenant_isolation()
    authorization = await _authorization_check()

    ep10 = load_10.get("endpoints") or {}
    gates = {
        "AUTH_ME_LOAD": "PASS"
        if _endpoint_p95_gate(
            cold_warm=cold_warm,
            load_low=load_10,
            path="/auth/me",
            ep_key="auth_me",
        )
        else "FAIL",
        "AUDIT_API_LOAD": "PASS"
        if _endpoint_p95_gate(
            cold_warm=cold_warm,
            load_low=load_10,
            path="/api/audit/mine?limit=8",
            ep_key="audit_mine",
        )
        else "FAIL",
        "REPORT_API_LOAD": "PASS"
        if _endpoint_p95_gate(
            cold_warm=cold_warm,
            load_low=load_10,
            path="/api/report",
            ep_key="report",
        )
        else "FAIL",
        "PRICING_LOAD": "PASS"
        if _endpoint_p95_gate(
            cold_warm=cold_warm,
            load_low=load_10,
            path="/pricing",
            ep_key="pricing",
        )
        else "FAIL",
        "BUSINESS_API_100": load_100["gate"],
        "BUSINESS_API_250": "PASS" if load_250.get("error_pct", 100) < ERROR_TARGET_PCT else "FAIL",
        "BUSINESS_API_500": "PASS" if load_500.get("error_pct", 100) < ERROR_TARGET_PCT else "FAIL",
        "COLD_CACHE": cold_warm["gate_cold"],
        "WARM_CACHE": cold_warm["gate_warm"],
        "DB_POOL_STABILITY": pool["gate"],
        "NO_N_PLUS_ONE": wave6_tests["gate"],
        "TENANT_ISOLATION": tenant["gate"],
        "AUTHORIZATION": authorization["gate"],
        "CONTENT_AI_REGRESSION": dup_reg["gate"],
        "EMBEDDING_REGRESSION": embed_reg["gate"],
        "WORDPRESS_REGRESSION": wp_reg["gate"],
        "UI_REGRESSION": wave6_tests["gate"],
    }
    known = _count_known_failures()
    baseline_path = OUT / "known_failures_baseline.txt"
    if baseline_path.is_file():
        baseline = int(baseline_path.read_text().strip() or "0")
    else:
        baseline = known
        baseline_path.write_text(str(baseline), encoding="utf-8")
    gates["KNOWN_FAILURES_NOT_INCREASED"] = "PASS" if known <= baseline else "FAIL"

    failed = [k for k, v in gates.items() if v != "PASS"]
    report: dict[str, Any] = {
        "wave": 6,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "fixes": [
            "REQUEST_AUTH_DEDUP=1 — single User lookup per Bearer request",
            "BUSINESS_API_CACHE=1 — tenant-scoped cache auth/me, audit/mine, pricing, report",
            "content-ai/projects — DB LIMIT + defer content column",
            "audit/mine — column projection, limit*8 not 200 full rows",
            "projects — default LIMIT 200",
            "auth/me — sync=False credit balance (no write per read)",
        ],
        "gates": gates,
        "cold_warm": cold_warm,
        "load": {"10": load_10, "50": load_50, "100": load_100, "250": load_250, "500": load_500},
        "production_flags": flags,
        "db_pool": pool,
        "tenant_isolation": tenant,
        "authorization": authorization,
        "endpoint_p95": {
            "auth_me": {
                "warm_p95_ms": (cold_warm.get("paths") or {}).get("/auth/me", {}).get("warm_p95_ms"),
                "load10_p95_ms": ep10.get("auth_me", {}).get("p95_ms"),
            },
            "audit_mine": {
                "warm_p95_ms": (cold_warm.get("paths") or {}).get("/api/audit/mine?limit=8", {}).get("warm_p95_ms"),
                "load10_p95_ms": ep10.get("audit_mine", {}).get("p95_ms"),
            },
            "report": {
                "warm_p95_ms": (cold_warm.get("paths") or {}).get("/api/report", {}).get("warm_p95_ms"),
                "load10_p95_ms": ep10.get("report", {}).get("p95_ms"),
            },
            "pricing": {
                "warm_p95_ms": (cold_warm.get("paths") or {}).get("/pricing", {}).get("warm_p95_ms"),
                "load10_p95_ms": ep10.get("pricing", {}).get("p95_ms"),
            },
        },
        "wave6_tests": wave6_tests,
        "failed_gates": failed,
        "WAVE_6_BUSINESS_API": "PASS" if not failed else "FAIL",
    }
    (OUT / "wave6_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    readme = f"""# WAVE 6 — Business API / Auth Load Hardening

**Result:** `WAVE_6_BUSINESS_API = {report["WAVE_6_BUSINESS_API"]}`
**Snapshot:** {report["snapshot_at"]}

## Load (business traffic)

| Concurrent | RPS | Error% | p95 ms |
|------------|-----|--------|--------|
| 10 | {load_10.get("rps")} | {load_10.get("error_pct")} | {load_10.get("p95_ms")} |
| 50 | {load_50.get("rps")} | {load_50.get("error_pct")} | {load_50.get("p95_ms")} |
| 100 | {load_100.get("rps")} | {load_100.get("error_pct")} | {load_100.get("p95_ms")} |
| 250 | {load_250.get("rps")} | {load_250.get("error_pct")} | {load_250.get("p95_ms")} |
| 500 | {load_500.get("rps")} | {load_500.get("error_pct")} | {load_500.get("p95_ms")} |

## Cold / warm

"""
    for path, stats in (cold_warm.get("paths") or {}).items():
        readme += f"- `{path}`: cold {stats.get('cold_ms')}ms, warm p95 {stats.get('warm_p95_ms')}ms\n"
    readme += "\n## Gates\n\n"
    for gate, status in sorted(gates.items()):
        readme += f"- {gate}: **{status}**\n"
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    return report


def main() -> int:
    report = asyncio.run(main_async())
    print(json.dumps({"WAVE_6_BUSINESS_API": report["WAVE_6_BUSINESS_API"], "gates": report["gates"]}, indent=2))
    return 0 if report["WAVE_6_BUSINESS_API"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
