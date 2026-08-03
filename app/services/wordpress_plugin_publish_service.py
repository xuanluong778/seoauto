"""Enqueue and execute WordPress publish jobs via Celery → SEO Helper plugin."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.wordpress_plugin import WordpressConnection, WordpressPublishJob
from app.services.plugin_entitlement_service import check_plugin_entitlement
from app.services.wordpress_plugin_client import plugin_patch_json, plugin_post_json
from app.services.wordpress_plugin_retry import backoff_seconds
from app.services.wordpress_plugin_security import (
    decrypt_site_secret,
    personal_organization_id,
)
from app.services.wordpress_pairing_service import _count_org_sites  # noqa: PLC2701

_LOG = logging.getLogger(__name__)

JOB_STATUSES = frozenset({"queued", "running", "retrying", "success", "failed", "blocked"})
DEFAULT_MAX_RETRIES = int(os.getenv("WORDPRESS_PUBLISH_MAX_RETRIES", "5"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_error(text: str) -> str:
    import re

    raw = str(text or "")
    raw = re.sub(r"(?i)(site_secret|password|token|signature|authorization)\s*[:=]\s*\S+", r"\1=***", raw)
    return raw[:2000]


def get_connection_for_site(
    db: Session,
    *,
    user_id: int,
    wp_site_id: str | None = None,
    site_url: str | None = None,
) -> WordpressConnection | None:
    """Resolve active plugin connection by publishing_site_id and/or site URL/domain.

    Pairing stores ``publishing_site_id`` as ``wps_…`` while Content AI / Settings often
    pass the publishing-sites UUID — match by normalized domain as fallback.
    """
    from app.services.wordpress_plugin_security import normalize_domain

    org_id = personal_organization_id(int(user_id))
    pub_id = str(wp_site_id or "").strip()
    url = str(site_url or "").strip()

    if pub_id:
        row = db.execute(
            select(WordpressConnection)
            .where(
                WordpressConnection.organization_id == org_id,
                WordpressConnection.user_id == int(user_id),
                WordpressConnection.publishing_site_id == pub_id,
                WordpressConnection.status.in_(("active", "pending")),
            )
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            return row
        # Resolve URL from publishing-sites store when caller passed UUID/id.
        if not url:
            try:
                from app.services.publishing_sites_store import get_site

                site = get_site(pub_id, user_id=int(user_id), reveal_password=False)
                if site:
                    url = str(site.get("url") or "").strip()
            except Exception:
                pass

    dom = normalize_domain(url) if url else ""
    if not dom and pub_id and ("." in pub_id) and not pub_id.startswith("wps_"):
        # Allow passing a bare host / URL as wp_site_id.
        dom = normalize_domain(pub_id)

    if not dom:
        return None

    rows = db.execute(
        select(WordpressConnection)
        .where(
            WordpressConnection.organization_id == org_id,
            WordpressConnection.user_id == int(user_id),
            WordpressConnection.status.in_(("active", "pending")),
        )
        .order_by(WordpressConnection.id.desc())
    ).scalars().all()
    for row in rows:
        row_dom = str(row.domain_normalized or "").strip().lower() or normalize_domain(str(row.site_url or ""))
        if row_dom and row_dom == dom:
            return row
    return None


def get_connection_for_user(
    db: Session,
    *,
    user: User,
    connection_id: int | None = None,
    wp_site_id: str | None = None,
    site_url: str | None = None,
) -> WordpressConnection | None:
    """Resolve connection scoped to caller tenant — prevents cross-user/org IDOR."""
    org_id = personal_organization_id(int(user.id))
    if connection_id:
        return db.execute(
            select(WordpressConnection).where(
                WordpressConnection.id == int(connection_id),
                WordpressConnection.organization_id == org_id,
                WordpressConnection.user_id == int(user.id),
            ).limit(1)
        ).scalar_one_or_none()
    return get_connection_for_site(
        db,
        user_id=int(user.id),
        wp_site_id=wp_site_id,
        site_url=site_url,
    )


def job_to_dict(job: WordpressPublishJob) -> dict[str, Any]:
    result = None
    if job.result_json:
        try:
            result = json.loads(job.result_json)
        except ValueError:
            result = None
    return {
        "id": job.id,
        "request_id": job.request_id,
        "command_type": job.command_type,
        "status": job.status,
        "connection_id": job.connection_id,
        "schedule_id": job.schedule_id,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "wp_post_id": job.wp_post_id,
        "wp_post_url": job.wp_post_url,
        "result": result,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _check_entitlement(db: Session, user: User, connection: WordpressConnection | None) -> tuple[bool, str]:
    site_count = _count_org_sites(db, personal_organization_id(int(user.id)))
    ent = check_plugin_entitlement(db, user, current_site_count=site_count)
    if not ent.allowed:
        return False, str(ent.reason or "entitlement_denied")
    if connection is not None:
        features = set(ent.enabled_features or [])
        if features and "seo_helper" not in features:
            return False, "plan_not_supported"
    return True, "active"


def create_publish_job(
    db: Session,
    *,
    user: User,
    payload: dict[str, Any],
    connection_id: int | None = None,
    wp_site_id: str | None = None,
    site_url: str | None = None,
    schedule_id: int | None = None,
    request_id: str | None = None,
    command_type: str = "post_create",
    source_article_id: str | None = None,
    enqueue: bool = True,
) -> WordpressPublishJob:
    """Entitlement check → job row → Celery enqueue."""
    org_id = personal_organization_id(int(user.id))
    connection = get_connection_for_user(
        db,
        user=user,
        connection_id=connection_id,
        wp_site_id=wp_site_id,
        site_url=site_url,
    )

    allowed, reason = _check_entitlement(db, user, connection)
    req_id = str(request_id or uuid.uuid4())

    body = dict(payload)
    if source_article_id:
        body.setdefault("source_article_id", source_article_id)
    body.setdefault("request_id", req_id)
    if connection is not None:
        body.setdefault("connection_id", int(connection.id))

    if not allowed:
        job = WordpressPublishJob(
            user_id=int(user.id),
            organization_id=org_id,
            connection_id=int(connection.id) if connection else None,
            schedule_id=schedule_id,
            request_id=req_id,
            command_type=command_type,
            status="blocked",
            payload_json=json.dumps(body, ensure_ascii=False),
            error_code=reason,
            error_message=f"Entitlement blocked: {reason}",
            completed_at=_utc_now(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    if connection is None:
        err_code = "connection_forbidden" if connection_id else "no_plugin_connection"
        err_msg = (
            "Không có quyền truy cập connection này."
            if connection_id
            else "Chưa ghép nối SEO Helper plugin cho website này."
        )
        job = WordpressPublishJob(
            user_id=int(user.id),
            organization_id=org_id,
            connection_id=None,
            schedule_id=schedule_id,
            request_id=req_id,
            command_type=command_type,
            status="blocked",
            payload_json=json.dumps(body, ensure_ascii=False),
            error_code=err_code,
            error_message=err_msg,
            completed_at=_utc_now(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    existing = db.execute(
        select(WordpressPublishJob).where(
            WordpressPublishJob.organization_id == org_id,
            WordpressPublishJob.request_id == req_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=org_id,
        connection_id=int(connection.id),
        schedule_id=schedule_id,
        request_id=req_id,
        command_type=command_type,
        status="queued",
        payload_json=json.dumps(body, ensure_ascii=False),
        max_retries=DEFAULT_MAX_RETRIES,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if enqueue:
        from app.workers.wordpress_publish_worker import enqueue_publish_job

        task_id = enqueue_publish_job(job.id)
        job.celery_task_id = task_id
        db.commit()
        db.refresh(job)

    return job


def execute_publish_job(db: Session, job_id: int) -> dict[str, Any]:
    """Run one job attempt (Celery worker entry). Keeps request_id stable on retry."""
    job = db.get(WordpressPublishJob, int(job_id))
    if job is None:
        return {"ok": False, "error": "job_not_found"}

    if job.status in ("success", "blocked", "failed"):
        return {"ok": job.status == "success", "status": job.status, "job": job_to_dict(job)}

    now = _utc_now()
    claimed = db.execute(
        update(WordpressPublishJob)
        .where(
            WordpressPublishJob.id == int(job_id),
            WordpressPublishJob.status.in_(("queued", "retrying")),
        )
        .values(status="running", started_at=job.started_at or now, updated_at=now)
    )
    db.commit()
    if int(getattr(claimed, "rowcount", 0) or 0) == 0:
        db.refresh(job)
        if job.status == "running":
            return {"ok": False, "status": "running", "deduped": True, "job": job_to_dict(job)}
        if job.status in ("success", "blocked", "failed"):
            return {"ok": job.status == "success", "status": job.status, "job": job_to_dict(job)}
        return {"ok": False, "status": job.status, "job": job_to_dict(job)}

    db.refresh(job)

    connection = db.get(WordpressConnection, int(job.connection_id or 0))
    if connection is None:
        return _finalize_job(
            db,
            job,
            status="blocked",
            error_code="connection_missing",
            error_message="WordPress connection not found",
        )

    user = db.get(User, int(job.user_id))
    if user is None:
        return _finalize_job(
            db,
            job,
            status="failed",
            error_code="user_missing",
            error_message="User not found",
        )

    allowed, reason = _check_entitlement(db, user, connection)
    if not allowed:
        return _finalize_job(
            db,
            job,
            status="blocked",
            error_code=reason,
            error_message=f"Entitlement blocked: {reason}",
        )

    secret = decrypt_site_secret(connection.site_secret_encrypted or "")
    if not secret:
        return _finalize_job(
            db,
            job,
            status="blocked",
            error_code="missing_secret",
            error_message="Cannot decrypt site_secret",
        )

    try:
        payload = json.loads(job.payload_json or "{}")
    except ValueError:
        payload = {}

    payload["request_id"] = job.request_id
    payload.setdefault("connection_id", int(connection.id))

    site_id = str(connection.publishing_site_id or "")
    cmd = str(job.command_type or "post_create").lower()
    if cmd in ("post_update", "patch_post"):
        post_id = int(payload.get("post_id") or 0)
        path = f"/wp-json/seoauto/v1/posts/{post_id}"
        result, err = plugin_patch_json(
            site_url=connection.site_url,
            site_id=site_id,
            connection_id=int(connection.id),
            secret=secret,
            path=path,
            payload=payload,
            request_id=job.request_id,
        )
    else:
        path = "/wp-json/seoauto/v1/posts"
        result, err = plugin_post_json(
            site_url=connection.site_url,
            site_id=site_id,
            connection_id=int(connection.id),
            secret=secret,
            path=path,
            payload=payload,
            request_id=job.request_id,
        )

    secret = ""

    if err is not None:
        return _handle_failure(db, job, err)

    if not isinstance(result, dict):
        return _handle_failure(
            db,
            job,
            type("E", (), {"retryable": False, "blocked": False, "error_code": "empty_result", "message": "Empty plugin response"})(),
        )

    wp_post_id = int(result.get("post_id") or 0) or None
    wp_url = str(result.get("permalink") or result.get("link") or "").strip() or None
    return _finalize_job(
        db,
        job,
        status="success",
        result=result,
        wp_post_id=wp_post_id,
        wp_post_url=wp_url,
    )


def _handle_failure(db: Session, job: WordpressPublishJob, err: Any) -> dict[str, Any]:
    job.retry_count = int(job.retry_count or 0) + 1
    job.error_code = str(getattr(err, "error_code", "error"))
    job.error_message = _sanitize_error(str(getattr(err, "message", "")))

    if getattr(err, "blocked", False):
        return _finalize_job(
            db,
            job,
            status="blocked",
            error_code=job.error_code,
            error_message=job.error_message,
        )

    retryable = bool(getattr(err, "retryable", False))
    if retryable and job.retry_count <= int(job.max_retries or DEFAULT_MAX_RETRIES):
        delay = backoff_seconds(job.retry_count - 1)
        job.status = "retrying"
        job.next_retry_at = _utc_now() + timedelta(seconds=delay)
        job.updated_at = _utc_now()
        db.commit()

        from app.workers.wordpress_publish_worker import enqueue_publish_job_delayed

        task_id = enqueue_publish_job_delayed(job.id, countdown=int(delay))
        job.celery_task_id = task_id
        db.commit()
        _LOG.warning(
            "wp publish job %s retry %s in %.0fs request_id=%s code=%s",
            job.id,
            job.retry_count,
            delay,
            job.request_id,
            job.error_code,
        )
        return {"ok": False, "status": "retrying", "job": job_to_dict(job)}

    return _finalize_job(
        db,
        job,
        status="failed",
        error_code=job.error_code,
        error_message=job.error_message,
    )


def _finalize_job(
    db: Session,
    job: WordpressPublishJob,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    result: dict[str, Any] | None = None,
    wp_post_id: int | None = None,
    wp_post_url: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    job.status = status
    job.error_code = error_code
    job.error_message = _sanitize_error(error_message or "") if error_message else None
    job.completed_at = now
    job.updated_at = now
    job.next_retry_at = None
    if result is not None:
        job.result_json = json.dumps(result, ensure_ascii=False)
    if wp_post_id:
        job.wp_post_id = int(wp_post_id)
    if wp_post_url:
        job.wp_post_url = wp_post_url
    db.commit()

    if job.schedule_id and status == "success":
        _sync_schedule_success(db, int(job.schedule_id), wp_post_id=job.wp_post_id, wp_post_url=job.wp_post_url)
    elif job.schedule_id and status in ("failed", "blocked"):
        _sync_schedule_failure(db, int(job.schedule_id), job.error_message or job.error_code or status)

    return {"ok": status == "success", "status": status, "job": job_to_dict(job)}


def _sync_schedule_success(
    db: Session,
    schedule_id: int,
    *,
    wp_post_id: int | None,
    wp_post_url: str | None,
) -> None:
    try:
        from app.models.content_ai_publish_schedule import ContentAIPublishSchedule
        from app.services.content_ai_entitlement import record_content_ai_usage
        from app.services.content_ai_publish_schedule_service import _to_db_utc, _utc_now
        from app.services.content_ai_project_store import update_content_ai_project_fields
        from app.services.security_audit_log import log_audit_event

        row = db.get(ContentAIPublishSchedule, int(schedule_id))
        if row is None:
            return
        now = _to_db_utc(_utc_now())
        row.status = "published"
        row.wp_post_id = int(wp_post_id or 0) or None
        row.wp_post_url = str(wp_post_url or "").strip() or None
        row.published_at = now
        row.last_error = None
        row.updated_at = now
        try:
            update_content_ai_project_fields(
                row.project_id,
                {"wp_publish_status": "published", "scheduled_at": ""},
                user_id=int(row.user_id),
            )
        except Exception:
            pass
        user = db.get(User, int(row.user_id))
        if user is not None:
            log_audit_event(
                action="publish.wordpress",
                user_id=user.id,
                resource_type="wordpress",
                resource_id=str(row.wp_post_id or ""),
                detail={"url": row.wp_post_url, "status": "published", "source": "plugin_celery"},
            )
            record_content_ai_usage(
                db,
                user,
                "wp_publish",
                quantity=1,
                metadata={"post_id": row.wp_post_id, "source": "plugin_celery", "schedule_id": row.id},
                idempotency_key=f"wp-publish-schedule:{row.id}",
            )
        db.commit()
    except Exception as exc:
        _LOG.exception("sync schedule success failed: %s", exc)


def _sync_schedule_failure(db: Session, schedule_id: int, message: str) -> None:
    try:
        from app.models.content_ai_publish_schedule import ContentAIPublishSchedule
        from app.services.content_ai_publish_schedule_service import _mark_publish_failure

        row = db.get(ContentAIPublishSchedule, int(schedule_id))
        if row is None:
            return
        exc = Exception(message)
        _mark_publish_failure(db, row, exc)
    except Exception as exc:
        _LOG.exception("sync schedule failure failed: %s", exc)


def build_plugin_payload_from_draft(
    draft: dict[str, Any],
    *,
    schedule_id: int | None = None,
    project_id: str | None = None,
    publish_mode: str = "publish",
    wp_category_id: int | None = None,
    primary_keyword: str | None = None,
) -> dict[str, Any]:
    """Map Content AI draft → SEO Helper plugin POST /posts payload."""
    title = str(draft.get("title") or "").strip()
    content = str(draft.get("content") or "").strip()
    slug = str(draft.get("slug") or "").strip()
    excerpt = str(draft.get("meta_description") or draft.get("excerpt") or "").strip()
    featured = str(draft.get("featured_image") or "").strip()
    if not featured:
        gallery = draft.get("gallery_images") or []
        if isinstance(gallery, list):
            for img in gallery:
                candidate = str(img or "").strip()
                if candidate:
                    featured = candidate
                    break

    mode = str(publish_mode or "publish").strip().lower()
    status = "draft" if mode == "draft" else "publish"
    scheduled_at = str(draft.get("scheduled_at") or "").strip()

    source = project_id or (f"schedule-{schedule_id}" if schedule_id else f"draft-{uuid.uuid4().hex[:12]}")

    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "status": status,
        "source_article_id": source,
    }
    if slug:
        payload["slug"] = slug
    if excerpt:
        payload["excerpt"] = excerpt
    if featured:
        payload["featured_image"] = featured
    if scheduled_at:
        payload["scheduled_at"] = scheduled_at
        if mode == "publish":
            payload["status"] = "future"
    if primary_keyword:
        payload["focus_keyword"] = primary_keyword

    categories: list[int] = []
    if wp_category_id and int(wp_category_id) > 0:
        categories.append(int(wp_category_id))
    cats_raw = draft.get("categories")
    if isinstance(cats_raw, list):
        for x in cats_raw:
            try:
                cid = int(x)
            except (TypeError, ValueError):
                continue
            if cid > 0 and cid not in categories:
                categories.append(cid)
    if categories:
        payload["categories"] = categories[:20]

    tags_raw = draft.get("tags") or []
    if isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        if tags:
            payload["tags"] = tags[:30]

    return payload


def get_job_for_user(db: Session, job_id: int, user: User) -> WordpressPublishJob | None:
    org_id = personal_organization_id(int(user.id))
    job = db.get(WordpressPublishJob, int(job_id))
    if job is None or int(job.organization_id) != org_id or int(job.user_id) != int(user.id):
        return None
    return job
