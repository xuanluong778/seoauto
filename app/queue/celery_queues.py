"""Celery queue names and task routing (WAVE 1 — multi-worker scale).

Enable with ``CELERY_MULTI_QUEUE=1``. When disabled, Celery uses the legacy
single default queue (backward compatible with solo worker).
"""

from __future__ import annotations

import os

from kombu import Exchange, Queue

QUEUE_CONTENT_AI = "content_ai"
QUEUE_WORDPRESS = "wordpress"
QUEUE_CRAWL = "crawl"
QUEUE_EMAIL = "email"
QUEUE_EMBEDDING = "embedding"
QUEUE_DEFAULT = "default"

ALL_QUEUES: tuple[str, ...] = (
    QUEUE_CONTENT_AI,
    QUEUE_WORDPRESS,
    QUEUE_CRAWL,
    QUEUE_EMAIL,
    QUEUE_EMBEDDING,
    QUEUE_DEFAULT,
)

# Explicit routing — keeps crawl/bulk/email/wordpress off shared workers.
TASK_ROUTES: dict[str, dict[str, str]] = {
    "content_ai.run_bulk": {"queue": QUEUE_CONTENT_AI},
    "content_ai.run_generation": {"queue": QUEUE_CONTENT_AI},
    "technical.run_scan": {"queue": QUEUE_CONTENT_AI},
    "wordpress.execute_publish_job": {"queue": QUEUE_WORDPRESS},
    "wordpress.execute_phase2_job": {"queue": QUEUE_WORDPRESS},
    "wordpress.publish_schedule_tick": {"queue": QUEUE_DEFAULT},
    "internal_links.sync_site": {"queue": QUEUE_WORDPRESS},
    "internal_links.embed_site": {"queue": QUEUE_WORDPRESS},
    "embedding.embed_keywords": {"queue": QUEUE_EMBEDDING},
    "duplicate.sync_wp_corpus": {"queue": QUEUE_EMBEDDING},
    "crawl.process_crawl_job": {"queue": QUEUE_CRAWL},
    "email.automation_tick": {"queue": QUEUE_EMAIL},
    "email.send_outbox": {"queue": QUEUE_EMAIL},
    "email.marketing_tick": {"queue": QUEUE_EMAIL},
    "email.send_campaign": {"queue": QUEUE_EMAIL},
    "chatbot_cskh.send_unread_email": {"queue": QUEUE_EMAIL},
    "jobs.recover_queued": {"queue": QUEUE_DEFAULT},
    "keywords.research_run": {"queue": QUEUE_DEFAULT},
}


def celery_multi_queue_enabled() -> bool:
    return os.getenv("CELERY_MULTI_QUEUE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def queue_for_task(task_name: str) -> str:
    route = TASK_ROUTES.get(str(task_name or "").strip())
    if route and route.get("queue"):
        return str(route["queue"])
    return QUEUE_DEFAULT


def build_celery_queue_config() -> dict:
    """Return Celery conf fragment when multi-queue mode is on; else empty dict."""
    if not celery_multi_queue_enabled():
        return {}
    exchange = Exchange("celery", type="direct")
    task_queues = tuple(Queue(name, exchange, routing_key=name) for name in ALL_QUEUES)
    return {
        "task_queues": task_queues,
        "task_default_queue": QUEUE_DEFAULT,
        "task_default_exchange": "celery",
        "task_default_routing_key": QUEUE_DEFAULT,
        "task_routes": TASK_ROUTES,
        "task_create_missing_queues": True,
    }
