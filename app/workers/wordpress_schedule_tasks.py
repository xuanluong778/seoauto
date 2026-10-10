"""WAVE 4 — Celery Beat: single scheduler for Content AI WordPress publish schedules."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.db import SessionLocal
from app.queue.celery_app import celery_app
from app.services.wp_publish_scheduler_rollout import use_celery_wp_scheduler

_LOG = logging.getLogger(__name__)

TASK_NAME = "wordpress.publish_schedule_tick"


def _poll_seconds() -> float:
    raw = os.getenv("WP_PUBLISH_SCHEDULE_TICK_SECONDS") or os.getenv(
        "CONTENT_AI_PUBLISH_WORKER_SECONDS", "20"
    )
    try:
        return max(10.0, min(60.0, float(raw)))
    except (TypeError, ValueError):
        return 20.0


def _batch_size() -> int:
    raw = os.getenv("WP_PUBLISH_SCHEDULE_BATCH") or os.getenv("CONTENT_AI_PUBLISH_WORKER_BATCH", "10")
    try:
        return max(1, min(int(raw), 100))
    except (TypeError, ValueError):
        return 10


def _stale_seconds() -> int:
    raw = os.getenv("CONTENT_AI_PUBLISH_STALE_SECONDS", "900")
    try:
        return max(120, int(raw))
    except (TypeError, ValueError):
        return 900


@celery_app.task(name=TASK_NAME, acks_late=True, max_retries=0)
def publish_schedule_tick_task() -> dict[str, Any]:
    """Claim due schedules and enqueue WordPress publish jobs (idempotent)."""
    if not use_celery_wp_scheduler():
        return {"ok": True, "skipped": "WP_PUBLISH_CELERY_SCHEDULER=0"}

    from app.services.celery_beat_lock import acquire_beat_tick_lock

    ttl = max(15, int(_poll_seconds()) - 2)
    if not acquire_beat_tick_lock(TASK_NAME, ttl_seconds=ttl):
        return {"ok": True, "skipped": "beat_lock"}

    from app.services.content_ai_publish_schedule_service import run_publish_worker_tick

    db = SessionLocal()
    try:
        summary = run_publish_worker_tick(
            db,
            limit=_batch_size(),
            stale_seconds=_stale_seconds(),
        )
        return {"ok": True, **summary}
    except Exception as exc:
        _LOG.exception("wordpress publish schedule tick failed")
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:200]}
    finally:
        db.close()
