"""Celery delayed job: Chatbot CSKH unread inbox email."""

from __future__ import annotations

import logging
from typing import Any

from app.db import SessionLocal
from app.queue.celery_app import celery_app

_LOG = logging.getLogger(__name__)

TASK_NAME = "chatbot_cskh.send_unread_email"


@celery_app.task(bind=True, name=TASK_NAME, acks_late=True, max_retries=3)
def send_unread_email_task(self, job_id: int) -> dict[str, Any]:
    from app.services.chatbot_cskh_email_notify import execute_notify_job

    db = SessionLocal()
    try:
        return execute_notify_job(db, int(job_id))
    except Exception as exc:
        _LOG.exception("cskh unread email job %s crashed", job_id)
        raise self.retry(exc=exc, countdown=30) from exc
    finally:
        db.close()


def enqueue_unread_email_job(job_id: int, *, countdown: int) -> str:
    result = send_unread_email_task.apply_async(
        args=[int(job_id)],
        countdown=max(0, int(countdown)),
    )
    return str(result.id)
