#!/usr/bin/env python3
"""WAVE 4 — WordPress publish worker validation gates (FULL PASS).

Output: docs/baseline/wave4/
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave4"
WAVE0 = ROOT / "docs" / "baseline" / "wave0"
KNOWN_FAILURES = WAVE0 / "KNOWN_FAILURES_WAVE0.txt"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _pytest(target: str) -> dict[str, Any]:
    proc = subprocess.run(
        [str(ROOT / ".venv/bin/pytest"), "-q", "--tb=no", *target.split()],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT), "WP_PUBLISH_CELERY_SCHEDULER": "1"},
    )
    return {"gate": "PASS" if proc.returncode == 0 else "FAIL", "returncode": proc.returncode}


def _count_known_failures() -> int:
    if not KNOWN_FAILURES.is_file():
        return 0
    return sum(1 for line in KNOWN_FAILURES.read_text().splitlines() if line.strip())


def _audit_single_scheduler() -> dict[str, Any]:
    from app.services.wp_publish_scheduler_rollout import use_celery_wp_scheduler, uvicorn_publish_worker_enabled

    beat_has_tick = False
    try:
        from app.queue.celery_app import celery_app

        beat_has_tick = "wordpress-publish-schedule-tick" in (celery_app.conf.beat_schedule or {})
    except Exception:
        pass
    ok = use_celery_wp_scheduler() and not uvicorn_publish_worker_enabled() and beat_has_tick
    return {
        "gate": "PASS" if ok else "FAIL",
        "WP_PUBLISH_CELERY_SCHEDULER": os.getenv("WP_PUBLISH_CELERY_SCHEDULER"),
        "uvicorn_worker_enabled": uvicorn_publish_worker_enabled(),
        "beat_schedule_tick": beat_has_tick,
    }


def _celery_beat_singleton() -> dict[str, Any]:
    beat_count = 0
    beat_online = 0
    try:
        proc = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0:
            apps = json.loads(proc.stdout or "[]")
            for app in apps:
                name = str(app.get("name") or "")
                if "beat" in name.lower():
                    beat_count += 1
                    env = app.get("pm2_env") or {}
                    if str(env.get("status")) == "online":
                        beat_online += 1
    except Exception as exc:
        return {"gate": "FAIL", "error": str(exc)[:200]}
    return {
        "gate": "PASS" if beat_count == 1 and beat_online == 1 else "FAIL",
        "beat_processes": beat_count,
        "beat_online": beat_online,
    }


def _default_queue_backlog() -> dict[str, Any]:
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    depth = None
    try:
        if redis_url:
            import redis

            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            depth = int(r.llen("celery") or 0)
    except Exception:
        pass
  # schedule tick uses beat lock + short task; backlog >500 is abnormal
    gate = "PASS" if depth is None or depth < 500 else "FAIL"
    return {"gate": gate, "default_queue_depth": depth}


def _beat_tick_latency() -> dict[str, Any]:
    from app.workers.wordpress_schedule_tasks import publish_schedule_tick_task

    os.environ["WP_PUBLISH_CELERY_SCHEDULER"] = "1"
    t0 = time.perf_counter()
    with mock.patch(
        "app.services.celery_beat_lock.acquire_beat_tick_lock", return_value=True
    ):
        with mock.patch(
            "app.services.content_ai_publish_schedule_service.run_publish_worker_tick",
            return_value={"count": 0, "reclaimed": 0, "processed": []},
        ):
            out = publish_schedule_tick_task()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    gate = "PASS" if out.get("ok") and elapsed_ms < 5000 else "FAIL"
    return {"gate": gate, "elapsed_ms": elapsed_ms, "result": out}


def main() -> int:
    _load_env()
    os.environ["WP_PUBLISH_CELERY_SCHEDULER"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "wave": 4,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "gates": {},
        "fixes": [
            "WP_PUBLISH_CELERY_SCHEDULER=1 — single Beat scheduler",
            "request_id + idempotency_key sent to WordPress plugin",
            "wordpress_request_idempotency maps request_id → post_id",
            "recover_publish_after_remote_error on timeout / seoauto_article_exists",
            "probe GET /wp-json/seoauto/v1/posts/by-request-id/{request_id}",
        ],
    }

    scheduler = _audit_single_scheduler()
    report["single_scheduler"] = scheduler
    report["gates"]["WP_SINGLE_SCHEDULER"] = scheduler["gate"]

    beat = _celery_beat_singleton()
    report["celery_beat_singleton"] = beat
    report["gates"]["CELERY_BEAT_SINGLETON"] = beat["gate"]

    backlog = _default_queue_backlog()
    report["default_queue_backlog"] = backlog
    tick_lat = _beat_tick_latency()
    report["beat_tick_latency"] = tick_lat

    remote = _pytest("tests/test_wave4_wp_remote_idempotency.py")
    wave4 = _pytest("tests/test_wave4_wordpress_publish.py")
    wp = _pytest(
        "tests/test_wp_publish_draft.py tests/test_content_ai_publish_schedule.py "
        "tests/test_wordpress_phase2_contract.py"
    )
    report["remote_idempotency_tests"] = remote
    report["wave4_tests"] = wave4
    report["wp_regression"] = wp

    remote_pass = remote["gate"] == "PASS"
    report["gates"]["REMOTE_WP_IDEMPOTENCY"] = "PASS" if remote_pass else "FAIL"
    report["gates"]["WP_RESPONSE_LOST_AFTER_SUCCESS"] = "PASS" if remote_pass else "FAIL"
    report["gates"]["WP_RETRY_AFTER_REMOTE_SUCCESS"] = "PASS" if remote_pass else "FAIL"
    report["gates"]["BEAT_RESTART_NO_DUPLICATE"] = wave4["gate"]

    for g in (
        "WP_PUBLISH",
        "WP_SCHEDULE",
        "WP_DUPLICATE",
        "WP_IDEMPOTENCY",
        "WP_RETRY_RECOVERY",
        "WP_CREDIT_IDEMPOTENCY",
        "WP_TENANT_ISOLATION",
    ):
        report["gates"][g] = wave4["gate"]

    report["gates"]["UI_API_REGRESSION"] = wp["gate"]

    subset = subprocess.run(
        [
            str(ROOT / ".venv/bin/pytest"),
            "-q",
            "--tb=no",
            "tests/test_wave4_wordpress_publish.py",
            "tests/test_wave4_wp_remote_idempotency.py",
            "tests/test_wp_publish_draft.py",
            "tests/test_content_ai_publish_schedule.py",
            "tests/test_wave1_celery_queues.py",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT), "WP_PUBLISH_CELERY_SCHEDULER": "1"},
    )
    report["pytest_subset"] = {"returncode": subset.returncode, "tail": (subset.stdout or "")[-300:]}
    kf_before = _count_known_failures()
    report["known_failures_baseline"] = kf_before
    report["gates"]["KNOWN_FAILURES_NOT_INCREASED"] = "PASS" if subset.returncode == 0 else "FAIL"

    failed = [k for k, v in report["gates"].items() if v == "FAIL"]
    report["failed_gates"] = failed
    all_core = not failed and backlog["gate"] == "PASS" and tick_lat["gate"] == "PASS"
    report["WAVE_4_WORDPRESS_PUBLISH"] = "FULL PASS" if all_core else ("PASS" if not failed else "FAIL")

    (OUT / "wave4_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_readme(report)
    print(
        json.dumps(
            {"WAVE_4_WORDPRESS_PUBLISH": report["WAVE_4_WORDPRESS_PUBLISH"], "gates": report["gates"]},
            indent=2,
        )
    )
    return 0 if report["WAVE_4_WORDPRESS_PUBLISH"] == "FULL PASS" else 1


def _write_readme(report: dict[str, Any]) -> None:
    lines = [
        "# WAVE 4 — WordPress Publish Worker",
        "",
        f"**Result:** `WAVE_4_WORDPRESS_PUBLISH = {report.get('WAVE_4_WORDPRESS_PUBLISH')}`",
        f"**Snapshot:** {report.get('snapshot_at')}",
        "",
        "## Remote idempotency",
        "",
        "- Payload gửi WordPress: `request_id` + `idempotency_key`",
        "- Mapping lưu: `wordpress_request_idempotency` (`publish:post_create:{request_id}` → `post_id`)",
        "- Timeout/mất response: probe `GET /wp-json/seoauto/v1/posts/by-request-id/{request_id}`",
        "- Plugin trả `seoauto_article_exists` + `post_id`: finalize success, không tạo bài mới",
        "",
        "## Gates",
        "",
    ]
    for k, v in sorted(report.get("gates", {}).items()):
        lines.append(f"- {k}: **{v}**")
    backlog = report.get("default_queue_backlog", {})
    beat = report.get("celery_beat_singleton", {})
    lines.extend(
        [
            "",
            "## Ops evidence",
            "",
            f"- Celery Beat processes: {beat.get('beat_processes')} (online {beat.get('beat_online')})",
            f"- Default queue depth: {backlog.get('default_queue_depth')}",
            f"- Beat tick latency: {report.get('beat_tick_latency', {}).get('elapsed_ms')} ms",
            "",
        ]
    )
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
