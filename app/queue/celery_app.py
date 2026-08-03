"""Celery application — broker and result backend use Redis."""

from __future__ import annotations

import os

from celery import Celery

_redis = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0").strip()

celery_app = Celery(
    "tooltechnical",
    broker=_redis,
    backend=_redis,
    include=[
        "app.workers.crawl_worker",
        "app.workers.keyword_tasks",
        "app.workers.wordpress_publish_worker",
        "app.services.internal_linking.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=int(os.getenv("CELERY_WORKER_PREFETCH", "1")),
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "900")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "840")),
    broker_connection_retry_on_startup=True,
)
