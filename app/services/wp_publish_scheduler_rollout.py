"""WAVE 4 — single Celery Beat scheduler for WordPress scheduled publish."""

from __future__ import annotations

import os


def use_celery_wp_scheduler() -> bool:
    """When True: Beat owns due-schedule ticks; Uvicorn must not poll or use per-row timers."""
    return os.getenv("WP_PUBLISH_CELERY_SCHEDULER", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def uvicorn_publish_worker_enabled() -> bool:
    if use_celery_wp_scheduler():
        return False
    flag = os.getenv("CONTENT_AI_PUBLISH_WORKER_AUTO")
    if flag is None:
        flag = os.getenv("CONTENT_AI_PUBLISH_SCHEDULER_AUTO", "1")
    return str(flag or "1").strip().lower() not in {"0", "false", "no", "off"}
