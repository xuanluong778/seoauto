"""
Crawler layer: JavaScript rendering (Playwright) with HTTP fallback.

Produces the same crawl bundle shape as legacy `crawl_site_detailed` / Playwright path.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

_LOG = logging.getLogger(__name__)


def _apply_crawl_intelligence(pages: list[dict[str, Any]], start_url: str) -> None:
    from urllib.parse import urlparse

    from app.services.crawl_intelligence import enrich_page_crawl_intelligence

    host = (urlparse(start_url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for p in pages:
        enrich_page_crawl_intelligence(p, domain=host, proxy_server=p.get("proxy_used"))


def schedule_technical_crawl(
    start_url: str,
    max_pages: int,
    project_id: int | None = None,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    allow_unowned: bool = False,
) -> dict[str, Any]:
    """
    Enqueue a distributed crawl (Celery + Redis). Poll DB or use ``run_technical_crawl_from_job``.

    Auth/runtime must pass ``user_id``. Legacy/internal: ``allow_unowned=True``.

    Requires workers: ``celery -A app.queue.celery_app worker -l info --concurrency 1``.
    """
    from app.queue.crawl_queue import enqueue_crawl

    return enqueue_crawl(
        start_url,
        project_id,
        max_pages=max_pages,
        user_id=user_id,
        organization_id=organization_id,
        allow_unowned=allow_unowned,
    )


def run_technical_crawl_from_job(
    job_id: int,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    allow_unowned: bool = False,
) -> dict[str, Any]:
    """Load a completed/partial distributed job bundle (same shape as :func:`run_technical_crawl`)."""
    from app.queue.crawl_queue import _require_owner_or_allow_unowned, fetch_crawl_bundle_for_job

    _require_owner_or_allow_unowned(user_id=user_id, allow_unowned=allow_unowned)
    return fetch_crawl_bundle_for_job(
        job_id,
        user_id=user_id,
        organization_id=organization_id,
    ) or {"pages": [], "edges": [], "domain": "", "total": 0}


def run_technical_crawl(
    start_url: str,
    max_pages: int,
    *,
    deadline_monotonic: float | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """
    Crawl internal URLs starting at `start_url`.

    Returns dict with keys: pages, edges, domain (compatible with analyzer).
    Optional deadline_monotonic (time.monotonic) stops crawl early with partial_data.
    """
    use_pw = os.getenv("USE_PLAYWRIGHT", "1").lower() in ("1", "true", "yes")
    extra: dict[str, Any] = {}
    if deadline_monotonic is not None:
        extra["deadline_monotonic"] = deadline_monotonic
    if on_progress is not None:
        extra["on_progress"] = on_progress
    if use_pw:
        try:
            from app.services.playwright_crawler import crawl_site_detailed_rendered

            out = crawl_site_detailed_rendered(start_url, max_pages=max_pages, **extra)
            _apply_crawl_intelligence(out.get("pages") or [], start_url)
            return out
        except Exception as exc:
            _LOG.warning("Playwright crawl unavailable (%s); using HTTP.", exc)
    from app.services.crawler import crawl_site_detailed

    out = crawl_site_detailed(start_url, max_pages=max_pages, **extra)
    _apply_crawl_intelligence(out.get("pages") or [], start_url)
    return out
