"""Celery application — broker and result backend use Redis."""

from __future__ import annotations

import os

from celery import Celery
import importlib

from app.queue.celery_queues import build_celery_queue_config

_redis = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0").strip()

celery_app = Celery(
    "tooltechnical",
    broker=_redis,
    backend=_redis,
    include=[
        "app.workers.crawl_worker",
        "app.workers.keyword_tasks",
        "app.workers.wordpress_publish_worker",
        "app.workers.wordpress_schedule_tasks",
        "app.workers.chatbot_cskh_notify_worker",
        "app.workers.email_automation_marketing_worker",
        "app.workers.technical_scan_tasks",
        "app.workers.content_ai_bulk_tasks",
        "app.workers.content_ai_generation_tasks",
        "app.workers.job_queue_recover",
        "app.services.internal_linking.tasks",
        "app.workers.embedding_tasks",
    ],
)

# Ensure critical ORM models are registered for SQLAlchemy string relationships
# in worker contexts. Without this, mapper init can fail (e.g. KnowledgeBase -> Project).
try:
    importlib.import_module("app.models.seo")
    importlib.import_module("app.models.knowledge")
    # Import User last so relationships can resolve.
    importlib.import_module("app.models.user")
except Exception:
    # Worker can still run most tasks; email notifications require proper mapper init.
    pass

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=int(os.getenv("CELERY_WORKER_PREFETCH", "1")),
    worker_max_tasks_per_child=int(os.getenv("CELERY_WORKER_MAX_TASKS_PER_CHILD", "200")),
    worker_soft_shutdown_timeout=int(os.getenv("CELERY_WORKER_SOFT_SHUTDOWN_TIMEOUT", "30")),
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "900")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "840")),
    task_default_retry_delay=int(os.getenv("CELERY_TASK_DEFAULT_RETRY_DELAY", "30")),
    broker_connection_retry_on_startup=True,
    **build_celery_queue_config(),
)

# Email automation + marketing scheduling.
# Requires a separate `celery beat` process in production.
celery_app.conf.beat_schedule = {
    "email-automation-tick": {
        "task": "email.automation_tick",
        "schedule": int(os.getenv("EMAIL_AUTOMATION_TICK_SECONDS", "300")),
    },
    "email-marketing-tick": {
        "task": "email.marketing_tick",
        "schedule": int(os.getenv("EMAIL_MARKETING_TICK_SECONDS", "300")),
    },
    "jobs-recover-queued": {
        "task": "jobs.recover_queued",
        "schedule": float(os.getenv("JOB_RECOVER_SCHEDULE_SECONDS", "30")),
    },
}
if os.getenv("WP_PUBLISH_CELERY_SCHEDULER", "0").strip().lower() in ("1", "true", "yes", "on"):
    celery_app.conf.beat_schedule["wordpress-publish-schedule-tick"] = {
        "task": "wordpress.publish_schedule_tick",
        "schedule": float(
            os.getenv("WP_PUBLISH_SCHEDULE_TICK_SECONDS")
            or os.getenv("CONTENT_AI_PUBLISH_WORKER_SECONDS", "20")
        ),
    }
