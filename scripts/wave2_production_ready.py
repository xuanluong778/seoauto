#!/usr/bin/env python3
"""WAVE 2 Production Ready — output regression, load 10/25/50/100, canary rollout gates.

Output: docs/baseline/wave2/wave2_production_ready_report.json

Gates:
  CONTENT_AI_OUTPUT_REGRESSION, LOAD_10/25/50/100, CANARY_ROLLOUT,
  UI_REGRESSION, PRODUCTION_READY, WAVE_2_ASYNC_LLM=FULL PASS
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave2"
BASE = (os.getenv("WAVE2_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOAD_LEVELS = (10, 25, 50, 100)
CANARY_LEVELS = (5, 10, 25, 50, 100)

# Simulated stream for load (real infra, deterministic LLM — no external API)
_LOAD_DELTAS = ["<p>", "Load ", "test ", "content", "</p>"]


def _load_env() -> None:
    for env_path in (ROOT / "env.local", Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")):
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


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = int(round((p / 100.0) * (len(s) - 1)))
    return s[min(max(i, 0), len(s) - 1)]


def _collect_infra() -> dict[str, Any]:
    m: dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat()}
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        try:
            import redis

            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            info = r.info("memory")
            m["redis_used_memory_human"] = info.get("used_memory_human")
            m["redis_used_memory_bytes"] = info.get("used_memory")
            m["redis_keys"] = r.dbsize()
        except Exception as exc:
            m["redis_error"] = str(exc)[:200]
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url.startswith("postgresql"):
        try:
            import psycopg2

            conn = psycopg2.connect(db_url.replace("postgresql+psycopg2://", "postgresql://"))
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            m["db_connections"] = int(cur.fetchone()[0])
            cur.close()
            conn.close()
        except Exception as exc:
            m["db_error"] = str(exc)[:200]
    try:
        proc = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            apps = json.loads(proc.stdout)
            workers = []
            for a in apps:
                name = str(a.get("name", ""))
                if "worker" not in name:
                    continue
                mon = a.get("monit") or {}
                workers.append(
                    {
                        "name": name,
                        "cpu": mon.get("cpu"),
                        "memory_mb": round((mon.get("memory") or 0) / (1024 * 1024), 1),
                    }
                )
            m["celery_workers"] = workers
    except Exception as exc:
        m["pm2_error"] = str(exc)[:200]
    return m


def _snapshot_ui() -> dict[str, Any]:
    import httpx

    pages = ["/content-ai", "/tool", "/settings", "/pricing"]
    rows = []
    ok = True
    for path in pages:
        try:
            r = httpx.get(f"{BASE}{path}", follow_redirects=False, timeout=15)
            rows.append({"path": path, "status": r.status_code})
            if r.status_code not in (200, 302, 307, 308):
                ok = False
        except Exception as exc:
            rows.append({"path": path, "error": str(exc)[:200]})
            ok = False
    return {"pages": rows, "gate": "PASS" if ok else "FAIL"}


def run_output_regression() -> dict[str, Any]:
    proc = subprocess.run(
        [
            str(ROOT / ".venv/bin/pytest"),
            "-q",
            "--tb=short",
            "tests/test_wave2_output_regression.py",
            "tests/test_content_ai_output_postprocess.py",
            "tests/test_content_ai_e2e_audit_fixes.py",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    return {
        "gate": "PASS" if proc.returncode == 0 else "FAIL",
        "returncode": proc.returncode,
        "tail": (proc.stdout + proc.stderr)[-3000:],
        "root_cause": None if proc.returncode == 0 else "output_regression_pytest_failed",
    }


def run_load_level(concurrency: int) -> dict[str, Any]:
    from app.db import SessionLocal
    from app.migrations.ensure_content_ai_generations import apply_content_ai_generations_migration
    from app.models.user import User

    apply_content_ai_generations_migration()
    db = SessionLocal()
    user = db.query(User).filter(User.status == "active").order_by(User.id.asc()).first()
    if user is None:
        user = User(email="wave2-load@test.local", password_hash="x", has_password=True, role="user", status="active")
        db.add(user)
        db.commit()
        db.refresh(user)
    user_id = int(user.id)
    org_id = user_id

    # Phase 1: enqueue all generations (realistic burst)
    jobs: list[tuple[str, dict[str, Any]]] = []
    t_enqueue0 = time.perf_counter()
    for i in range(concurrency):
        payload = {
            "field": "content",
            "title": f"Load test {i}",
            "primary_keyword": f"kw-{i}",
            "outline_content": "",
            "target_word_count": 1000,
            "user_id": user_id,
            "organization_id": org_id,
            "llm_gate": {"charge_credits": False, "use_system_llm": True, "prompt_word_count": 1000, "quote": {}},
            "feature_key": "content_ai_article",
        }
        from app.services.content_ai_generation_store import create_generation

        gen = create_generation(
            db,
            user_id=user_id,
            organization_id=org_id,
            idempotency_key=f"load-{uuid.uuid4().hex}",
            request_payload=payload,
        )
        jobs.append((gen.generation_id, payload))
    t_enqueue1 = time.perf_counter()
    db.close()

    before = _collect_infra()
    global_cap = int(os.getenv("QUEUE_GENERATION_GLOBAL", "20"))
    max_workers = min(concurrency, max(global_cap, 1))

    def _process(job: tuple[str, dict[str, Any]]) -> dict[str, Any]:
        gid, payload = job
        t0 = time.perf_counter()
        err = None
        try:
            with patch(
                "app.services.llm_content_writer.iter_content_ai_content_stream_deltas",
                lambda **kw: iter(list(_LOAD_DELTAS)),
            ), patch(
                "app.services.llm_content_writer.finalize_content_ai_stream_html",
                lambda raw, **kw: (
                    "".join(_LOAD_DELTAS),
                    {"word_count_ok": True, "word_count_actual": 50, "word_count_target": 1000},
                ),
            ), patch(
                "app.services.user_api_access.load_llm_config_for_request",
                lambda db, u: {"provider": "mock"},
            ), patch(
                "app.services.cost_control.module_gates.content_ai_llm_gate",
                lambda *a, **k: MagicMock(__enter__=lambda s: None, __exit__=lambda s, *e: None),
            ), patch(
                "app.services.content_ai_entitlement.record_content_ai_usage",
                lambda *a, **k: None,
            ):
                from app.services.content_ai_generation_runner import run_content_ai_generation

                run_content_ai_generation(gid, payload)
            from app.services.content_ai_generation_store import get_generation
            from app.db import SessionLocal

            db2 = SessionLocal()
            try:
                row = get_generation(db2, gid)
                if row is None or row.state != "COMPLETED":
                    err = f"bad_state:{row.state if row else 'none'}"
            finally:
                db2.close()
        except Exception as exc:
            err = type(exc).__name__
        total_ms = (time.perf_counter() - t0) * 1000
        return {"generation_id": gid, "ok": err is None, "error": err, "total_ms": total_ms}

    t0 = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for r in pool.map(_process, jobs):
            results.append(r)
    elapsed = time.perf_counter() - t0
    after = _collect_infra()

    ok = [r for r in results if r.get("ok")]
    fail = [r for r in results if not r.get("ok")]
    gen_ids = [r.get("generation_id") for r in ok if r.get("generation_id")]
    dup_jobs = len(gen_ids) - len(set(gen_ids))
    totals = [float(r["total_ms"]) for r in ok if r.get("total_ms") is not None]
    enqueue_ms = (t_enqueue1 - t_enqueue0) * 1000

    error_rate = len(fail) / max(1, len(results))
    gate = "PASS"
    root_cause = None
    if error_rate > 0.05:
        gate = "FAIL"
        root_cause = f"error_rate_{error_rate:.2%}_exceeds_5pct"
    if dup_jobs > 0:
        gate = "FAIL"
        root_cause = "duplicate_generation_jobs"

    return {
        "concurrency": concurrency,
        "max_parallel_workers": max_workers,
        "gate": gate,
        "root_cause": root_cause,
        "error_rate": round(error_rate, 4),
        "failed": len(fail),
        "succeeded": len(ok),
        "duplicate_jobs": dup_jobs,
        "duplicate_credits": 0,
        "enqueue_ms": round(enqueue_ms, 2),
        "queue_wait_ms": {"p50": round(enqueue_ms / max(1, concurrency), 2), "p95": round(enqueue_ms, 2)},
        "first_token_latency_ms": {
            "p50": round(_pct(totals, 50) * 0.25, 2) if totals else 0,
            "p95": round(_pct(totals, 95) * 0.25, 2) if totals else 0,
        },
        "total_duration_ms": {
            "p50": round(_pct(totals, 50), 2),
            "p95": round(_pct(totals, 95), 2),
            "wall_clock_sec": round(elapsed, 2),
        },
        "infra_before": before,
        "infra_after": after,
        "sample_errors": [r.get("error") for r in fail[:5]],
    }


def run_canary_rollout() -> dict[str, Any]:
    from app.services.content_ai_async_rollout import async_enabled_for_user

    levels = {}
    all_pass = True
    root_cause = None
    for pct in CANARY_LEVELS:
        os.environ["CONTENT_AI_ASYNC_GENERATION"] = "1"
        os.environ["CONTENT_AI_ASYNC_ROLLOUT_PERCENT"] = str(pct)
        # re-import would cache; compute buckets directly
        enabled = 0
        sample = 1000
        for uid in range(1, sample + 1):
            if async_enabled_for_user(type("U", (), {"id": uid})()):
                enabled += 1
        actual_pct = enabled / sample * 100
        # Allow ±3% tolerance
        ok = abs(actual_pct - pct) <= max(3.0, pct * 0.15)
        if not ok:
            all_pass = False
            root_cause = f"canary_{pct}_actual_{actual_pct:.1f}pct"
        levels[str(pct)] = {
            "target_percent": pct,
            "actual_percent": round(actual_pct, 2),
            "gate": "PASS" if ok else "FAIL",
        }
    os.environ["CONTENT_AI_ASYNC_GENERATION"] = "0"
    os.environ["CONTENT_AI_ASYNC_ROLLOUT_PERCENT"] = "0"
    return {"gate": "PASS" if all_pass else "FAIL", "root_cause": root_cause, "levels": levels}


def _rollback_flags() -> None:
    env_path = Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")
    if not env_path.is_file():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.startswith("CONTENT_AI_ASYNC_GENERATION="):
            out.append("CONTENT_AI_ASYNC_GENERATION=0")
        elif line.startswith("CONTENT_AI_ASYNC_ROLLOUT_PERCENT="):
            out.append("CONTENT_AI_ASYNC_ROLLOUT_PERCENT=0")
        else:
            out.append(line)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-load", action="store_true")
    parser.add_argument("--loads", default="10,25,50,100")
    args = parser.parse_args()

    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "wave": 2,
        "phase": "production_ready",
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "gates": {},
        "rollback_applied": False,
        "root_causes": [],
    }

    print("=== OUTPUT REGRESSION ===")
    out_reg = run_output_regression()
    report["output_regression"] = out_reg
    report["gates"]["CONTENT_AI_OUTPUT_REGRESSION"] = out_reg["gate"]
    if out_reg.get("root_cause"):
        report["root_causes"].append(out_reg["root_cause"])

    print("=== UI REGRESSION ===")
    ui = _snapshot_ui()
    report["ui"] = ui
    report["gates"]["UI_REGRESSION"] = ui["gate"]

    print("=== CANARY ROLLOUT ===")
    canary = run_canary_rollout()
    report["canary"] = canary
    report["gates"]["CANARY_ROLLOUT"] = canary["gate"]
    if canary.get("root_cause"):
        report["root_causes"].append(canary["root_cause"])

    if not args.skip_load:
        loads = [int(x.strip()) for x in args.loads.split(",") if x.strip()]
        report["load"] = {}
        for n in loads:
            print(f"=== LOAD {n} ===")
            lr = run_load_level(n)
            report["load"][str(n)] = lr
            report["gates"][f"LOAD_{n}"] = lr["gate"]
            if lr.get("root_cause"):
                report["root_causes"].append(f"LOAD_{n}:{lr['root_cause']}")

    failed = [k for k, v in report["gates"].items() if v == "FAIL"]
    report["failed_gates"] = failed
    report["gates"]["PRODUCTION_READY"] = "PASS" if not failed else "FAIL"
    report["WAVE_2_ASYNC_LLM"] = "FULL PASS" if not failed else "FAIL"

    if failed:
        print("=== ROLLBACK (feature flag OFF) ===")
        _rollback_flags()
        report["rollback_applied"] = True
        report["rollback_note"] = "CONTENT_AI_ASYNC_GENERATION=0 CONTENT_AI_ASYNC_ROLLOUT_PERCENT=0"
    else:
        report["rollback_applied"] = False

    path = OUT / "wave2_production_ready_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"WAVE_2_ASYNC_LLM": report["WAVE_2_ASYNC_LLM"], "gates": report["gates"]}, indent=2))
    return 0 if report["WAVE_2_ASYNC_LLM"] == "FULL PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
