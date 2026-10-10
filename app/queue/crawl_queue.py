"""Enqueue crawl jobs and load completed crawl bundles for the SEO pipeline."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.crawl_job import DistributedCrawlJob, DistributedCrawlResult

_LOG = logging.getLogger("crawl.queue")


class CrawlOwnerRequiredError(ValueError):
    """Authenticated/runtime crawl must set user_id (+ resolved organization_id)."""

    def __init__(self, message: str = "user_id is required for distributed crawl jobs.") -> None:
        self.code = "crawl_owner_required"
        super().__init__(message)


def _resolve_tenant(
    user_id: int | None,
    organization_id: int | None,
    db: Session,
) -> tuple[int | None, int | None]:
    if user_id is None or int(user_id) <= 0:
        return None, None
    from app.services.tenant_org import OrganizationForbiddenError, resolve_organization_id

    uid = int(user_id)
    try:
        org_id = resolve_organization_id(uid, organization_id, db=db)
    except OrganizationForbiddenError:
        raise
    return uid, int(org_id)


def _require_owner_or_allow_unowned(
    *,
    user_id: int | None,
    allow_unowned: bool,
) -> None:
    if user_id is not None and int(user_id) > 0:
        return
    if allow_unowned:
        return
    raise CrawlOwnerRequiredError()


def job_owned_by_tenant(
    job: DistributedCrawlJob,
    *,
    user_id: int,
    organization_id: int | None = None,
) -> bool:
    """True when job tenant columns match the caller (legacy unowned rows → deny)."""
    uid = int(user_id or 0)
    if uid <= 0:
        return False
    job_uid = getattr(job, "user_id", None)
    if job_uid is None:
        return False
    if int(job_uid) != uid:
        return False
    from app.services.tenant_org import personal_organization_id

    expected_org = (
        int(organization_id)
        if organization_id is not None and int(organization_id) > 0
        else personal_organization_id(uid)
    )
    job_org = getattr(job, "organization_id", None)
    if job_org is None:
        return False
    return int(job_org) == int(expected_org)


def get_crawl_job_for_user(
    job_id: int,
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> DistributedCrawlJob | None:
    """Load crawl job only if owned by tenant. Cross-tenant → None."""
    own = db is None
    session = db or SessionLocal()
    try:
        try:
            uid, org_id = _resolve_tenant(user_id, organization_id, session)
        except Exception:
            return None
        if uid is None or org_id is None:
            return None
        job = session.query(DistributedCrawlJob).filter(DistributedCrawlJob.id == int(job_id)).one_or_none()
        if job is None:
            return None
        if not job_owned_by_tenant(job, user_id=uid, organization_id=org_id):
            return None
        return job
    finally:
        if own:
            session.close()


def enqueue_crawl(
    url: str,
    project_id: int | None = None,
    *,
    max_pages: int = 1,
    user_id: int | None = None,
    organization_id: int | None = None,
    allow_unowned: bool = False,
) -> dict[str, Any]:
    """
    Persist a job row and dispatch ``process_crawl_job`` to Celery.

    Runtime/auth callers must pass ``user_id`` (and optional ``organization_id``).
    Legacy/internal-only: ``allow_unowned=True`` when no tenant context exists.

    Returns: ``{"job_id", "task_id", "url", "project_id", "max_pages", "user_id", "organization_id"}``.
    """
    from app.workers.crawl_worker import process_crawl_job

    _require_owner_or_allow_unowned(user_id=user_id, allow_unowned=allow_unowned)

    db = SessionLocal()
    try:
        uid, org_id = _resolve_tenant(user_id, organization_id, db)
        if not allow_unowned and (uid is None or org_id is None):
            raise CrawlOwnerRequiredError()
        job = DistributedCrawlJob(
            project_id=project_id,
            user_id=uid,
            organization_id=org_id,
            job_type="single_url" if max_pages <= 1 else "site",
            target_url=url,
            max_pages=max_pages,
            status="queued",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        ar = process_crawl_job.apply_async(
            kwargs={
                "url": url,
                "project_id": project_id,
                "max_pages": max_pages,
                "distributed_job_id": job.id,
            }
        )
        job.celery_task_id = ar.id
        db.commit()
        if ar.id and uid is not None and org_id is not None:
            try:
                from app.services.async_task_registry import register_task_owner

                # Own DB session inside register — do not disturb crawl job transaction.
                register_task_owner(ar.id, uid, organization_id=org_id)
            except Exception:
                _LOG.exception("enqueue_crawl_register_task_owner_failed job_id=%s", job.id)
        _LOG.info(
            "enqueue_crawl",
            extra={
                "job_id": job.id,
                "task_id": ar.id,
                "url": url,
                "project_id": project_id,
                "max_pages": max_pages,
                "user_id": uid,
                "organization_id": org_id,
            },
        )
        return {
            "job_id": job.id,
            "task_id": ar.id,
            "url": url,
            "project_id": project_id,
            "max_pages": max_pages,
            "user_id": uid,
            "organization_id": org_id,
        }
    finally:
        db.close()


def fetch_crawl_bundle_for_job(
    job_id: int,
    db: Session | None = None,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    """
    Rebuild ``{pages, edges, domain}`` from stored results for ``analyze_technical_seo`` / pipeline.

    Returns None if job missing, not completed/partial, or (when ``user_id`` set) not owned by tenant.
    """
    own = db is None
    if own:
        db = SessionLocal()
    assert db is not None
    try:
        if user_id is not None:
            job = get_crawl_job_for_user(
                int(job_id),
                user_id=int(user_id),
                organization_id=organization_id,
                db=db,
            )
        else:
            job = db.query(DistributedCrawlJob).filter(DistributedCrawlJob.id == job_id).one_or_none()
        if not job or job.status not in ("completed", "partial"):
            return None
        rows = (
            db.query(DistributedCrawlResult)
            .filter(DistributedCrawlResult.job_id == job_id)
            .order_by(DistributedCrawlResult.id.asc())
            .all()
        )
        pages: list[dict[str, Any]] = []
        for r in rows:
            if not r.result_json:
                continue
            try:
                pages.append(json.loads(r.result_json))
            except json.JSONDecodeError:
                continue
        edges: list[dict[str, str]] = []
        seen_e: set[tuple[str, str]] = set()
        for p in pages:
            u = str(p.get("url") or "")
            for link in p.get("internal_links") or []:
                t = str(link)
                key = (u, t)
                if key in seen_e:
                    continue
                seen_e.add(key)
                edges.append({"from": u, "to": t})
        domain = ""
        if pages:
            from urllib.parse import urlparse

            domain = urlparse(str(pages[0].get("url") or "")).netloc or ""
        return {"pages": pages, "total": len(pages), "edges": edges, "domain": domain, "distributed_job_id": job_id}
    finally:
        if own:
            db.close()
