#!/usr/bin/env python3
"""WAVE 0 — baseline snapshot: tests, API contracts, UI, Content AI, infra metrics.

Output: docs/baseline/wave0/
Gates: BASELINE, UI_BASELINE, CONTENT_AI_BASELINE
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave0"
BASE = (os.getenv("WAVE0_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")

# Load env for DB/Redis metrics
for env_path in (ROOT / "env.local", Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")):
    if env_path.is_file():
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

UI_PAGES = [
    "/content-ai",
    "/tool",
    "/chatbot-cskh",
    "/social-auto",
    "/settings",
    "/pricing",
    "/account-billing",
    "/admin/affiliate",
    "/admin/billing",
    "/admin/backup",
    "/admin/email",
    "/admin/integrations",
    "/admin/pricing",
    "/admin/credit-costs",
    "/admin/plan-quotas",
    "/admin/saas-economics",
]

CONTENT_AI_API_CONTRACTS = [
    ("POST", "/content-ai/suggest"),
    ("POST", "/content-ai/suggest-stream"),
    ("POST", "/content-ai/draft"),
    ("POST", "/content-ai/duplicate-check"),
    ("POST", "/content-ai/credit-quote"),
    ("GET", "/content-ai/bulk-jobs/ping"),
    ("POST", "/content-ai/bulk-jobs/start"),
    ("POST", "/content-ai/publish-draft"),
    ("GET", "/content-ai/projects"),
    ("GET", "/content-ai/usage"),
    ("GET", "/content-ai/llm-providers"),
]

CONTENT_AI_TEST_GLOBS = [
    "tests/test_content_ai_e2e_audit_fixes.py",
    "tests/test_content_ai_duplicate_detection.py",
    "tests/test_content_ai_credit.py",
    "tests/test_content_ai_bulk_progress.py",
    "tests/test_content_ai_output_postprocess.py",
    "tests/test_wp_publish_draft.py",
    "tests/test_bulk_celery_no_inline_dup.py",
    "tests/test_content_ai_publish_schedule.py",
    "tests/test_content_ai_word_count_flow.py",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.I)
    return (m.group(1).strip() if m else "")


def _extract_markers(html: str) -> dict[str, Any]:
    """Structural markers — not pixel diff; stable across deploy if UI unchanged."""
    markers: dict[str, Any] = {}
    for pat, key in (
        (r'id="([^"]+)"', "ids_sample"),
        (r'class="([^"]{1,80})"', "classes_sample"),
        (r'<script[^>]+src="([^"]+)"', "script_srcs"),
        (r'<link[^>]+href="([^"]+\.css[^"]*)"', "css_hrefs"),
    ):
        found = re.findall(pat, html, re.I)
        if key.endswith("_sample"):
            markers[key] = sorted(set(found))[:40]
        else:
            markers[key] = sorted(set(found))[:30]
    markers["body_bytes"] = len(html.encode("utf-8", errors="replace"))
    return markers


def _fastapi_app():
    """Return inner FastAPI app (main.app is wrapped by ProbeFastPathMiddleware)."""
    sys.path.insert(0, str(ROOT))
    import main  # noqa: WPS433

    wrapped = main.app
    return wrapped.app if hasattr(wrapped, "app") else wrapped


def snapshot_openapi() -> dict[str, Any]:
    schema = _fastapi_app().openapi()
    paths = schema.get("paths") or {}
    content_ai_paths = {k: v for k, v in paths.items() if "content-ai" in k}
    key_paths = {
        k: v
        for k, v in paths.items()
        if any(
            k.startswith(p)
            for p in (
                "/auth/",
                "/content-ai/",
                "/api/saas/",
                "/health",
                "/ready",
                "/metrics",
                "/api/report",
            )
        )
    }
    summary = {
        "openapi_version": schema.get("openapi"),
        "title": (schema.get("info") or {}).get("title"),
        "version": (schema.get("info") or {}).get("version"),
        "total_paths": len(paths),
        "content_ai_path_count": len(content_ai_paths),
        "key_path_count": len(key_paths),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "openapi_full.json").write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "openapi_content_ai.json").write_text(
        json.dumps(content_ai_paths, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUT / "openapi_key_paths.json").write_text(
        json.dumps(key_paths, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def snapshot_ui_pages() -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    ok = True
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        for path in UI_PAGES:
            t0 = time.perf_counter()
            try:
                r = client.get(f"{BASE}{path}")
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
                body = r.content
                html = body.decode("utf-8", errors="replace")
                row = {
                    "path": path,
                    "status": r.status_code,
                    "content_type": r.headers.get("content-type", ""),
                    "location": r.headers.get("location", ""),
                    "elapsed_ms": elapsed_ms,
                    "sha256": _sha256(body),
                    "title": _extract_title(html) if r.status_code == 200 and "html" in r.headers.get("content-type", "") else "",
                    "markers": _extract_markers(html) if r.status_code == 200 else {},
                }
                # Public pages should return 200; admin may 302 to login (expected)
                if path.startswith("/admin/"):
                    if r.status_code not in (200, 302, 303, 307, 308):
                        row["gate"] = "FAIL"
                        ok = False
                    else:
                        row["gate"] = "PASS"
                elif r.status_code != 200:
                    row["gate"] = "FAIL"
                    ok = False
                else:
                    row["gate"] = "PASS"
            except Exception as exc:
                row = {"path": path, "gate": "FAIL", "error": str(exc)[:300]}
                ok = False
            rows.append(row)
    (OUT / "ui_pages_snapshot.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows, ok


def snapshot_api_contracts() -> dict[str, Any]:
    schema = _fastapi_app().openapi()
    paths = schema.get("paths") or {}
    contracts: list[dict[str, Any]] = []
    missing = []
    for method, path in CONTENT_AI_API_CONTRACTS:
        entry = paths.get(path)
        if not entry or method.lower() not in entry:
            missing.append(f"{method} {path}")
            contracts.append({"method": method, "path": path, "present": False})
            continue
        op = entry[method.lower()]
        contracts.append(
            {
                "method": method,
                "path": path,
                "present": True,
                "operationId": op.get("operationId"),
                "summary": op.get("summary"),
                "requestBody": _schema_ref_summary(op.get("requestBody")),
                "responses": {
                    str(code): _schema_ref_summary(resp) for code, resp in (op.get("responses") or {}).items()
                },
            }
        )
    result = {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "contracts": contracts,
        "missing": missing,
        "gate": "PASS" if not missing else "FAIL",
    }
    (OUT / "api_contracts_content_ai.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def _schema_ref_summary(node: Any) -> Any:
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return {"$ref": node["$ref"]}
    out: dict[str, Any] = {}
    for k in ("description", "required", "content"):
        if k in node:
            out[k] = node[k]
    return out or node


def run_pytest(target: str, junit_name: str) -> dict[str, Any]:
    junit = OUT / junit_name
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(ROOT / ".venv/bin/python"),
        "-m",
        "pytest",
        target,
        "-q",
        "--tb=no",
        f"--junitxml={junit}",
    ]
    env = os.environ.copy()
    # Isolate test DB from production Postgres when suite uses default engine.
    if not env.get("PYTEST_DATABASE_URL") and env.get("DATABASE_URL", "").startswith("postgresql"):
        env["DATABASE_URL"] = f"sqlite:///{(ROOT / '.pytest_wave0.db').as_posix()}"
        env["APP_ENV"] = "test"
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    elapsed = round(time.perf_counter() - t0, 1)
    stdout = proc.stdout or ""
    passed = failed = 0
    m = re.search(r"(\d+) passed", stdout)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", stdout)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) error", stdout)
    errors = int(m.group(1)) if m else 0
    return {
        "target": target,
        "exit_code": proc.returncode,
        "elapsed_sec": elapsed,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "gate": "PASS" if proc.returncode == 0 else "FAIL",
        "tail": "\n".join(stdout.splitlines()[-8:]),
    }


def collect_infra_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {"snapshot_at": datetime.now(timezone.utc).isoformat()}

    # CPU / RAM
    try:
        with open("/proc/loadavg") as f:
            metrics["loadavg"] = f.read().strip()
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = v.strip()
            metrics["meminfo_kb"] = {
                k: mem[k] for k in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached") if k in mem
            }
    except OSError as exc:
        metrics["proc_error"] = str(exc)

    try:
        nproc = subprocess.run(["nproc"], capture_output=True, text=True, check=True)
        metrics["cpu_cores"] = int(nproc.stdout.strip())
    except Exception:
        pass

    # HTTP probes
    try:
        with httpx.Client(timeout=10.0) as c:
            h = c.get(f"{BASE}/health")
            r = c.get(f"{BASE}/ready")
            metrics["health"] = {"status": h.status_code, "body": h.json() if h.status_code == 200 else h.text[:200]}
            metrics["ready"] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:200]}
    except Exception as exc:
        metrics["http_probe_error"] = str(exc)

    # DB connections
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url.startswith("postgresql"):
        try:
            import psycopg2
            from urllib.parse import urlparse

            u = urlparse(db_url.replace("postgresql+psycopg2://", "postgresql://"))
            conn = psycopg2.connect(
                host=u.hostname or "127.0.0.1",
                port=u.port or 5432,
                user=u.username,
                password=u.password,
                dbname=(u.path or "/").lstrip("/"),
                connect_timeout=3,
            )
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            metrics["db_active_connections"] = cur.fetchone()[0]
            cur.execute("SELECT pg_database_size(current_database())")
            metrics["db_size_bytes"] = cur.fetchone()[0]
            cur.close()
            conn.close()
        except Exception as exc:
            metrics["db_error"] = str(exc)[:300]

    # Redis
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        try:
            import redis

            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            info = r.info(section="memory")
            metrics["redis_used_memory_human"] = info.get("used_memory_human")
            metrics["redis_connected_clients"] = r.info("clients").get("connected_clients")
            metrics["redis_db_keys"] = r.dbsize()
            # Celery queue depth (default queue)
            for qname in ("celery", "celery@seoauto-worker"):
                try:
                    metrics[f"redis_list_{qname}"] = r.llen(qname)
                except Exception:
                    pass
        except Exception as exc:
            metrics["redis_error"] = str(exc)[:300]

    # PM2 summary
    try:
        proc = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            apps = json.loads(proc.stdout)
            metrics["pm2"] = [
                {
                    "name": a.get("name"),
                    "status": (a.get("pm2_env") or {}).get("status"),
                    "cpu": (a.get("monit") or {}).get("cpu"),
                    "memory": (a.get("monit") or {}).get("memory"),
                    "restarts": (a.get("pm2_env") or {}).get("restart_time"),
                }
                for a in apps
                if "seoauto" in str(a.get("name", ""))
            ]
    except Exception as exc:
        metrics["pm2_error"] = str(exc)[:200]

    (OUT / "infra_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    return metrics


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "wave": 0,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "gates": {},
    }

    print("=== WAVE 0: OpenAPI snapshot ===")
    report["openapi"] = snapshot_openapi()

    print("=== WAVE 0: API contracts (Content AI) ===")
    api_contracts = snapshot_api_contracts()
    report["api_contracts"] = api_contracts

    print("=== WAVE 0: UI page snapshots ===")
    ui_rows, ui_ok = snapshot_ui_pages()
    report["ui_pages"] = {"count": len(ui_rows), "gate": "PASS" if ui_ok else "FAIL"}

    print("=== WAVE 0: Infra metrics ===")
    report["infra"] = collect_infra_metrics()

    print("=== WAVE 0: Full pytest suite ===")
    full_tests = run_pytest("tests/", "junit_full.xml")
    report["tests_full"] = full_tests
    report["gates"]["BASELINE"] = full_tests["gate"]

    print("=== WAVE 0: Content AI targeted tests ===")
    ca_target = " ".join(CONTENT_AI_TEST_GLOBS)
    ca_tests = run_pytest(ca_target, "junit_content_ai.xml")
    report["tests_content_ai"] = ca_tests
    report["gates"]["CONTENT_AI_BASELINE"] = ca_tests["gate"]

    report["gates"]["UI_BASELINE"] = "PASS" if ui_ok else "FAIL"
    if api_contracts.get("gate") == "FAIL":
        report["gates"]["CONTENT_AI_BASELINE"] = "FAIL"

    all_pass = all(v == "PASS" for v in report["gates"].values())
    report["overall"] = "PASS" if all_pass else "FAIL"

    (OUT / "wave0_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== GATES ===")
    for k, v in report["gates"].items():
        print(f"  {k} = {v}")
    print(f"  OVERALL = {report['overall']}")
    print(f"\nArtifacts: {OUT}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
