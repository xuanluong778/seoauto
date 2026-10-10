#!/usr/bin/env python3
"""WAVE 1 — Celery scale validation: queues, prefork, claim concurrency, regressions.

Output: docs/baseline/wave1/
Gates: CELERY_QUEUE, CELERY_PREFORK, JOB_CLAIM_CONCURRENCY, NO_DUPLICATE_JOB,
       QUEUE_RECOVERY, CREDIT_IDEMPOTENCY, CONTENT_AI_BULK_REGRESSION,
       WP_PUBLISH_REGRESSION, UI_REGRESSION, KNOWN_FAILURES_NOT_INCREASED

Usage:
  .venv/bin/python scripts/wave1_celery_scale.py
  .venv/bin/python scripts/wave1_celery_scale.py --scale-level 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave1"
WAVE0 = ROOT / "docs" / "baseline" / "wave0"
KNOWN_FAILURES = WAVE0 / "KNOWN_FAILURES_WAVE0.txt"
BASE = (os.getenv("WAVE1_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTENT_AI_REGRESSION = [
    "tests/test_content_ai_e2e_audit_fixes.py",
    "tests/test_content_ai_duplicate_detection.py",
    "tests/test_content_ai_credit.py",
    "tests/test_content_ai_bulk_progress.py",
    "tests/test_content_ai_output_postprocess.py",
    "tests/test_content_ai_publish_schedule.py",
    "tests/test_bulk_celery_no_inline_dup.py",
]

WP_REGRESSION = [
    "tests/test_wp_publish_draft.py",
    "tests/test_content_ai_publish_schedule.py",
]

CREDIT_REGRESSION = [
    "tests/test_content_ai_credit.py",
    "tests/test_p0_security_billing_fixes.py::test_bulk_charge_uses_actual_word_count",
]

WAVE1_TESTS = [
    "tests/test_wave1_celery_queues.py",
    "tests/test_wave1_job_claim_concurrency_pg.py",
    "tests/test_job_store_fingerprint.py::test_claim_job_by_id_and_skips_running",
    "tests/test_bulk_celery_no_inline_dup.py",
]

UI_PAGES = [
    "/content-ai",
    "/tool",
    "/chatbot-cskh",
    "/settings",
    "/pricing",
]


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


def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )


def _pytest(target: str, junit_name: str) -> dict[str, Any]:
    junit = OUT / junit_name
    proc = _run(
        [
            str(ROOT / ".venv/bin/pytest"),
            "-q",
            "--tb=no",
            f"--junitxml={junit}",
            *target.split(),
        ],
        timeout=900,
    )
    m = re.search(r"(\d+) passed.*?(\d+) failed", proc.stdout + proc.stderr)
    passed = int(m.group(1)) if m else 0
    failed = int(m.group(2)) if m else 0
    return {
        "target": target,
        "returncode": proc.returncode,
        "passed": passed,
        "failed": failed,
        "gate": "PASS" if proc.returncode == 0 else "FAIL",
        "junit": str(junit.relative_to(ROOT)),
    }


def _parse_junit_failures(junit_path: Path) -> set[str]:
    if not junit_path.is_file():
        return set()
    import xml.etree.ElementTree as ET

    root = ET.parse(junit_path).getroot()
    out: set[str] = set()
    for tc in root.iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            cls = tc.get("classname", "")
            name = tc.get("name", "")
            if cls:
                # Normalize to pytest node id when classname is file path
                if cls.startswith("tests."):
                    out.add(f"{cls.replace('.', '/')}.py::{name}")
                elif cls.startswith("tests/"):
                    out.add(f"{cls}::{name}")
                else:
                    out.add(f"{cls}::{name}")
            else:
                out.add(name)
    return out


def _normalize_failure_id(node_id: str) -> str:
    s = str(node_id or "").strip()
    if "::" in s:
        return s
    return s


def _snapshot_ui() -> dict[str, Any]:
    import httpx

    rows = []
    ok = True
    for path in UI_PAGES:
        url = f"{BASE}{path}"
        try:
            r = httpx.get(url, follow_redirects=False, timeout=15)
            rows.append({"path": path, "status": r.status_code})
            if r.status_code not in (200, 302, 307, 308):
                ok = False
        except Exception as exc:
            rows.append({"path": path, "error": str(exc)[:200]})
            ok = False
    return {"pages": rows, "gate": "PASS" if ok else "FAIL"}


def _collect_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat()}
    try:
        import psutil

        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        metrics["ram_used_mb"] = round(mem.used / (1024 * 1024))
        metrics["ram_available_mb"] = round(mem.available / (1024 * 1024))
    except Exception as exc:
        metrics["psutil_error"] = str(exc)[:200]

    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        try:
            import redis

            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            metrics["redis_db_keys"] = r.dbsize()
            queue_depth: dict[str, int] = {}
            for q in ("content_ai", "wordpress", "crawl", "email", "default", "celery"):
                try:
                    queue_depth[q] = int(r.llen(q))
                except Exception:
                    queue_depth[q] = -1
            metrics["queue_depth"] = queue_depth
        except Exception as exc:
            metrics["redis_error"] = str(exc)[:200]

    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url.startswith("postgresql"):
        try:
            import psycopg2

            conn = psycopg2.connect(db_url.replace("postgresql+psycopg2://", "postgresql://"))
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            metrics["db_connections"] = int(cur.fetchone()[0])
            cur.close()
            conn.close()
        except Exception as exc:
            metrics["db_error"] = str(exc)[:200]

    try:
        proc = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            apps = json.loads(proc.stdout)
            workers = []
            for a in apps:
                name = str(a.get("name", ""))
                if "worker" not in name:
                    continue
                env_pm2 = (a.get("pm2_env") or {})
                args = _pm2_worker_args(env_pm2)
                workers.append(
                    {
                        "name": name,
                        "status": env_pm2.get("status"),
                        "cpu": (a.get("monit") or {}).get("cpu"),
                        "memory": (a.get("monit") or {}).get("memory"),
                        "prefork": "-P prefork" in args or "prefork" in args,
                        "solo": "-P solo" in args or " solo " in f" {args} ",
                        "queues": _queues_from_pm2_args(args),
                        "concurrency": (m.group(1) if (m := re.search(r"--concurrency=(\d+)", args)) else None),
                    }
                )
            metrics["celery_workers"] = workers
    except Exception as exc:
        metrics["pm2_error"] = str(exc)[:200]

    return metrics


def _pm2_worker_args(env_pm2: dict[str, Any]) -> str:
    raw = env_pm2.get("args") or ""
    if isinstance(raw, list):
        return " ".join(str(x) for x in raw)
    return str(raw)


def _queues_from_pm2_args(args: str) -> list[str]:
    if not args:
        return []
    # PM2 may store "-Q queue" as separate tokens in a joined string
    parts = args.split()
    queues: list[str] = []
    for i, tok in enumerate(parts):
        if tok == "-Q" and i + 1 < len(parts):
            queues.append(parts[i + 1])
    if queues:
        return queues
    return re.findall(r"-Q\s+(\S+)", args)


def _gate_celery_queue(metrics: dict[str, Any]) -> str:
    if os.getenv("CELERY_MULTI_QUEUE", "0") != "1":
        return "SKIP"
    workers = metrics.get("celery_workers") or []
    if not workers:
        return "FAIL"
    queues = set()
    name_to_queue = {
        "seoauto-worker-content-ai": "content_ai",
        "seoauto-worker-wordpress": "wordpress",
        "seoauto-worker-crawl": "crawl",
        "seoauto-worker-email": "email",
        "seoauto-worker-default": "default",
    }
    for w in workers:
        for q in w.get("queues") or []:
            queues.add(q)
        pm2_name = str(w.get("name") or "")
        if pm2_name in name_to_queue:
            queues.add(name_to_queue[pm2_name])
    required = {"content_ai", "wordpress", "crawl", "email", "default"}
    return "PASS" if required.issubset(queues) else "FAIL"


def _gate_prefork(metrics: dict[str, Any]) -> str:
    if os.getenv("CELERY_MULTI_QUEUE", "0") != "1":
        return "SKIP"
    workers = metrics.get("celery_workers") or []
    if not workers:
        return "FAIL"
    for w in workers:
        if w.get("solo"):
            return "FAIL"
        if not w.get("prefork"):
            return "FAIL"
    return "PASS"


def _check_backup() -> dict[str, Any]:
    backup_script = ROOT / "scripts" / "backup" / "backup_seoauto.sh"
    backup_dirs = list(Path("/var/www/seoauto_vn_usr/data/backups").glob("*")) if Path(
        "/var/www/seoauto_vn_usr/data/backups"
    ).is_dir() else []
    return {
        "script_exists": backup_script.is_file(),
        "recent_backups": len(backup_dirs),
        "gate": "PASS" if backup_script.is_file() else "FAIL",
    }


def _compare_known_failures(current: set[str]) -> dict[str, Any]:
    baseline: set[str] = set()
    if KNOWN_FAILURES.is_file():
        baseline = {ln.strip() for ln in KNOWN_FAILURES.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}
    new_failures = sorted(current - baseline)
    return {
        "baseline_count": len(baseline),
        "current_count": len(current),
        "new_failures": new_failures[:50],
        "new_failure_count": len(new_failures),
        "gate": "PASS" if len(new_failures) == 0 else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale-level", type=int, default=1, choices=[1, 2, 4])
    args = parser.parse_args()

    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "wave": 1,
        "scale_level": args.scale_level,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "gates": {},
        "metrics": {},
    }

    print("=== WAVE 1: Backup check ===")
    report["backup"] = _check_backup()
    report["gates"]["BACKUP_READY"] = report["backup"]["gate"]

    print("=== WAVE 1: Celery queue config ===")
    from app.queue import celery_queues

    report["celery_multi_queue"] = celery_queues.celery_multi_queue_enabled()
    report["task_routes_count"] = len(celery_queues.TASK_ROUTES)
    report["gates"]["CELERY_QUEUE"] = "PASS" if report["celery_multi_queue"] else "SKIP"

    print("=== WAVE 1: Infra metrics ===")
    metrics = _collect_metrics()
    report["metrics"]["before"] = metrics
    report["gates"]["CELERY_PREFORK"] = _gate_prefork(metrics)
    if report["gates"]["CELERY_QUEUE"] != "SKIP":
        report["gates"]["CELERY_QUEUE"] = _gate_celery_queue(metrics)

    print("=== WAVE 1: UI baseline (subset) ===")
    ui = _snapshot_ui()
    report["ui_baseline"] = ui
    report["gates"]["UI_REGRESSION"] = ui["gate"]

    print("=== WAVE 1: Wave1 + claim concurrency tests ===")
    w1 = _pytest(" ".join(WAVE1_TESTS), "junit_wave1_core.xml")
    report["tests_wave1_core"] = w1
    report["gates"]["JOB_CLAIM_CONCURRENCY"] = "PASS" if w1["gate"] == "PASS" else "FAIL"
    report["gates"]["NO_DUPLICATE_JOB"] = report["gates"]["JOB_CLAIM_CONCURRENCY"]

    print("=== WAVE 1: Content AI bulk regression ===")
    ca = _pytest(" ".join(CONTENT_AI_REGRESSION), "junit_content_ai_regression.xml")
    report["tests_content_ai"] = ca
    report["gates"]["CONTENT_AI_BULK_REGRESSION"] = ca["gate"]

    print("=== WAVE 1: WordPress publish regression ===")
    wp = _pytest(" ".join(WP_REGRESSION), "junit_wp_regression.xml")
    report["tests_wp"] = wp
    report["gates"]["WP_PUBLISH_REGRESSION"] = wp["gate"]

    print("=== WAVE 1: Credit idempotency regression ===")
    cr = _pytest(" ".join(CREDIT_REGRESSION), "junit_credit_regression.xml")
    report["tests_credit"] = cr
    report["gates"]["CREDIT_IDEMPOTENCY"] = cr["gate"]

    print("=== WAVE 1: Queue recovery ===")
    qr = _pytest("tests/test_bulk_celery_no_inline_dup.py tests/test_job_store_fingerprint.py::test_claim_job_by_id_and_skips_running", "junit_queue_recovery.xml")
    report["tests_queue_recovery"] = qr
    report["gates"]["QUEUE_RECOVERY"] = qr["gate"]

    print("=== WAVE 1: Known failures comparison (targeted full subset) ===")
    subset_targets = sorted(
        str(p.relative_to(ROOT))
        for pat in ("test_content_ai_*.py", "test_wp_*.py", "test_bulk_*.py", "test_wave1_*.py")
        for p in (ROOT / "tests").glob(pat)
    )
    subset_targets.append("tests/test_job_store_fingerprint.py")
    sub = _pytest(" ".join(subset_targets), "junit_wave1_subset.xml")
    report["tests_subset"] = sub
    current_fails = _parse_junit_failures(OUT / "junit_wave1_subset.xml")
    report["known_failures"] = _compare_known_failures(current_fails)
    report["gates"]["KNOWN_FAILURES_NOT_INCREASED"] = report["known_failures"]["gate"]

    report["metrics"]["after"] = _collect_metrics()

    critical = [
        "JOB_CLAIM_CONCURRENCY",
        "NO_DUPLICATE_JOB",
        "CREDIT_IDEMPOTENCY",
        "CONTENT_AI_BULK_REGRESSION",
        "WP_PUBLISH_REGRESSION",
        "UI_REGRESSION",
    ]
    if report["celery_multi_queue"]:
        critical.extend(["CELERY_QUEUE", "CELERY_PREFORK"])
    failed_critical = [g for g in critical if report["gates"].get(g) == "FAIL"]
    report["wave1_overall"] = "PASS" if not failed_critical else "FAIL"
    report["failed_critical_gates"] = failed_critical

    (OUT / "wave1_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"gates": report["gates"], "overall": report["wave1_overall"]}, indent=2))
    return 0 if report["wave1_overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
