"""
Celery worker: Playwright crawl with shared browser per process, DB persistence, proxies.

Run: ``celery -A app.queue.celery_app worker -l info -P prefork --concurrency=1``
(``--concurrency=1`` recommended per Playwright process unless you raise process count via Docker replicas.)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import time
from typing import Any

from celery.signals import worker_process_init, worker_process_shutdown

from app.db import SessionLocal
from app.models.crawl_job import DistributedCrawlJob, DistributedCrawlResult
from app.queue.celery_app import celery_app
from app.services.crawl_logging import crawl_event
from app.services.crawl_monitor import record_crawl_outcome, worker_heartbeat
from app.services.crawler import normalize_url
from app.services.crawl_intelligence import enrich_page_crawl_intelligence
from app.services.domain_intelligence import record_domain_crawl_outcome
from app.services.domain_rate_limiter import acquire_domain_slot
from app.workers.crawl_intel import _host_from_url, run_intel_crawl

_LOG = logging.getLogger(__name__)

_browser_state: dict[str, Any] = {"pw": None, "browser": None}


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _url_hash(url: str) -> str:
    try:
        key = normalize_url(url)
    except Exception:
        key = (url or "").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@worker_process_init.connect
def _init_playwright(**_kwargs: Any) -> None:
    if os.getenv("CRAWLER_WORKER_DISABLE_BROWSER_POOL", "").lower() in ("1", "true", "yes"):
        return
    try:
        from playwright.sync_api import sync_playwright

        from app.services.playwright_stealth import CHROMIUM_LAUNCH_ARGS

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=list(CHROMIUM_LAUNCH_ARGS))
        _browser_state["pw"] = pw
        _browser_state["browser"] = browser
        crawl_event("worker_browser_ready", worker_id=_worker_id())
    except Exception as exc:
        _LOG.warning("Playwright pool init failed; tasks will launch own browser: %s", exc)


@worker_process_shutdown.connect
def _shutdown_playwright(**_kwargs: Any) -> None:
    br = _browser_state.get("browser")
    pw = _browser_state.get("pw")
    try:
        if br:
            br.close()
    except Exception:
        pass
    try:
        if pw:
            pw.stop()
    except Exception:
        pass
    _browser_state.clear()


def _upsert_result(
    db: Any,
    *,
    job_id: int,
    page: dict[str, Any],
    proxy_used: str | None,
    worker_id: str,
    retry_count: int,
    crawl_time_seconds: float | None,
    error_message: str | None = None,
) -> None:
    u = str(page.get("url") or "")
    uh = _url_hash(u)
    row = (
        db.query(DistributedCrawlResult)
        .filter(DistributedCrawlResult.job_id == job_id, DistributedCrawlResult.url_hash == uh)
        .one_or_none()
    )
    payload = json.dumps(page, ensure_ascii=False, default=str)
    st = str(page.get("crawl_status") or "success")
    br = page.get("block_reason")
    brs = str(br)[:255] if br else None
    if row:
        row.url = u
        row.result_json = payload
        row.crawl_status = st
        row.block_reason = brs
        row.proxy_used = proxy_used
        row.worker_id = worker_id
        row.retry_count = retry_count
        row.crawl_time_seconds = crawl_time_seconds
        row.error_message = error_message
    else:
        db.add(
            DistributedCrawlResult(
                job_id=job_id,
                url=u,
                url_hash=uh,
                crawl_status=st,
                block_reason=brs,
                proxy_used=proxy_used,
                worker_id=worker_id,
                retry_count=retry_count,
                crawl_time_seconds=crawl_time_seconds,
                result_json=payload,
                error_message=error_message,
            )
        )


@celery_app.task(
    bind=True,
    name="crawl.process_crawl_job",
    retry_backoff=True,
    retry_backoff_max=int(os.getenv("CELERY_RETRY_BACKOFF_MAX", "600")),
    retry_jitter=True,
    max_retries=int(os.getenv("CELERY_TASK_MAX_RETRIES", "7")),
)
def process_crawl_job(
    self,
    *,
    url: str,
    project_id: int | None = None,
    max_pages: int = 1,
    distributed_job_id: int,
) -> dict[str, Any]:
    """
    Execute crawl for ``distributed_job_id`` (DB row created by ``enqueue_crawl``).

    Returns per-job summary fields for the last processed URL (multi-page jobs: last page).
    """
    wid = _worker_id()
    retry_count = int(getattr(self.request, "retries", 0) or 0)
    db = SessionLocal()
    proxy_used: str | None = None
    t0 = time.perf_counter()
    last_summary: dict[str, Any] = {}
    try:
        job = db.query(DistributedCrawlJob).filter(DistributedCrawlJob.id == distributed_job_id).one_or_none()
        if not job:
            crawl_event("crawl_job_missing", worker_id=wid, job_id=distributed_job_id)
            return {"url": url, "crawl_status": "failed", "error": "job_not_found"}

        job.status = "running"
        job.error_message = None
        db.commit()
        worker_heartbeat(wid)

        if not acquire_domain_slot(url, timeout_sec=float(os.getenv("CRAWL_DOMAIN_ACQUIRE_TIMEOUT", "120"))):
            job.status = "failed"
            job.error_message = "domain_rate_limit_timeout"
            db.commit()
            crawl_event("crawl_domain_acquire_failed", job_id=job.id, url=url, worker_id=wid)
            return {
                "url": url,
                "crawl_status": "failed",
                "proxy_used": None,
                "worker_id": wid,
                "retry_count": retry_count,
                "crawl_time": round(time.perf_counter() - t0, 3),
            }

        bundle: dict[str, Any] | None = None
        last_proxy_server: str | None = None

        ext_pw = _browser_state.get("pw")
        ext_br = _browser_state.get("browser")
        host = _host_from_url(url)

        crawl_event(
            "crawl_intel_start",
            job_id=job.id,
            url=url,
            worker_id=wid,
            domain=host,
            retry_count=retry_count,
        )
        bundle, proxy_used = run_intel_crawl(url, max_pages, ext_pw=ext_pw, ext_br=ext_br)

        last_proxy_server = proxy_used

        if not bundle:
            job.status = "failed"
            job.error_message = "no_crawl_result"
            db.commit()
            return {
                "url": url,
                "crawl_status": "failed",
                "proxy_used": proxy_used,
                "worker_id": wid,
                "retry_count": retry_count,
                "crawl_time": round(time.perf_counter() - t0, 3),
            }

        pages = bundle.get("pages") or []
        total_time = time.perf_counter() - t0
        per_page_time = (total_time / len(pages)) if pages else total_time

        for p in pages:
            ct = round(per_page_time, 4)
            p["proxy_used"] = proxy_used
            enrich_page_crawl_intelligence(p, domain=host or "", proxy_server=proxy_used)
            record_domain_crawl_outcome(host or "", p, latency_seconds=ct)
            _upsert_result(
                db,
                job_id=job.id,
                page=p,
                proxy_used=proxy_used,
                worker_id=wid,
                retry_count=retry_count,
                crawl_time_seconds=ct,
            )
            st = str(p.get("crawl_status") or "success")
            record_crawl_outcome(crawl_status=st, crawl_time_sec=ct)
            crawl_event(
                "crawl_page_saved",
                job_id=job.id,
                domain=(url.split("/")[2] if "://" in url else url)[:120],
                url=str(p.get("url")),
                crawl_status=st,
                proxy_server=last_proxy_server,
                worker_id=wid,
            )
            last_summary = {
                "url": str(p.get("url")),
                "crawl_status": st,
                "proxy_used": proxy_used,
                "worker_id": wid,
                "retry_count": retry_count,
                "crawl_time": ct,
                "crawl_quality_score": p.get("crawl_quality_score"),
                "crawl_confidence_score": p.get("crawl_confidence_score"),
                "quality_level": p.get("quality_level"),
                "data_trust": p.get("data_trust"),
                "reliability_flags": p.get("reliability_flags"),
            }

        job.status = "completed"
        db.commit()
        crawl_event("crawl_job_completed", job_id=job.id, worker_id=wid, pages=len(pages))
        try:
            from app.services.cost_usage_logger import record_infra_cost_usage

            record_infra_cost_usage(
                db,
                user_id=job.user_id,
                organization_id=job.organization_id,
                feature_key="crawl_job",
                quantity=max(1, len(pages) or 1),
                provider="crawl",
                request_id=f"crawl:{job.id}:{retry_count}",
                credits_used=0,
                extra={"job_type": job.job_type, "distributed_job_id": job.id},
            )
            db.commit()
        except Exception:
            db.rollback()
            _LOG.exception("crawl cost usage log failed job_id=%s", job.id)
        return last_summary or {
            "url": url,
            "crawl_status": "success",
            "proxy_used": proxy_used,
            "worker_id": wid,
            "retry_count": retry_count,
            "crawl_time": round(total_time, 3),
        }
    except Exception as exc:
        try:
            db.rollback()
            job = db.query(DistributedCrawlJob).filter(DistributedCrawlJob.id == distributed_job_id).one_or_none()
            if job and job.status != "completed":
                saved = (
                    db.query(DistributedCrawlResult)
                    .filter(DistributedCrawlResult.job_id == distributed_job_id)
                    .count()
                )
                job.status = "partial" if saved else "failed"
                job.error_message = str(exc)[:2000]
                db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()
