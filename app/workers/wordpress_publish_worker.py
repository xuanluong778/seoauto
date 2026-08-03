"""Celery worker: WordPress publish jobs → SEO Helper plugin (HMAC)."""

from __future__ import annotations

import logging
from typing import Any

from app.db import SessionLocal
from app.queue.celery_app import celery_app
from app.services.wordpress_plugin_publish_service import execute_publish_job

_LOG = logging.getLogger(__name__)

TASK_NAME = "wordpress.execute_publish_job"


@celery_app.task(bind=True, name=TASK_NAME, acks_late=True)
def execute_publish_job_task(self, job_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return execute_publish_job(db, int(job_id))
    except Exception:
        _LOG.exception("wordpress publish job %s crashed", job_id)
        raise
    finally:
        db.close()


def enqueue_publish_job(job_id: int) -> str:
    result = execute_publish_job_task.apply_async(args=[int(job_id)])
    return str(result.id)


def enqueue_publish_job_delayed(job_id: int, *, countdown: int) -> str:
    result = execute_publish_job_task.apply_async(args=[int(job_id)], countdown=max(1, int(countdown)))
    return str(result.id)
