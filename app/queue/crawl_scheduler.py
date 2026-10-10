"""
Batch scheduling: prioritize URLs, dedupe, enqueue Celery tasks.

Uses Redis when available (SET url hashes per project); falls back to in-process set.
"""

from __future__ import annotations

import hashlib
import os
from typing import Callable

from app.queue.crawl_queue import enqueue_crawl
from app.services.crawler import normalize_url


def _url_hash(url: str) -> str:
    try:
        key = normalize_url(url)
    except Exception:
        key = (url or "").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
    except Exception:
        return None


def _dedupe_key(project_id: int | None) -> str:
    pid = project_id if project_id is not None else 0
    return f"crawl:dedupe:project:{pid}"


def mark_urls_seen(project_id: int | None, urls: list[str]) -> int:
    """Register URLs as scheduled (for cross-batch dedupe). Returns count newly added."""
    r = _redis()
    key = _dedupe_key(project_id)
    n = 0
    if r:
        for u in urls:
            if r.sadd(key, _url_hash(u)):
                n += 1
        if int(os.getenv("CRAWL_DEDUPE_TTL_SECONDS", "604800")) > 0:
            r.expire(key, int(os.getenv("CRAWL_DEDUPE_TTL_SECONDS", "604800")))
        return n
    return len(urls)


def filter_new_urls(project_id: int | None, urls: list[str]) -> list[str]:
    r = _redis()
    key = _dedupe_key(project_id)
    out: list[str] = []
    if not r:
        return list(dict.fromkeys(urls))
    for u in urls:
        h = _url_hash(u)
        if not r.sismember(key, h):
            out.append(u)
    return out


def schedule_crawl_batch(
    urls: list[str],
    project_id: int | None,
    *,
    max_pages: int = 1,
    priority_key: Callable[[str], tuple] | None = None,
    batch_size: int | None = None,
    user_id: int | None = None,
    organization_id: int | None = None,
    allow_unowned: bool = False,
) -> list[dict]:
    """
    Sort by priority (optional), drop duplicates already seen for project, enqueue in chunks.

    Auth/runtime: pass ``user_id`` (+ optional ``organization_id``).
    Legacy/internal-only: ``allow_unowned=True``.

    ``priority_key`` returns a sortable tuple; higher priority first (reverse sort).
    """
    from app.queue.crawl_queue import _require_owner_or_allow_unowned

    _require_owner_or_allow_unowned(user_id=user_id, allow_unowned=allow_unowned)

    bs = batch_size or int(os.getenv("CRAWL_SCHEDULER_BATCH", "500"))
    uniq: list[str] = list(dict.fromkeys(u.strip() for u in urls if (u or "").strip()))
    fresh = filter_new_urls(project_id, uniq)
    if priority_key:
        fresh.sort(key=priority_key, reverse=True)
    enqueued: list[dict] = []
    chunk: list[str] = []
    for u in fresh:
        chunk.append(u)
        if len(chunk) >= bs:
            for item in chunk:
                enqueued.append(
                    enqueue_crawl(
                        item,
                        project_id,
                        max_pages=max_pages,
                        user_id=user_id,
                        organization_id=organization_id,
                        allow_unowned=allow_unowned,
                    )
                )
            mark_urls_seen(project_id, chunk)
            chunk = []
    for item in chunk:
        enqueued.append(
            enqueue_crawl(
                item,
                project_id,
                max_pages=max_pages,
                user_id=user_id,
                organization_id=organization_id,
                allow_unowned=allow_unowned,
            )
        )
    if chunk:
        mark_urls_seen(project_id, chunk)
    return enqueued
