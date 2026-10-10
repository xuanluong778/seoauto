"""WAVE 5 — dedicated Celery embedding worker + WP corpus cache."""

from __future__ import annotations

import os


def embedding_celery_enabled() -> bool:
    """When True: Uvicorn must not load sentence-transformers; use Celery embedding queue."""
    return os.getenv("EMBEDDING_CELERY_WORKER", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_embedding_worker_process() -> bool:
    """True only in the dedicated embedding Celery worker process."""
    return os.getenv("CELERY_EMBEDDING_WORKER", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def uvicorn_may_load_embedding_model() -> bool:
    if embedding_celery_enabled():
        return False
    return not is_embedding_worker_process()


def duplicate_wp_corpus_cache_enabled() -> bool:
    """When True: WP REST corpus is cached per-tenant; live fetch is async on refresh."""
    return os.getenv("DUPLICATE_WP_CORPUS_CACHE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def duplicate_wp_async_fetch_enabled() -> bool:
    """When True: stale corpus refresh runs in background (does not block Uvicorn)."""
    return duplicate_wp_corpus_cache_enabled() and os.getenv(
        "DUPLICATE_WP_ASYNC_FETCH", "1"
    ).strip().lower() in ("1", "true", "yes", "on")
