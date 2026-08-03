"""In-process worker loop for content_ai_bulk jobs (runs while FastAPI server is up)."""

from __future__ import annotations

import os
import threading
import time

_started = False
_lock = threading.Lock()


def content_ai_bulk_worker_loop() -> None:
    from app.services.content_ai_bulk_runner import run_content_ai_bulk_job
    from app.services.job_store import (
        claim_next_pending_job,
        ensure_job_schema,
        fail_job,
        mark_stale_jobs_failed,
        mark_stale_queued_failed,
        update_job,
    )

    while True:
        try:
            ensure_job_schema()
            break
        except Exception:
            time.sleep(2.0)
    poll = float(os.getenv("CONTENT_AI_BULK_POLL_SECONDS", "2.0"))
    watchdog = int(os.getenv("JOB_WATCHDOG_SECONDS", "900"))
    queue_stale = int(os.getenv("JOB_QUEUE_STALE_SECONDS", "180"))

    while True:
        job = None
        try:
            mark_stale_jobs_failed(stale_seconds=watchdog)
            mark_stale_queued_failed(stale_seconds=queue_stale)
            job = claim_next_pending_job(job_type="content_ai_bulk")
            if not job:
                time.sleep(poll)
                continue
            payload = job.payload if isinstance(job.payload, dict) else {}
            update_job(
                job.job_id,
                state="RUNNING",
                progress=max(1, int(job.progress or 1)),
                message="Bắt đầu viết bài hàng loạt…",
            )
            run_content_ai_bulk_job(job.job_id, payload)
        except Exception as exc:
            if job:
                try:
                    fail_job(job.job_id, error=str(exc)[:2000])
                except Exception:
                    pass
            time.sleep(poll)


def start_content_ai_bulk_worker_background() -> None:
    global _started
    if (os.getenv("CONTENT_AI_BULK_WORKER_AUTO", "1") or "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=content_ai_bulk_worker_loop, name="content-ai-bulk-worker", daemon=True)
    t.start()
