"""Re-enqueue QUEUED technical/bulk jobs if Celery message was lost (worker crash before ack)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from app.queue.celery_app import celery_app

_LOG = logging.getLogger(__name__)

TASK_NAME = "jobs.recover_queued"


def _age_seconds(created_at: Any) -> float:
    if created_at is None:
        return 9999.0
    if isinstance(created_at, (int, float)):
        return max(0.0, time.time() - float(created_at))
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return 9999.0
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds())
    return 9999.0


@celery_app.task(name=TASK_NAME, acks_late=True, max_retries=0)
def recover_queued_jobs_task() -> dict[str, Any]:
    from app.services.celery_beat_lock import acquire_beat_tick_lock
    from app.services.job_store import list_jobs_by_states

    if not acquire_beat_tick_lock(TASK_NAME, ttl_seconds=25):
        return {"ok": True, "skipped": "beat_lock"}

    min_age = float(os.getenv("JOB_RECOVER_MIN_AGE_SECONDS", "20"))
    limit = int(os.getenv("JOB_RECOVER_LIMIT", "20"))
    enqueued = 0
    errors: list[str] = []

    try:
        rows = list_jobs_by_states(
            states=("QUEUED", "PENDING"),
            job_types=("technical_analyze", "content_ai_bulk"),
            limit=limit,
        )
    except Exception as exc:
        _LOG.warning("recover_list_failed: %s", exc)
        return {"ok": False, "error": type(exc).__name__}

    for job in rows:
        try:
            if _age_seconds(getattr(job, "created_at", None)) < min_age:
                continue
            jtype = str(getattr(job, "job_type", "") or "")
            jid = str(job.job_id)
            if jtype == "technical_analyze":
                from app.workers.technical_scan_tasks import enqueue_technical_scan

                pl = job.payload if isinstance(job.payload, dict) else {}
                enqueue_technical_scan(jid, pl)
                enqueued += 1
            elif jtype == "content_ai_bulk":
                from app.workers.content_ai_bulk_tasks import enqueue_content_ai_bulk

                enqueue_content_ai_bulk(jid)
                enqueued += 1
        except Exception as exc:
            errors.append(f"{getattr(job, 'job_id', '?')}:{type(exc).__name__}")
            _LOG.warning("recover_enqueue_failed: %s", exc)

    # WAVE 2: recover stale async Content AI generations
    try:
        from app.services.content_ai_generation_store import list_stale_generations
        from app.workers.content_ai_generation_tasks import enqueue_content_ai_generation

        for gen in list_stale_generations(states=("QUEUED", "RUNNING"), limit=limit):
            if _age_seconds(gen.created_at) < min_age:
                continue
            enqueue_content_ai_generation(gen.generation_id)
            enqueued += 1
    except Exception as exc:
        errors.append(f"generation_recover:{type(exc).__name__}")
        _LOG.warning("recover_generations_failed: %s", exc)

    try:
        from app.db import SessionLocal
        from app.services.wordpress_plugin_publish_service import (
            list_recoverable_publish_jobs,
            recover_publish_job,
        )

        rdb = SessionLocal()
        try:
            for wp_job in list_recoverable_publish_jobs(rdb, limit=limit, min_age_seconds=min_age):
                if recover_publish_job(rdb, int(wp_job.id)):
                    enqueued += 1
        finally:
            rdb.close()
    except Exception as exc:
        errors.append(f"wp_publish_recover:{type(exc).__name__}")
        _LOG.warning("recover_wp_publish_failed: %s", exc)

    return {"ok": True, "enqueued": enqueued, "errors": errors}
