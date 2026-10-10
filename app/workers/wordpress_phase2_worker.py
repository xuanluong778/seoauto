"""Celery worker: Publish Guard + AI SEO Phase 2 jobs (async, no sync AI in HTTP)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.db import SessionLocal
from app.queue.celery_app import celery_app
from app.services.wordpress_plugin_phase2_service import execute_phase2_job

_LOG = logging.getLogger(__name__)

TASK_NAME = "wordpress.execute_phase2_job"


@celery_app.task(
    bind=True,
    name=TASK_NAME,
    acks_late=True,
    max_retries=int(os.getenv("WP_PHASE2_MAX_RETRIES", "5")),
    soft_time_limit=int(os.getenv("WP_PHASE2_SOFT_TIME_LIMIT", "840")),
    time_limit=int(os.getenv("WP_PHASE2_TIME_LIMIT", "900")),
)
def execute_phase2_job_task(self, job_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return execute_phase2_job(db, int(job_id))
    except Exception as exc:
        _LOG.exception("wordpress phase2 job %s crashed", job_id)
        countdown = min(300, 15 * (2 ** min(int(self.request.retries), 4)))
        raise self.retry(exc=exc, countdown=countdown) from exc
    finally:
        db.close()


def enqueue_phase2_job(job_id: int) -> str:
    result = execute_phase2_job_task.apply_async(args=[int(job_id)])
    return str(result.id)
