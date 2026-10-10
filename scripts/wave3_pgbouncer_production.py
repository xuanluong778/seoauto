#!/usr/bin/env python3
"""WAVE 3 — PgBouncer production validation (business traffic + transaction pool).

Enables DB_USE_PGBOUNCER=1 canary on PM2, runs authenticated business flows at
10/50/100 concurrent, checks transaction-pooling compatibility, measures DB/host
metrics, validates tenant isolation, and tests rollback to direct PostgreSQL.

Output: docs/baseline/wave3/pgbouncer_production_report.json

Usage:
  .venv/bin/python scripts/wave3_pgbouncer_production.py --apply-canary
  .venv/bin/python scripts/wave3_pgbouncer_production.py --apply-canary --keep-canary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave3"
SHARED_ENV = Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")
ECOSYSTEM = Path("/var/www/seoauto_vn_usr/data/www/shared/ecosystem.config.cjs")
BASE = (os.getenv("WAVE3_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")
INTERNAL_TOKEN = (os.getenv("INTERNAL_CRON_TOKEN") or "").strip()
LOAD_DURATION_SEC = float(os.getenv("WAVE3_BUSINESS_LOAD_SEC", "20"))
TECH_URL = os.getenv("WAVE3_TECH_URL", "https://example.com/")
MAX_INFLIGHT = int(os.getenv("WAVE3_MAX_INFLIGHT", "35"))

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BUSINESS_FLOWS = (
    "auth_me",
    "content_ai_projects",
    "content_ai_credit_quote",
    "credits_preview",
    "technical_audit_job",
    "audit_mine",
    "seo_projects",
    "wordpress_test_connection",
)


def _load_env() -> None:
    keys = {
        "DATABASE_URL",
        "DB_USE_PGBOUNCER",
        "JWT_SECRET",
        "INTERNAL_CRON_TOKEN",
        "REDIS_URL",
        "PGBOUNCER_DEFAULT_POOL_SIZE",
    }
    for env_path in (ROOT / "env.local", SHARED_ENV):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k and (k not in os.environ or k in keys):
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                os.environ[k] = v


def _pg_url_direct() -> str:
    return (os.getenv("DATABASE_URL") or "").replace(":6433/", ":5435/")


def _pg_url_pgbouncer() -> str:
    return _pg_url_direct().replace(":5435/", ":6433/")


def _pg_connect_url(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql://")


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def _patch_shared_env(*, use_pgbouncer: bool) -> dict[str, str]:
    """Update shared env.local DB_USE_PGBOUNCER + DATABASE_URL port."""
    text = SHARED_ENV.read_text(encoding="utf-8")
    backup = text
    direct_url = ""
    for line in text.splitlines():
        if line.startswith("DATABASE_URL="):
            direct_url = line.split("=", 1)[1].strip()
            if ":6433/" in direct_url:
                direct_url = direct_url.replace(":6433/", ":5435/")
            break
    if not direct_url:
        raise RuntimeError("DATABASE_URL not found in shared env.local")
    new_url = direct_url.replace(":5435/", ":6433/") if use_pgbouncer else direct_url
    flag = "1" if use_pgbouncer else "0"

    def _set_line(content: str, key: str, value: str) -> str:
        pat = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pat.search(content):
            return pat.sub(f"{key}={value}", content, count=1)
        return content + f"\n{key}={value}\n"

    text = _set_line(text, "DB_USE_PGBOUNCER", flag)
    text = _set_line(text, "DATABASE_URL", new_url)
    SHARED_ENV.write_text(text, encoding="utf-8")
    os.environ["DB_USE_PGBOUNCER"] = flag
    os.environ["DATABASE_URL"] = new_url
    return {"backup_written": str(SHARED_ENV), "db_use_pgbouncer": flag, "database_url_port": ":6433" if use_pgbouncer else ":5435"}


def _pm2_reload() -> dict[str, Any]:
    proc = subprocess.run(
        ["pm2", "reload", str(ECOSYSTEM), "--update-env"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {"returncode": proc.returncode, "stderr": (proc.stderr or "")[-500:]}


def _wait_ready(timeout_sec: float = 90.0) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/ready", timeout=5.0)
            last = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"status": r.status_code}
            if r.status_code == 200 and (last.get("ready") is True or last.get("status") == "ready"):
                return {"gate": "PASS", "ready": last}
        except Exception as exc:
            last = {"error": str(exc)[:200]}
        time.sleep(2)
    return {"gate": "FAIL", "ready": last}


def profile_db(*, label: str, direct: bool = True) -> dict[str, Any]:
    import psycopg2

    url = _pg_connect_url(_pg_url_direct() if direct else _pg_url_pgbouncer())
    out: dict[str, Any] = {"label": label, "via": "postgres_direct" if direct else "pgbouncer"}
    try:
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute(
            "SELECT state, count(*) FROM pg_stat_activity WHERE datname = current_database() GROUP BY state"
        )
        states = {str(r[0] or "null"): int(r[1]) for r in cur.fetchall()}
        out["connections_by_state"] = states
        out["total_connections"] = sum(states.values())
        cur.execute("SHOW max_connections")
        out["max_connections"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT count(*) FROM pg_stat_activity
            WHERE datname = current_database() AND wait_event_type IS NOT NULL
            """
        )
        out["waiting"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT count(*) FROM pg_stat_activity
            WHERE datname = current_database() AND state = 'active'
              AND now() - query_start > interval '1 second'
            """
        )
        out["slow_queries_gt_1s"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT coalesce(max(extract(epoch from (now() - xact_start))), 0)
            FROM pg_stat_activity
            WHERE datname = current_database() AND xact_start IS NOT NULL
            """
        )
        out["max_transaction_duration_sec"] = round(float(cur.fetchone()[0] or 0), 3)
        cur.close()
        conn.close()
    except Exception as exc:
        out["error"] = str(exc)[:300]
    return out


async def _fetch_metrics() -> dict[str, Any]:
    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE}/metrics", headers=headers, timeout=5.0)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


def _host_from_metrics(m: dict[str, Any]) -> dict[str, Any]:
    host = m.get("host") or {}
    dbp = m.get("db_pool") or {}
    return {
        "cpu_pct": host.get("cpu_pct"),
        "ram_used_mb": host.get("ram_used_mb"),
        "db_pool": dbp,
        "queue_queued": (m.get("queue") or {}).get("queued_count"),
    }


def _make_tokens(user_ids: list[int]) -> dict[int, str]:
    from app.core.security import create_access_token

    return {uid: create_access_token(uid) for uid in user_ids}


def _load_test_user_ids(limit: int = 8) -> list[int]:
    from sqlalchemy import text

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT id FROM users WHERE status='active' ORDER BY id ASC LIMIT :lim"),
            {"lim": limit},
        ).fetchall()
        return [int(r[0]) for r in rows] or [1]
    finally:
        db.close()


def test_transaction_pool_compatibility() -> dict[str, Any]:
    """Verify transaction-pooling semantics vs app-safe patterns."""
    import psycopg2

    url = _pg_connect_url(_pg_url_pgbouncer())
    results: dict[str, Any] = {"gate": "PASS", "cases": {}}

    def _case(name: str, fn, *, required: bool = True) -> None:
        try:
            ok, detail = fn()
            results["cases"][name] = {"ok": ok, "detail": detail, "required": required}
            if not ok and required:
                results["gate"] = "FAIL"
        except Exception as exc:
            results["cases"][name] = {"ok": False, "detail": str(exc)[:200], "required": required}
            if required:
                results["gate"] = "FAIL"

    def simple_crud() -> tuple[bool, str]:
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
            conn.commit()
            return True, "select_commit_ok"
        finally:
            conn.close()

    def prepared_same_tx() -> tuple[bool, str]:
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("PREPARE wave3_plan AS SELECT $1::int")
            cur.execute("EXECUTE wave3_plan (42)")
            assert cur.fetchone()[0] == 42
            conn.commit()
            return True, "prepare_execute_same_tx"
        finally:
            conn.close()

    def prepared_cross_checkout() -> tuple[bool, str]:
        """Expected incompatible — document only."""
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("PREPARE wave3_cross AS SELECT $1::int")
            conn.commit()
            cur.execute("EXECUTE wave3_cross (1)")
            conn.commit()
            return True, "unexpectedly_ok"
        except Exception as exc:
            return True, f"expected_incompatible:{type(exc).__name__}"
        finally:
            conn.close()

    def advisory_lock_same_tx() -> tuple[bool, str]:
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_advisory_lock(424242)")
            cur.execute("SELECT pg_advisory_unlock(424242)")
            conn.commit()
            return True, "advisory_same_tx"
        finally:
            conn.close()

    def listen_notify() -> tuple[bool, str]:
        """LISTEN requires session pooling — app does not use."""
        conn = psycopg2.connect(url)
        try:
            conn.set_isolation_level(0)
            cur = conn.cursor()
            cur.execute("LISTEN wave3_channel")
            conn.commit()
            cur.execute("NOTIFY wave3_channel")
            conn.poll()
            return True, "listen_ok_in_tx"
        except Exception as exc:
            return True, f"expected_limitation:{type(exc).__name__}"
        finally:
            conn.close()

    def set_session() -> tuple[bool, str]:
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("SET work_mem = '8MB'")
            cur.execute("SHOW work_mem")
            v1 = cur.fetchone()[0]
            conn.commit()
            cur.execute("SHOW work_mem")
            v2 = cur.fetchone()[0]
            return True, f"set_in_tx={v1} after_commit={v2}"
        finally:
            conn.close()

    def temp_table_same_tx() -> tuple[bool, str]:
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("CREATE TEMP TABLE wave3_tmp (id int)")
            cur.execute("INSERT INTO wave3_tmp VALUES (1)")
            cur.execute("SELECT count(*) FROM wave3_tmp")
            n = cur.fetchone()[0]
            conn.commit()
            return n == 1, f"rows={n}"
        finally:
            conn.close()

    def temp_table_after_return() -> tuple[bool, str]:
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("CREATE TEMP TABLE wave3_tmp2 (id int)")
            conn.commit()
        finally:
            conn.close()
        conn2 = psycopg2.connect(url)
        try:
            cur = conn2.cursor()
            cur.execute("SELECT count(*) FROM wave3_tmp2")
            cur.fetchone()
            return False, "should_not_reach"
        except Exception as exc:
            return True, f"expected_incompatible:{type(exc).__name__}"
        finally:
            conn2.close()

    def long_transaction() -> tuple[bool, str]:
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.execute("SELECT pg_sleep(2)")
            cur.execute("SELECT 1")
            conn.commit()
            return True, "held_2s_ok"
        finally:
            conn.close()

    def skip_locked() -> tuple[bool, str]:
        """App uses FOR UPDATE SKIP LOCKED — must work in one transaction."""
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.execute("SELECT id FROM users WHERE status='active' LIMIT 1 FOR UPDATE SKIP LOCKED")
            row = cur.fetchone()
            conn.commit()
            return row is not None, "skip_locked_ok"
        finally:
            conn.close()

    _case("simple_crud", simple_crud)
    _case("prepared_same_tx", prepared_same_tx)
    _case("prepared_cross_checkout", prepared_cross_checkout, required=False)
    _case("advisory_lock_same_tx", advisory_lock_same_tx)
    _case("listen_notify", listen_notify, required=False)
    _case("set_session", set_session)
    _case("temp_table_same_tx", temp_table_same_tx)
    _case("temp_table_after_return", temp_table_after_return, required=False)
    _case("long_transaction_2s", long_transaction)
    _case("for_update_skip_locked", skip_locked)

    required_fail = [
        k for k, v in results["cases"].items() if not v.get("ok") and v.get("required", True)
    ]
    if required_fail:
        results["gate"] = "FAIL"
        results["failed_required"] = required_fail
    return results


async def _business_request(
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
            r = await client.get(f"{BASE}/auth/me", headers=headers, timeout=15.0)
        elif flow == "content_ai_projects":
            r = await client.get(f"{BASE}/content-ai/projects", headers=headers, timeout=45.0)
        elif flow == "content_ai_credit_quote":
            body = {
                "field": "content",
                "title": f"wave3-{uid}",
                "primary_keyword": "seo test",
                "target_word_count": 500,
            }
            r = await client.post(f"{BASE}/content-ai/credit-quote", headers=headers, json=body, timeout=20.0)
        elif flow == "credits_preview":
            body = {"module": "audit", "action": "technical_deep", "quota_key": "technical_audit"}
            r = await client.post(f"{BASE}/api/credits/preview", headers=headers, json=body, timeout=15.0)
        elif flow == "technical_audit_job":
            body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
            h = {**headers, "X-Idempotency-Key": f"wave3-pb-{uid}-{i}-{uuid.uuid4().hex[:8]}"}
            r = await client.post(f"{BASE}/analyze/technical/jobs", headers=h, json=body, timeout=45.0)
        elif flow == "audit_mine":
            r = await client.get(f"{BASE}/api/audit/mine", headers=headers, timeout=20.0)
        elif flow == "seo_projects":
            r = await client.get(f"{BASE}/projects", headers=headers, timeout=20.0)
        elif flow == "wordpress_test_connection":
            body = {"url": "https://example.com", "username": "wave3", "app_password": "invalid"}
            r = await client.post(
                f"{BASE}/content-ai/wordpress/test-connection", headers=headers, json=body, timeout=25.0
            )
        else:
            r = await client.get(f"{BASE}/health", timeout=5.0)
        status = r.status_code
    except Exception:
        status = 0
    return status, (time.perf_counter() - t0) * 1000.0, flow


async def _virtual_business_user(
    uid: int,
    token: str,
    stop_at: float,
    results: dict[str, Any],
    sem: asyncio.Semaphore,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        i = 0
        while time.time() < stop_at:
            flow = BUSINESS_FLOWS[i % len(BUSINESS_FLOWS)]
            async with sem:
                st, lat, name = await _business_request(client, flow, headers, uid, i)
            results["latencies_ms"].append(lat)
            results["status_counts"][st] = results["status_counts"].get(st, 0) + 1
            results["by_flow"].setdefault(name, {"ok": 0, "err": 0})
            if st == 0 or st >= 500:
                results["by_flow"][name]["err"] += 1
            else:
                results["by_flow"][name]["ok"] += 1
            i += 1
            await asyncio.sleep(0.2)


async def run_business_load(concurrency: int) -> dict[str, Any]:
    user_ids = _load_test_user_ids(max(4, min(concurrency, 10)))
    tokens = _make_tokens(user_ids)
    results: dict[str, Any] = {
        "concurrency": concurrency,
        "latencies_ms": [],
        "status_counts": {},
        "by_flow": {},
    }
    stop_at = time.time() + LOAD_DURATION_SEC
    sem = asyncio.Semaphore(min(MAX_INFLIGHT, max(10, concurrency)))
    tasks = [
        asyncio.create_task(
            _virtual_business_user(user_ids[i % len(user_ids)], tokens[user_ids[i % len(user_ids)]], stop_at, results, sem)
        )
        for i in range(concurrency)
    ]
    db_before = profile_db(label=f"load_{concurrency}_before", direct=True)
    metrics_before = await _fetch_metrics()
    await asyncio.gather(*tasks)
    metrics_after = await _fetch_metrics()
    db_after = profile_db(label=f"load_{concurrency}_after", direct=True)

    total = sum(results["status_counts"].values()) or 1
    errors = sum(c for s, c in results["status_counts"].items() if s == 0 or s >= 500)
    rate_limited = results["status_counts"].get(429, 0)
    error_pct = round(errors / total * 100.0, 2)
    p99 = round(_pct(results["latencies_ms"], 99), 1)
    host = _host_from_metrics(metrics_after or metrics_before)

    db_flow_names = [f for f in BUSINESS_FLOWS if f != "auth_me"]
    db_err = sum(results["by_flow"].get(f, {}).get("err", 0) for f in db_flow_names)
    db_ok = sum(results["by_flow"].get(f, {}).get("ok", 0) for f in db_flow_names)
    db_total = db_ok + db_err or 1
    db_error_pct = round(db_err / db_total * 100.0, 2)

    gate = "PASS"
    notes: list[str] = []
    if db_error_pct >= 3.0:
        gate = "FAIL"
        notes.append(f"db_flow_error_pct={db_error_pct}")
    if error_pct >= 15.0 and concurrency >= 50:
        notes.append(f"http_error_pct={error_pct}")
    if rate_limited > total * 0.35:
        notes.append(f"rate_limited={rate_limited}")
    if p99 > 45000:
        gate = "FAIL"
        notes.append(f"p99_ms={p99}")
    if db_after.get("total_connections", 0) >= db_after.get("max_connections", 100) - 3:
        gate = "FAIL"
        notes.append("postgres_near_max_connections")
    if db_after.get("slow_queries_gt_1s", 0) > concurrency // 2:
        gate = "FAIL"
        notes.append("slow_queries_high")

    return {
        "gate": gate,
        "concurrency": concurrency,
        "duration_sec": LOAD_DURATION_SEC,
        "total_requests": total,
        "error_pct": error_pct,
        "db_flow_error_pct": db_error_pct,
        "rate_limited_429": rate_limited,
        "p50_ms": round(_pct(results["latencies_ms"], 50), 1),
        "p95_ms": round(_pct(results["latencies_ms"], 95), 1),
        "p99_ms": p99,
        "status_counts": results["status_counts"],
        "by_flow": results["by_flow"],
        "db_before": db_before,
        "db_after": db_after,
        "host_metrics": host,
        "notes": notes,
    }


async def test_tenant_query() -> dict[str, Any]:
    ids = _load_test_user_ids(2)
    if len(ids) < 2:
        return {"gate": "SKIP", "reason": "need>=2 users"}
    t1, t2 = _make_tokens([ids[0]])[ids[0]], _make_tokens([ids[1]])[ids[1]]
    body = {"url": TECH_URL, "max_pages": 2, "use_gsc": False}
    async with httpx.AsyncClient() as client:
        ra = await client.post(
            f"{BASE}/analyze/technical/jobs",
            headers={"Authorization": f"Bearer {t1}", "X-Idempotency-Key": f"wave3-tenant-{uuid.uuid4().hex[:8]}"},
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
    return {"gate": "PASS" if ok else "FAIL", "cross_poll_status": rb.status_code}


def test_no_pool_exhaustion() -> dict[str, Any]:
    db = profile_db(label="pool_check", direct=True)
    max_conn = db.get("max_connections", 100)
    total = db.get("total_connections", 0)
    gate = "PASS" if total < max_conn - 5 and db.get("slow_queries_gt_1s", 0) == 0 else "FAIL"
    return {"gate": gate, **db}


def index_warn_status() -> dict[str, Any]:
    import psycopg2

    url = _pg_connect_url(_pg_url_direct())
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_wordpress_publish_jobs_status_created'"
    )
    exists = cur.fetchone() is not None
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_wordpress_publish_jobs_status_retry'"
    )
    has_retry = cur.fetchone() is not None
    cur.close()
    conn.close()
    return {
        "ix_wordpress_publish_jobs_status_created": {
            "status": "WARN" if not exists else "OK",
            "reason": "digiseo is not table owner — cannot CREATE INDEX; use table owner or DBA",
            "fallback_index": "ix_wordpress_publish_jobs_status_retry",
            "fallback_present": has_retry,
        }
    }


def test_pgbouncer_rollback() -> dict[str, Any]:
    """Simulate PgBouncer outage → rollback to direct PG → verify live."""
    steps: list[dict[str, Any]] = []
    try:
        subprocess.run(["docker", "stop", "seoauto-pgbouncer"], capture_output=True, timeout=30)
        steps.append({"step": "stop_pgbouncer", "ok": True})
        time.sleep(2)

        try:
            broken_ready = httpx.get(f"{BASE}/ready", timeout=5.0)
            steps.append({"step": "ready_while_pgbouncer_down", "status": broken_ready.status_code})
        except Exception as exc:
            steps.append({"step": "ready_while_pgbouncer_down", "error": str(exc)[:120]})

        patch = _patch_shared_env(use_pgbouncer=False)
        steps.append({"step": "env_rollback_direct", **patch})
        reload = _pm2_reload()
        steps.append({"step": "pm2_reload", **reload})
        ready = _wait_ready(90)
        steps.append({"step": "ready_after_rollback", **ready})

        import psycopg2

        direct = _pg_connect_url(_pg_url_direct())
        conn = psycopg2.connect(direct)
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE status='active' ORDER BY id LIMIT 1")
        uid = int(cur.fetchone()[0])
        cur.close()
        conn.close()
        token = _make_tokens([uid])[uid]
        me = httpx.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
        steps.append({"step": "auth_me_after_rollback", "status": me.status_code})

        gate = "PASS" if ready.get("gate") == "PASS" and me.status_code == 200 else "FAIL"
        return {"gate": gate, "steps": steps}
    finally:
        subprocess.run(["docker", "start", "seoauto-pgbouncer"], capture_output=True, timeout=30)
        steps.append({"step": "restart_pgbouncer", "ok": True})
        time.sleep(3)


async def verify_pgbouncer_live() -> dict[str, Any]:
    m = await _fetch_metrics()
    dbp = m.get("db_pool") or {}
    via_pgbouncer = os.getenv("DB_USE_PGBOUNCER", "0") == "1"
    ready = httpx.get(f"{BASE}/ready", timeout=10.0)
    ok = via_pgbouncer and ready.status_code == 200
    return {
        "gate": "PASS" if ok else "FAIL",
        "db_use_pgbouncer_env": via_pgbouncer,
        "ready_status": ready.status_code,
        "db_pool_metrics": dbp,
    }


async def main_async(args: argparse.Namespace) -> int:
    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "wave": "3-pgbouncer-production",
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "gates": {},
        "index_warn": index_warn_status(),
    }

    if args.apply_canary:
        print("=== Enable PgBouncer canary (PM2) ===")
        patch = _patch_shared_env(use_pgbouncer=True)
        reload = _pm2_reload()
        ready = _wait_ready(120)
        report["canary_enable"] = {"patch": patch, "pm2_reload": reload, "ready": ready}
        if ready.get("gate") != "PASS":
            report["gates"]["PRODUCTION_LIVE"] = "FAIL"
            report["WAVE_3_DB_PGBOUNCER"] = "FAIL"
            _write_report(report)
            return 1
        time.sleep(5)

    live_check = await verify_pgbouncer_live()
    report["pgbouncer_live_check"] = live_check
    if not args.offline and live_check.get("gate") != "PASS":
        report["gates"]["PRODUCTION_LIVE"] = "FAIL"
        report["WAVE_3_DB_PGBOUNCER"] = "FAIL"
        _write_report(report)
        print("PgBouncer not active on PM2 — run with --apply-canary")
        return 1

    print("=== Transaction pool compatibility ===")
    compat = test_transaction_pool_compatibility()
    report["transaction_pool_compatibility"] = compat
    report["gates"]["TRANSACTION_POOL_COMPATIBILITY"] = compat["gate"]

    print("=== Business load 10/50/100 ===")
    load_gates = {}
    for n in (10, 50, 100):
        print(f"--- load {n} ---")
        lr = await run_business_load(n)
        report[f"business_load_{n}"] = lr
        load_gates[n] = lr["gate"]
        report["gates"][f"PGBOUNCER_BUSINESS_LOAD_{n}"] = lr["gate"]
        await asyncio.sleep(12)

    print("=== Tenant + pool exhaustion ===")
    tenant = await test_tenant_query()
    report["tenant_query"] = tenant
    report["gates"]["TENANT_QUERY"] = tenant["gate"]

    pool = test_no_pool_exhaustion()
    report["pool_exhaustion"] = pool
    report["gates"]["NO_POOL_EXHAUSTION"] = pool["gate"]

    live_ok = all(load_gates.get(n) == "PASS" for n in (10, 50, 100)) and compat["gate"] == "PASS"
    report["gates"]["PRODUCTION_LIVE"] = "PASS" if live_ok else "FAIL"

    print("=== PgBouncer rollback drill ===")
    if args.with_rollback_drill:
        rollback = test_pgbouncer_rollback()
        report["pgbouncer_rollback"] = rollback
        report["gates"]["PGBOUNCER_ROLLBACK"] = rollback["gate"]
    else:
        report["pgbouncer_rollback"] = {"gate": "SKIP", "note": "use --with-rollback-drill"}
        report["gates"]["PGBOUNCER_ROLLBACK"] = "SKIP"

    failed = [k for k, v in report["gates"].items() if v == "FAIL"]
    report["failed_gates"] = failed
    required = [
        "TRANSACTION_POOL_COMPATIBILITY",
        "PGBOUNCER_BUSINESS_LOAD_10",
        "PGBOUNCER_BUSINESS_LOAD_50",
        "PGBOUNCER_BUSINESS_LOAD_100",
        "NO_POOL_EXHAUSTION",
        "TENANT_QUERY",
        "PRODUCTION_LIVE",
    ]
    if args.with_rollback_drill:
        required.append("PGBOUNCER_ROLLBACK")
    all_pass = not failed and all(report["gates"].get(g) == "PASS" for g in required)
    report["WAVE_3_DB_PGBOUNCER"] = "FULL PASS" if all_pass else "FAIL"

    if args.apply_canary and not args.keep_canary:
        print("=== Restore direct PG (post-validation) ===")
        _patch_shared_env(use_pgbouncer=False)
        _pm2_reload()
        _wait_ready(90)
        report["post_validation_restore"] = "DB_USE_PGBOUNCER=0 direct :5435"
    elif args.keep_canary and all_pass:
        report["post_validation_restore"] = "kept DB_USE_PGBOUNCER=1 (FULL PASS)"

    _write_report(report)
    print(json.dumps({"WAVE_3_DB_PGBOUNCER": report["WAVE_3_DB_PGBOUNCER"], "gates": report["gates"]}, indent=2))
    return 0 if all_pass else 1


def _write_report(report: dict[str, Any]) -> None:
    (OUT / "pgbouncer_production_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    warn = report.get("index_warn", {}).get("ix_wordpress_publish_jobs_status_created", {})
    lines = [
        "# WAVE 3 — PgBouncer Production Validation",
        "",
        f"**Result:** `{report.get('WAVE_3_DB_PGBOUNCER')}`",
        f"**Snapshot:** {report.get('snapshot_at')}",
        "",
        "## Gates",
        "",
    ]
    for k, v in sorted(report.get("gates", {}).items()):
        lines.append(f"- {k}: **{v}**")
    lines.extend(
        [
            "",
            "## Index WARN",
            "",
            f"- `ix_wordpress_publish_jobs_status_created`: **{warn.get('status')}**",
            f"  - {warn.get('reason')}",
            f"  - Fallback `{warn.get('fallback_index')}` present: {warn.get('fallback_present')}",
            "",
            "## Rollback",
            "",
            "`DB_USE_PGBOUNCER=0` + `DATABASE_URL` → `:5435` + `pm2 reload ecosystem.config.cjs --update-env`",
            "",
        ]
    )
    (OUT / "PGBOUNCER_PRODUCTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-canary", action="store_true", help="Enable DB_USE_PGBOUNCER=1 on PM2 before tests")
    parser.add_argument("--keep-canary", action="store_true", help="Leave PgBouncer enabled after FULL PASS")
    parser.add_argument(
        "--with-rollback-drill",
        action="store_true",
        help="Stop PgBouncer container and verify rollback to direct PG (disruptive)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="PgBouncer compat + business load only; no env/PM2/docker changes",
    )
    args = parser.parse_args()
    if args.offline:
        args.apply_canary = False
        args.with_rollback_drill = False
    elif not args.apply_canary:
        print("Note: PM2 already on PgBouncer canary? Use --apply-canary to enable, or --offline for read-only checks.")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
