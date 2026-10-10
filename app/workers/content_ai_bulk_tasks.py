"""Celery: Content AI bulk article jobs (job_store poll contract unchanged)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.queue.celery_app import celery_app

_LOG = logging.getLogger(__name__)

TASK_NAME = "content_ai.run_bulk"


def content_ai_bulk_celery_enabled() -> bool:
    return os.getenv("CONTENT_AI_BULK_CELERY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


@celery_app.task(
    bind=True,
    name=TASK_NAME,
    acks_late=True,
    max_retries=20,
    soft_time_limit=int(os.getenv("CONTENT_AI_BULK_SOFT_TIME_LIMIT", "7200")),
    time_limit=int(os.getenv("CONTENT_AI_BULK_TIME_LIMIT", "7500")),
)
def run_content_ai_bulk_task(self, job_id: str) -> dict[str, Any]:
    from app.services.content_ai_bulk_runner import run_content_ai_bulk_job
    from app.services.job_store import claim_job_by_id, fail_job, get_job, update_job
    from app.services.queue_fairness import release_slot, try_acquire_slot

    jid = str(job_id)
    st = get_job(jid)
    if st is None:
        return {"ok": False, "error": "job_not_found"}
    if st.state in ("SUCCESS", "ERROR", "CANCELLED"):
        return {"ok": True, "skipped": st.state}

    pl = st.payload if isinstance(st.payload, dict) else {}
    user_id = int(pl.get("user_id") or st.user_id or 0)
    if user_id <= 0:
        fail_job(jid, error="Missing user_id on bulk job")
        return {"ok": False, "error": "missing_user"}

    if not try_acquire_slot("bulk", user_id, jid, ttl_sec=7200):
        update_job(jid, message="Đang chờ slot Content AI (giới hạn concurrency)…")
        countdown = min(180, 8 * (2 ** min(int(self.request.retries), 4)))
        raise self.retry(countdown=countdown)

    try:
        # Claim QUEUED → RUNNING if still queued; allow resume of orphan RUNNING
        if st.state in ("QUEUED", "PENDING"):
            claimed = claim_job_by_id(jid)
            if not claimed:
                st2 = get_job(jid)
                if st2 and st2.state in ("SUCCESS", "ERROR", "CANCELLED"):
                    return {"ok": True, "skipped": st2.state}
                # Another worker claimed — exit quietly
                if st2 and st2.state == "RUNNING":
                    pass
                else:
                    countdown = min(60, 5 * (2 ** min(int(self.request.retries), 3)))
                    raise self.retry(countdown=countdown)

        run_content_ai_bulk_job(jid, pl)
        return {"ok": True, "job_id": jid}
    except Exception as exc:
        _LOG.exception("content_ai bulk celery task failed job_id=%s", jid)
        try:
            st2 = get_job(jid)
            if st2 and st2.state not in ("SUCCESS", "ERROR", "CANCELLED"):
                fail_job(jid, error=str(exc)[:2000])
        except Exception:
            pass
        return {"ok": False, "error": type(exc).__name__}
    finally:
        release_slot("bulk", user_id, jid)


def enqueue_content_ai_bulk(job_id: str) -> str:
    async_result = run_content_ai_bulk_task.apply_async(args=[str(job_id)])
    return str(async_result.id)
