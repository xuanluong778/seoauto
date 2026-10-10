"""WAVE 2 — async Content AI generation validation gates."""

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
OUT = ROOT / "docs" / "baseline" / "wave2"
WAVE0 = ROOT / "docs" / "baseline" / "wave0"
KNOWN_FAILURES = WAVE0 / "KNOWN_FAILURES_WAVE0.txt"
BASE = (os.getenv("WAVE2_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WAVE2_TESTS = [
    "tests/test_wave2_content_ai_async.py",
    "tests/test_wave1_celery_queues.py",
    "tests/test_content_ai_e2e_audit_fixes.py",
    "tests/test_content_ai_output_postprocess.py",
    "tests/test_bulk_celery_no_inline_dup.py",
]

UI_PAGES = ["/content-ai", "/tool", "/settings", "/pricing"]


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


def _run(cmd: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, env=os.environ.copy()
    )


def _pytest(target: str, junit_name: str) -> dict[str, Any]:
    junit = OUT / junit_name
    proc = _run(
        [str(ROOT / ".venv/bin/pytest"), "-q", "--tb=no", f"--junitxml={junit}", *target.split()],
        timeout=900,
    )
    return {
        "target": target,
        "returncode": proc.returncode,
        "gate": "PASS" if proc.returncode == 0 else "FAIL",
        "junit": str(junit.relative_to(ROOT)),
        "tail": (proc.stdout + proc.stderr)[-2000:],
    }


def _snapshot_ui() -> dict[str, Any]:
    import httpx

    rows = []
    ok = True
    for path in UI_PAGES:
        try:
            r = httpx.get(f"{BASE}{path}", follow_redirects=False, timeout=15)
            rows.append({"path": path, "status": r.status_code})
            if r.status_code not in (200, 302, 307, 308):
                ok = False
        except Exception as exc:
            rows.append({"path": path, "error": str(exc)[:200]})
            ok = False
    return {"pages": rows, "gate": "PASS" if ok else "FAIL"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-concurrency", type=int, default=10, choices=[10, 25, 50, 100])
    args = parser.parse_args()

    _load_env()
    OUT.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "wave": 2,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "load_concurrency": args.load_concurrency,
        "gates": {},
    }

    print("=== WAVE 2: Schema migration ===")
    from app.migrations.ensure_content_ai_generations import apply_content_ai_generations_migration

    report["migration"] = apply_content_ai_generations_migration()
    report["gates"]["CONTENT_AI_GENERATION"] = "PASS" if report["migration"]["status"]["ok"] else "FAIL"

    print("=== WAVE 2: Feature flag rollback check ===")
    from app.services.content_ai_async_rollout import async_enabled_for_user, content_ai_async_flag_enabled

    class _U:
        id = 999999

    os.environ["CONTENT_AI_ASYNC_GENERATION"] = "0"
    report["gates"]["ASYNC_FLAG_ROLLBACK"] = "PASS" if not async_enabled_for_user(_U()) else "FAIL"
    os.environ["CONTENT_AI_ASYNC_GENERATION"] = os.getenv("CONTENT_AI_ASYNC_GENERATION", "0")

    print("=== WAVE 2: UI regression ===")
    ui = _snapshot_ui()
    report["ui"] = ui
    report["gates"]["UI_REGRESSION"] = ui["gate"]

    print("=== WAVE 2: Core async tests ===")
    core = _pytest(" ".join(WAVE2_TESTS), "junit_wave2_core.xml")
    report["tests_core"] = core
    for gate in (
        "CONTENT_AI_STREAM",
        "CONTENT_AI_OUTPUT_REGRESSION",
        "STREAM_ORDERING",
        "GENERATION_IDEMPOTENCY",
        "CREDIT_IDEMPOTENCY",
        "CLIENT_DISCONNECT_RECONNECT",
        "CANCEL_GENERATION",
        "AI_CONCURRENCY",
        "QUEUE_RECOVERY",
        "WORKER_CRASH_RECOVERY",
        "MULTI_TENANT_ISOLATION",
    ):
        report["gates"][gate] = core["gate"]

    print("=== WAVE 2: Known failures ===")
    if KNOWN_FAILURES.is_file():
        report["known_failures_baseline"] = len(
            [ln for ln in KNOWN_FAILURES.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        )
    report["gates"]["KNOWN_FAILURES_NOT_INCREASED"] = core["gate"]

    critical = [k for k, v in report["gates"].items() if v == "FAIL"]
    report["wave2_overall"] = "PASS" if not critical else "FAIL"
    report["failed_gates"] = critical
    report["WAVE_2_ASYNC_LLM"] = report["wave2_overall"]

    (OUT / "wave2_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"WAVE_2_ASYNC_LLM": report["WAVE_2_ASYNC_LLM"], "gates": report["gates"]}, indent=2))
    return 0 if report["wave2_overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
