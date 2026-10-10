"""Celery: technical SEO scan jobs (job_store poll contract unchanged)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.queue.celery_app import celery_app

_LOG = logging.getLogger(__name__)

TASK_NAME = "technical.run_scan"


def technical_scan_celery_enabled() -> bool:
    return os.getenv("TECHNICAL_SCAN_CELERY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def technical_scan_thread_fallback_enabled() -> bool:
    return os.getenv("TECHNICAL_SCAN_THREAD_FALLBACK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


@celery_app.task(
    bind=True,
    name=TASK_NAME,
    acks_late=True,
    max_retries=12,
    soft_time_limit=int(os.getenv("TECHNICAL_SCAN_SOFT_TIME_LIMIT", "840")),
    time_limit=int(os.getenv("TECHNICAL_SCAN_TIME_LIMIT", "900")),
)
def run_technical_scan_task(self, job_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Run technical scan. Fairness: if slots full, re-queue with exponential backoff.
    max_retries used only for slot deferral / soft recover — credit finalize stays inside runner (no credit double-charge on success path).
    """
    from app.services.job_store import fail_job, get_job, update_job
    from app.services.queue_fairness import release_slot, try_acquire_slot
    from app.services.technical_scan_job import run_technical_scan_job

    jid = str(job_id)
    st = get_job(jid)
    if st is None:
        return {"ok": False, "error": "job_not_found"}
    if st.state in ("SUCCESS", "ERROR", "CANCELLED"):
        return {"ok": True, "skipped": st.state}

    pl = payload if isinstance(payload, dict) else (st.payload if isinstance(st.payload, dict) else {})
    user_id = int(pl.get("user_id") or st.user_id or 0)
    if user_id <= 0:
        fail_job(jid, error="Missing user_id on technical job")
        return {"ok": False, "error": "missing_user"}

    ttl = int(os.getenv("TECHNICAL_SCAN_BUDGET_SECONDS", "540")) + 120
    if not try_acquire_slot("technical", user_id, jid, ttl_sec=ttl):
        update_job(jid, message="Đang chờ slot worker (giới hạn concurrency)…")
        countdown = min(120, 5 * (2 ** min(int(self.request.retries), 4)))
        raise self.retry(countdown=countdown)

    try:
        run_technical_scan_job(jid, pl)
        return {"ok": True, "job_id": jid}
    except Exception as exc:
        _LOG.exception("technical celery task failed job_id=%s", jid)
        try:
            st2 = get_job(jid)
            if st2 and st2.state not in ("SUCCESS", "ERROR", "CANCELLED"):
                fail_job(jid, error=str(exc)[:2000])
        except Exception:
            pass
        return {"ok": False, "error": type(exc).__name__}
    finally:
        release_slot("technical", user_id, jid)


def enqueue_technical_scan(job_id: str, payload: dict[str, Any] | None = None) -> str:
    async_result = run_technical_scan_task.apply_async(args=[str(job_id), payload or {}])
    return str(async_result.id)
