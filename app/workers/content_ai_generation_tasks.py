"""Celery: Content AI async generation (WAVE 2 — content_ai queue)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.queue.celery_app import celery_app
from app.services.content_ai_generation_store import TERMINAL_STATES

_LOG = logging.getLogger(__name__)

TASK_NAME = "content_ai.run_generation"


def content_ai_generation_celery_enabled() -> bool:
    return os.getenv("CONTENT_AI_ASYNC_GENERATION", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@celery_app.task(
    bind=True,
    name=TASK_NAME,
    acks_late=True,
    max_retries=12,
    soft_time_limit=int(os.getenv("CONTENT_AI_GEN_SOFT_TIME_LIMIT", "7200")),
    time_limit=int(os.getenv("CONTENT_AI_GEN_TIME_LIMIT", "7500")),
)
def run_content_ai_generation_task(self, generation_id: str) -> dict[str, Any]:
    from app.db import SessionLocal
    from app.services.content_ai_generation_runner import run_content_ai_generation
    from app.services.content_ai_generation_store import (
        claim_generation,
        fail_generation,
        get_generation,
        update_generation_progress,
    )
    from app.services.queue_fairness import release_slot, try_acquire_slot

    gid = str(generation_id)
    db = SessionLocal()
    try:
        row = get_generation(db, gid)
    finally:
        db.close()

    if row is None:
        return {"ok": False, "error": "generation_not_found"}
    if row.state in TERMINAL_STATES:
        return {"ok": True, "skipped": row.state}

    user_id = int(row.user_id)
    org_id = int(row.organization_id)

    if not try_acquire_slot("generation", user_id, gid, org_id=org_id, ttl_sec=7200):
        update_generation_progress(gid, message="Đang chờ slot Content AI…")
        countdown = min(120, 8 * (2 ** min(int(self.request.retries), 4)))
        raise self.retry(countdown=countdown)

    try:
        if row.state == "QUEUED":
            claimed = claim_generation(gid)
            if not claimed:
                db2 = SessionLocal()
                try:
                    row2 = get_generation(db2, gid)
                finally:
                    db2.close()
                if row2 and row2.state in TERMINAL_STATES:
                    return {"ok": True, "skipped": row2.state}
                if row2 and row2.state == "RUNNING":
                    return {"ok": True, "deduped": True}
                countdown = min(60, 5 * (2 ** min(int(self.request.retries), 3)))
                raise self.retry(countdown=countdown)

        payload = dict(row.request or {})
        return run_content_ai_generation(gid, payload)
    except Exception as exc:
        _LOG.exception("content_ai generation task failed generation_id=%s", gid)
        fail_generation(gid, error=str(exc)[:2000])
        return {"ok": False, "error": type(exc).__name__}
    finally:
        release_slot("generation", user_id, gid, org_id=org_id)


def enqueue_content_ai_generation(generation_id: str) -> str:
    async_result = run_content_ai_generation_task.apply_async(args=[str(generation_id)])
    return str(async_result.id)
