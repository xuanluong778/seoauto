"""CRUD and execution for Content AI bulk publish schedules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models.content_ai_publish_schedule import ContentAIPublishSchedule, SCHEDULE_STATUSES
from app.models.user import User
from app.services.content_ai_entitlement import assert_content_ai_feature
from app.services.content_ai_project_store import (
    _resolve_project_content,
    board_site_label_map,
    board_site_url_map,
    collect_written_board_summaries,
    get_content_ai_project,
    normalize_board_website_url,
    sanitize_board_website_options,
    update_content_ai_project_fields,
)
from app.services.content_ai_wp_publish_executor import publish_draft_to_wordpress
from app.services.wordpress_plugin_publish_service import (
    build_plugin_payload_from_draft,
    create_publish_job,
    get_connection_for_site,
)
from app.services.job_store import _dialect_name
from app.services.publishing_sites_store import get_site
from app.services.rbac import normalize_role
from app.services.user_scope import is_admin_role

DEFAULT_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_PUBLISH_RETRIES = 3
RETRY_BACKOFF_MINUTES = (5, 15, 60)
PUBLISHING_STALE_SECONDS = 900
PUBLISH_NOW_DEDUP_SECONDS = 90


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        # DB drivers (esp. SQLite) often strip tzinfo — treat naive as UTC.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_db_utc(dt: datetime) -> datetime:
    """
    Normalize to UTC for persistence.
    Returns aware UTC — Postgres timestamptz keeps it correctly; SQLite drivers
    typically strip tzinfo and store the UTC wall time.
    """
    aware = _as_utc_aware(dt)
    assert aware is not None
    return aware


def _utc_now_naive() -> datetime:
    return _utc_now().replace(tzinfo=None)


def _db_utc_cutoff(db: Session | None = None) -> datetime:
    """
    Cutoff for scheduled_at / updated_at comparisons.
    SQLite stores naive UTC; Postgres timestamptz needs aware UTC so the
    driver does not reinterpret naive values in the server local timezone.
    """
    if db is not None and _dialect_name(db) != "sqlite":
        return _utc_now()
    return _utc_now_naive()


def _next_retry_at(retry_count: int) -> datetime:
    idx = max(0, min(int(retry_count) - 1, len(RETRY_BACKOFF_MINUTES) - 1))
    minutes = RETRY_BACKOFF_MINUTES[idx]
    return _to_db_utc(_utc_now() + timedelta(minutes=minutes))


def _sanitize_error_message(exc: BaseException) -> str:
    """Strip secrets from error text before persisting or logging."""
    import re

    raw = str(exc)
    if hasattr(exc, "detail"):
        d = getattr(exc, "detail", None)
        if isinstance(d, str):
            raw = d
        elif isinstance(d, dict) and d.get("message"):
            raw = str(d.get("message"))
    raw = re.sub(r"(?i)(app[_-]?password|password|token|authorization)\s*[:=]\s*\S+", r"\1=***", raw)
    raw = re.sub(r"Bearer\s+\S+", "Bearer ***", raw, flags=re.I)
    return raw[:2000]


def parse_scheduled_at(value: str) -> datetime:
    """Parse client datetime; naive values use Asia/Ho_Chi_Minh. Returns UTC-aware."""
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Thiếu scheduled_at.")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="scheduled_at không hợp lệ.") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=DEFAULT_TZ)
    return dt.astimezone(timezone.utc)


def _schedule_to_dict(row: ContentAIPublishSchedule) -> dict[str, Any]:
    sched = _as_utc_aware(row.scheduled_at)
    sched_local = ""
    if sched is not None:
        sched_local = sched.astimezone(DEFAULT_TZ).isoformat()
    return {
        "id": row.id,
        "user_id": row.user_id,
        "project_id": row.project_id,
        "bulk_job_id": row.bulk_job_id,
        "keyword": row.keyword,
        "title": row.title,
        "wp_site_id": row.wp_site_id,
        "wp_category_id": row.wp_category_id,
        "scheduled_at": sched_local,
        "scheduled_at_utc": sched.isoformat() if sched else None,
        "status": row.status,
        "wp_post_id": row.wp_post_id,
        "wp_post_url": row.wp_post_url,
        "retry_count": row.retry_count,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


def get_schedule_row(
    db: Session,
    schedule_id: int,
    user: User,
    *,
    admin_all: bool = False,
) -> ContentAIPublishSchedule | None:
    q = select(ContentAIPublishSchedule).where(ContentAIPublishSchedule.id == int(schedule_id))
    if not (admin_all and is_admin_role(normalize_role(user.role))):
        q = q.where(ContentAIPublishSchedule.user_id == int(user.id))
    return db.execute(q).scalar_one_or_none()


def list_schedules(
    db: Session,
    user: User,
    *,
    bulk_job_id: str | None = None,
    project_id: str | None = None,
    project_ids: list[str] | None = None,
    status: str | None = None,
    limit: int = 200,
    admin_all: bool = False,
) -> list[dict[str, Any]]:
    q = select(ContentAIPublishSchedule).order_by(ContentAIPublishSchedule.id.desc())
    if not (admin_all and is_admin_role(normalize_role(user.role))):
        q = q.where(ContentAIPublishSchedule.user_id == int(user.id))
    if bulk_job_id:
        q = q.where(ContentAIPublishSchedule.bulk_job_id == str(bulk_job_id).strip())
    if project_id:
        q = q.where(ContentAIPublishSchedule.project_id == str(project_id).strip())
    if project_ids:
        ids = [str(x).strip() for x in project_ids if str(x).strip()]
        if ids:
            q = q.where(ContentAIPublishSchedule.project_id.in_(ids))
    if status:
        st = str(status).strip().lower()
        if st in SCHEDULE_STATUSES:
            q = q.where(ContentAIPublishSchedule.status == st)
    q = q.limit(max(1, min(limit, 500)))
    rows = db.execute(q).scalars().all()
    return [_schedule_to_dict(r) for r in rows]


def _resolve_wp_credentials(
    *,
    user_id: int,
    wp_site_id: str | None,
    wp_url: str | None = None,
    username: str | None = None,
    app_password: str | None = None,
) -> tuple[str, str, str, str | None]:
    sid = str(wp_site_id or "").strip()
    if sid:
        from app.services.wordpress_connection import resolve_wordpress_connection

        cred = resolve_wordpress_connection(user_id=user_id, site_id=sid, site_url=wp_url)
        return cred["url"], cred["username"], cred["app_password"], cred["site_id"]
    url = str(wp_url or "").strip()
    user = str(username or "").strip()
    pwd = str(app_password or "").strip()
    if not url or not user or not pwd:
        raise HTTPException(
            status_code=400,
            detail="Cần wp_site_id hoặc đủ wp_url + username + app_password.",
        )
    return url, user, pwd, None


def _project_snapshot(
    project_id: str,
    user_id: int,
    *,
    wp_category_id: int | None = None,
) -> dict[str, Any]:
    """Lightweight snapshot for schedule/publish rows — no draft rebuild / network I/O."""
    project = get_content_ai_project(project_id, user_id=user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy project.")
    content = _resolve_project_content(project)
    if not str(content or "").strip():
        raise HTTPException(status_code=400, detail="Project chưa có nội dung bài viết.")
    title = str(project.get("custom_title") or project.get("title") or "").strip()
    keyword = str(project.get("primary_keyword") or "").strip()
    cat_id = wp_category_id
    if cat_id is None:
        try:
            cat_id = int(project.get("wp_category_id") or 0) or None
        except (TypeError, ValueError):
            cat_id = None
    return {
        "project": project,
        "keyword": keyword,
        "title": title or keyword,
        "content_html": content,
        "wp_category_id": cat_id,
    }


def _cancel_active_for_project(db: Session, user_id: int, project_id: str) -> None:
    rows = db.execute(
        select(ContentAIPublishSchedule).where(
            ContentAIPublishSchedule.user_id == user_id,
            ContentAIPublishSchedule.project_id == project_id,
            ContentAIPublishSchedule.status.in_(("draft", "scheduled")),
        )
    ).scalars().all()
    for row in rows:
        row.status = "cancelled"
        row.updated_at = datetime.now(timezone.utc)


def _find_matching_scheduled_row(
    db: Session,
    user_id: int,
    project_id: str,
    scheduled_at: datetime,
) -> ContentAIPublishSchedule | None:
    target_ts = scheduled_at.astimezone(timezone.utc).timestamp()
    rows = db.execute(
        select(ContentAIPublishSchedule).where(
            ContentAIPublishSchedule.user_id == int(user_id),
            ContentAIPublishSchedule.project_id == str(project_id).strip(),
            ContentAIPublishSchedule.status == "scheduled",
        )
    ).scalars().all()
    for row in rows:
        when = row.scheduled_at
        if when is None:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if abs(when.astimezone(timezone.utc).timestamp() - target_ts) < 1.0:
            return row
    return None


def _resolve_publish_now_duplicate(
    db: Session,
    user_id: int,
    project_id: str,
) -> ContentAIPublishSchedule | None:
    """Block double-click publish: return recent published row or None."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=PUBLISH_NOW_DEDUP_SECONDS)
    rows = db.execute(
        select(ContentAIPublishSchedule)
        .where(
            ContentAIPublishSchedule.user_id == int(user_id),
            ContentAIPublishSchedule.project_id == str(project_id).strip(),
        )
        .order_by(ContentAIPublishSchedule.id.desc())
        .limit(8)
    ).scalars().all()
    for row in rows:
        if row.status == "publishing":
            raise HTTPException(status_code=409, detail="Bài đang được đăng.")
        if (
            row.status == "published"
            and row.wp_post_id
            and int(row.wp_post_id) > 0
            and row.published_at is not None
        ):
            pub_at = row.published_at
            if pub_at.tzinfo is None:
                pub_at = pub_at.replace(tzinfo=timezone.utc)
            if pub_at >= cutoff:
                return row
    return None


def create_schedule(
    db: Session,
    user: User,
    *,
    project_id: str,
    scheduled_at: str,
    wp_site_id: str | None = None,
    wp_url: str | None = None,
    username: str | None = None,
    app_password: str | None = None,
    wp_category_id: int | None = None,
    bulk_job_id: str | None = None,
    seo_plugin: str = "auto",
) -> dict[str, Any]:
    when = parse_scheduled_at(scheduled_at)
    now = _utc_now()
    if when <= now:
        raise HTTPException(status_code=400, detail="scheduled_at phải ở tương lai.")
    existing = _find_matching_scheduled_row(db, user.id, project_id, when)
    if existing is not None:
        _schedule_due_publish(int(existing.id), when)
        return _schedule_to_dict(existing)
    snap = _project_snapshot(project_id, user.id, wp_category_id=wp_category_id)
    # Validate site ownership quickly; credentials are resolved again at publish time.
    _, _, _, site_id = _resolve_wp_credentials(
        user_id=user.id,
        wp_site_id=wp_site_id,
        wp_url=wp_url,
        username=username,
        app_password=app_password,
    )
    if site_id:
        wp_site_id = site_id
    _cancel_active_for_project(db, user.id, project_id)
    row = ContentAIPublishSchedule(
        user_id=user.id,
        project_id=project_id,
        bulk_job_id=str(bulk_job_id or "").strip() or None,
        keyword=snap["keyword"],
        title=snap["title"],
        content_html=snap["content_html"],
        wp_site_id=wp_site_id,
        wp_category_id=snap["wp_category_id"],
        scheduled_at=_to_db_utc(when),
        status="scheduled",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    # Update project metadata after commit so slow JSON rewrite never blocks the API response.
    try:
        update_content_ai_project_fields(
            project_id,
            {"scheduled_at": when.astimezone(DEFAULT_TZ).strftime("%Y-%m-%dT%H:%M")},
            user_id=user.id,
        )
    except Exception:
        pass
    # Ensure this row is published when due even if the polling worker is delayed.
    _schedule_due_publish(int(row.id), when)
    return _schedule_to_dict(row)


def _schedule_due_publish(schedule_id: int, when_utc: datetime) -> None:
    """Daemon timer: publish this schedule when its due time arrives."""
    from app.services.wp_publish_scheduler_rollout import use_celery_wp_scheduler

    if use_celery_wp_scheduler():
        return

    import logging
    import threading
    import time

    log = logging.getLogger("content_ai.publish_worker")
    due = _as_utc_aware(when_utc) or _utc_now()

    def _run() -> None:
        try:
            delay = (due - _utc_now()).total_seconds()
            if delay > 0:
                # Cap sleep to 24h; long schedules still rely on the polling worker.
                time.sleep(min(delay + 0.5, 86400.0))
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                row = db.get(ContentAIPublishSchedule, int(schedule_id))
                if not row or str(row.status or "") != "scheduled":
                    return
                row_due = _as_utc_aware(row.scheduled_at)
                if row_due and row_due > _utc_now() + timedelta(seconds=2):
                    return
                row.status = "publishing"
                row.updated_at = _to_db_utc(_utc_now())
                db.commit()
                db.refresh(row)
                outcome = _publish_claimed_row(db, row, force_now=True, raise_on_error=False)
                if outcome.get("ok"):
                    log.info("timer published schedule_id=%s", schedule_id)
                else:
                    log.warning(
                        "timer publish failed schedule_id=%s err=%s",
                        schedule_id,
                        outcome.get("error"),
                    )
            finally:
                db.close()
        except Exception:
            log.exception("timer publish crashed schedule_id=%s", schedule_id)

    threading.Thread(
        target=_run,
        name=f"content-ai-publish-at-{schedule_id}",
        daemon=True,
    ).start()


def create_schedule_batch(
    db: Session,
    user: User,
    items: list[dict[str, Any]],
    *,
    scheduled_at: str | None = None,
    wp_site_id: str | None = None,
    wp_url: str | None = None,
    username: str | None = None,
    app_password: str | None = None,
    bulk_job_id: str | None = None,
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item in items:
        pid = str(item.get("project_id") or "").strip()
        if not pid:
            errors.append({"project_id": "", "error": "Thiếu project_id"})
            continue
        when = str(item.get("scheduled_at") or scheduled_at or "").strip()
        if not when:
            errors.append({"project_id": pid, "error": "Thiếu scheduled_at"})
            continue
        try:
            row = create_schedule(
                db,
                user,
                project_id=pid,
                scheduled_at=when,
                wp_site_id=str(item.get("wp_site_id") or wp_site_id or "").strip() or None,
                wp_url=wp_url,
                username=username,
                app_password=app_password,
                wp_category_id=item.get("wp_category_id"),
                bulk_job_id=str(item.get("bulk_job_id") or bulk_job_id or "").strip() or None,
            )
            created.append(row)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            errors.append({"project_id": pid, "error": detail})
    return {"ok": True, "created": created, "errors": errors, "count": len(created)}


def cancel_schedules(
    db: Session,
    user: User,
    *,
    schedule_ids: list[int] | None = None,
    project_ids: list[str] | None = None,
) -> dict[str, Any]:
    ids = [int(x) for x in (schedule_ids or []) if x]
    pids = [str(x).strip() for x in (project_ids or []) if str(x).strip()]
    if not ids and not pids:
        raise HTTPException(status_code=400, detail="Cần schedule_ids hoặc project_ids.")
    q = select(ContentAIPublishSchedule).where(
        ContentAIPublishSchedule.user_id == int(user.id),
        ContentAIPublishSchedule.status.in_(("draft", "scheduled")),
    )
    if ids and pids:
        q = q.where(
            or_(
                ContentAIPublishSchedule.id.in_(ids),
                ContentAIPublishSchedule.project_id.in_(pids),
            )
        )
    elif ids:
        q = q.where(ContentAIPublishSchedule.id.in_(ids))
    else:
        q = q.where(ContentAIPublishSchedule.project_id.in_(pids))
    rows = db.execute(q).scalars().all()
    for row in rows:
        row.status = "cancelled"
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "cancelled": len(rows)}


def update_schedule_time(
    db: Session,
    user: User,
    schedule_id: int,
    scheduled_at: str,
) -> dict[str, Any]:
    row = get_schedule_row(db, schedule_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch đăng.")
    if row.status not in ("draft", "scheduled"):
        raise HTTPException(status_code=400, detail="Chỉ sửa lịch ở trạng thái scheduled.")
    when = parse_scheduled_at(scheduled_at)
    now = datetime.now(timezone.utc)
    if when <= now:
        raise HTTPException(status_code=400, detail="scheduled_at phải ở tương lai.")
    row.scheduled_at = when
    row.status = "scheduled"
    row.updated_at = now
    update_content_ai_project_fields(
        row.project_id,
        {"scheduled_at": when.astimezone(DEFAULT_TZ).strftime("%Y-%m-%dT%H:%M")},
        user_id=user.id,
    )
    db.commit()
    db.refresh(row)
    return _schedule_to_dict(row)


def execute_schedule_row(
    db: Session,
    row: ContentAIPublishSchedule,
    *,
    user: User | None = None,
    request: Any | None = None,
    publish_mode: str = "publish",
    force_now: bool = False,
) -> dict[str, Any]:
    """Publish one schedule row to WordPress (API / manual)."""
    if row.status in ("published", "cancelled"):
        return _schedule_to_dict(row)
    if row.status == "publishing":
        raise HTTPException(status_code=409, detail="Bài đang được đăng.")
    if row.status != "scheduled":
        raise HTTPException(status_code=400, detail=f"Trạng thái không hợp lệ: {row.status}")

    row.status = "publishing"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    pub_user = user if user is not None else db.get(User, int(row.user_id))
    outcome = _publish_claimed_row(
        db,
        row,
        user=pub_user,
        request=request,
        publish_mode=publish_mode,
        force_now=force_now,
        raise_on_error=True,
    )
    if outcome.get("ok"):
        db.refresh(row)
        result = _schedule_to_dict(row)
        if outcome.get("async"):
            result["async"] = True
            result["job_id"] = outcome.get("job_id")
            result["request_id"] = outcome.get("request_id")
            return result
        return {**result, "publish_result": outcome.get("publish_result")}
    raise HTTPException(status_code=502, detail=outcome.get("error") or "Đăng bài thất bại.")


def _build_draft_payload_for_row(row: ContentAIPublishSchedule, *, force_now: bool) -> dict[str, Any]:
    uid = int(row.user_id)
    draft_payload: dict[str, Any] = {
        "title": row.title,
        "content": row.content_html,
        "meta_description": "",
        "categories": [row.wp_category_id] if row.wp_category_id else [],
    }
    project = get_content_ai_project(row.project_id, user_id=uid)
    if project:
        meta = str(project.get("custom_description") or project.get("meta_description") or "").strip()
        if meta:
            draft_payload["meta_description"] = meta
        draft_out = project.get("draft_output") if isinstance(project.get("draft_output"), dict) else {}
        fi = str(project.get("featured_image") or draft_out.get("featured_image") or "").strip()
        if fi:
            draft_payload["featured_image"] = fi
        gal = project.get("gallery_images") or draft_out.get("gallery_images")
        if isinstance(gal, list) and gal:
            draft_payload["gallery_images"] = gal

    if row.scheduled_at and not force_now:
        sched = row.scheduled_at
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
        if sched > datetime.now(timezone.utc) + timedelta(seconds=5):
            draft_payload["scheduled_at"] = sched.astimezone(DEFAULT_TZ).strftime("%Y-%m-%dT%H:%M")
    return draft_payload


def _mark_publish_failure(db: Session, row: ContentAIPublishSchedule, exc: BaseException) -> dict[str, Any]:
    err = _sanitize_error_message(exc)
    row.retry_count = int(row.retry_count or 0) + 1
    row.last_error = err
    now = _to_db_utc(_utc_now())
    if row.retry_count >= MAX_PUBLISH_RETRIES:
        row.status = "failed"
    else:
        row.status = "scheduled"
        row.scheduled_at = _next_retry_at(row.retry_count)
    row.updated_at = now
    db.commit()
    return {
        "id": row.id,
        "ok": False,
        "status": row.status,
        "retry_count": row.retry_count,
        "error": err[:500],
    }


def _publish_claimed_row(
    db: Session,
    row: ContentAIPublishSchedule,
    *,
    user: User | None = None,
    request: Any | None = None,
    publish_mode: str = "publish",
    force_now: bool = False,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """Publish a row already in status=publishing. Idempotent if wp_post_id exists."""
    if row.wp_post_id and int(row.wp_post_id) > 0:
        now = _to_db_utc(_utc_now())
        row.status = "published"
        row.published_at = row.published_at or now
        row.updated_at = now
        db.commit()
        return {"id": row.id, "ok": True, "status": "published", "skipped": True}

    uid = int(row.user_id)
    try:
        wp_url, wp_user, wp_pwd, _ = _resolve_wp_credentials(user_id=uid, wp_site_id=row.wp_site_id)
    except HTTPException as exc:
        if raise_on_error:
            raise
        return _mark_publish_failure(db, row, exc)

    draft_payload = _build_draft_payload_for_row(row, force_now=force_now)
    pub_user = user
    if pub_user is None:
        try:
            pub_user = db.execute(select(User).where(User.id == uid).limit(1)).scalar_one_or_none()
        except Exception:
            pub_user = None

    plugin_connection = get_connection_for_site(
        db,
        user_id=uid,
        wp_site_id=row.wp_site_id,
        site_url=wp_url,
    )
    if plugin_connection is not None and str(plugin_connection.status or "") == "active":
        if pub_user is None:
            if raise_on_error:
                raise HTTPException(status_code=404, detail="User not found for publish job.")
            return _mark_publish_failure(db, row, Exception("User not found for publish job."))
        try:
            assert_content_ai_feature(db, pub_user, "wp_publish", quantity=1)
            plugin_payload = build_plugin_payload_from_draft(
                draft_payload,
                schedule_id=int(row.id),
                project_id=str(row.project_id or ""),
                publish_mode=publish_mode,
                wp_category_id=int(row.wp_category_id or 0) or None,
                primary_keyword=row.keyword,
            )
            job = create_publish_job(
                db,
                user=pub_user,
                payload=plugin_payload,
                wp_site_id=row.wp_site_id,
                site_url=wp_url,
                schedule_id=int(row.id),
                request_id=f"schedule-{row.id}",
                source_article_id=str(row.project_id or f"schedule-{row.id}"),
                enqueue=True,
            )
            if job.status == "blocked":
                if raise_on_error:
                    raise HTTPException(status_code=403, detail=job.error_message or job.error_code)
                return _mark_publish_failure(db, row, Exception(job.error_message or job.error_code or "blocked"))
            return {
                "id": row.id,
                "ok": True,
                "status": "publishing",
                "async": True,
                "job_id": job.id,
                "request_id": job.request_id,
                "job_status": job.status,
            }
        except HTTPException:
            raise
        except Exception as exc:
            outcome = _mark_publish_failure(db, row, exc)
            if raise_on_error:
                raise
            return outcome

    try:
        if pub_user is not None:
            assert_content_ai_feature(db, pub_user, "wp_publish", quantity=1)
        result = publish_draft_to_wordpress(
            db=db,
            user=pub_user,
            wp_url=wp_url,
            username=wp_user,
            app_password=wp_pwd,
            draft_payload=draft_payload,
            primary_keyword=row.keyword,
            publish_mode=publish_mode,
            request=request,
            record_usage=bool(pub_user is not None),
            usage_idempotency_key=f"wp-publish-schedule:{row.id}",
        )
        now = _to_db_utc(_utc_now())
        row.status = "published"
        row.wp_post_id = int(result.get("post_id") or 0) or None
        row.wp_post_url = str(result.get("link") or "").strip() or None
        row.published_at = now
        row.last_error = None
        row.updated_at = now
        try:
            update_content_ai_project_fields(
                row.project_id,
                {"wp_publish_status": "published", "scheduled_at": ""},
                user_id=uid,
            )
        except Exception:
            pass
        db.commit()
        return {
            "id": row.id,
            "ok": True,
            "status": "published",
            "wp_post_id": row.wp_post_id,
            "wp_post_url": row.wp_post_url,
            "publish_result": result,
        }
    except Exception as exc:
        outcome = _mark_publish_failure(db, row, exc)
        if raise_on_error:
            raise
        return outcome


def claim_next_due_schedule(db: Session) -> ContentAIPublishSchedule | None:
    """
    Atomically claim the oldest due scheduled row (status scheduled -> publishing).
    Safe for multiple worker processes (SKIP LOCKED / BEGIN IMMEDIATE).
    """
    import logging

    log = logging.getLogger("content_ai.publish_worker")
    dialect = _dialect_name(db)
    try:
        if dialect == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        # SQLite: naive UTC. Postgres timestamptz: aware UTC (never naive local).
        now = _db_utc_cutoff(db)
        stmt = (
            select(ContentAIPublishSchedule)
            .where(
                ContentAIPublishSchedule.status == "scheduled",
                ContentAIPublishSchedule.scheduled_at.is_not(None),
                ContentAIPublishSchedule.scheduled_at <= now,
            )
            .order_by(ContentAIPublishSchedule.scheduled_at.asc())
            .limit(1)
        )
        if dialect != "sqlite":
            stmt = stmt.with_for_update(skip_locked=True)
        row = db.execute(stmt).scalar_one_or_none()
        if not row:
            db.rollback()
            return None
        row.status = "publishing"
        row.updated_at = now
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        log.exception("claim_next_due_schedule failed")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def reclaim_stale_publishing(db: Session, *, stale_seconds: int | None = None) -> int:
    """Reset rows stuck in publishing (worker crash) for retry or failed."""
    from app.models.wordpress_plugin import WordpressPublishJob

    secs = int(stale_seconds if stale_seconds is not None else PUBLISHING_STALE_SECONDS)
    now = _db_utc_cutoff(db)
    cutoff = now - timedelta(seconds=max(60, secs))
    rows = list(
        db.execute(
            select(ContentAIPublishSchedule).where(
                ContentAIPublishSchedule.status == "publishing",
                ContentAIPublishSchedule.updated_at < cutoff,
            )
        ).scalars().all()
    )
    if not rows:
        return 0
    reclaimed = 0
    for row in rows:
        active_job = db.execute(
            select(WordpressPublishJob.id).where(
                WordpressPublishJob.schedule_id == int(row.id),
                WordpressPublishJob.status.in_(("queued", "running", "retrying")),
            ).limit(1)
        ).scalar_one_or_none()
        if active_job is not None:
            continue
        if row.wp_post_id and int(row.wp_post_id) > 0:
            row.status = "published"
            row.published_at = row.published_at or now
        elif int(row.retry_count or 0) >= MAX_PUBLISH_RETRIES:
            row.status = "failed"
            row.last_error = (row.last_error or "Worker timeout")[:2000]
        else:
            row.status = "scheduled"
            row.scheduled_at = _next_retry_at(int(row.retry_count or 0) + 1)
            row.retry_count = int(row.retry_count or 0) + 1
            row.last_error = ((row.last_error or "") + " [stale publishing reclaimed]")[:2000]
        row.updated_at = now
        reclaimed += 1
    db.commit()
    return reclaimed


def publish_now_one(
    db: Session,
    user: User,
    *,
    project_id: str,
    wp_site_id: str | None = None,
    wp_url: str | None = None,
    username: str | None = None,
    app_password: str | None = None,
    wp_category_id: int | None = None,
    bulk_job_id: str | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    assert_content_ai_feature(db, user, "wp_publish", quantity=1)
    dup = _resolve_publish_now_duplicate(db, user.id, project_id)
    if dup is not None:
        return {**_schedule_to_dict(dup), "idempotent": True}
    snap = _project_snapshot(project_id, user.id, wp_category_id=wp_category_id)
    wp_url, wp_user, wp_pwd, site_id = _resolve_wp_credentials(
        user_id=user.id,
        wp_site_id=wp_site_id,
        wp_url=wp_url,
        username=username,
        app_password=app_password,
    )
    _cancel_active_for_project(db, user.id, project_id)
    row = ContentAIPublishSchedule(
        user_id=user.id,
        project_id=project_id,
        bulk_job_id=str(bulk_job_id or "").strip() or None,
        keyword=snap["keyword"],
        title=snap["title"],
        content_html=snap["content_html"],
        wp_site_id=site_id or wp_site_id,
        wp_category_id=snap["wp_category_id"],
        scheduled_at=_to_db_utc(_utc_now()),
        status="scheduled",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return execute_schedule_row(db, row, user=user, request=request, force_now=True)


def publish_now_batch(
    db: Session,
    user: User,
    project_ids: list[str],
    *,
    wp_site_id: str | None = None,
    wp_url: str | None = None,
    username: str | None = None,
    app_password: str | None = None,
    bulk_job_id: str | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    published: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for pid in project_ids:
        pid = str(pid or "").strip()
        if not pid:
            continue
        try:
            published.append(
                publish_now_one(
                    db,
                    user,
                    project_id=pid,
                    wp_site_id=wp_site_id,
                    wp_url=wp_url,
                    username=username,
                    app_password=app_password,
                    bulk_job_id=bulk_job_id,
                    request=request,
                )
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            errors.append({"project_id": pid, "error": detail})
        except Exception as exc:
            errors.append({"project_id": pid, "error": str(exc)[:500]})
    return {"ok": True, "published": published, "errors": errors, "count": len(published)}


def list_due_schedules(db: Session, *, limit: int = 20) -> list[ContentAIPublishSchedule]:
    now = _db_utc_cutoff(db)
    q = (
        select(ContentAIPublishSchedule)
        .where(
            ContentAIPublishSchedule.status == "scheduled",
            ContentAIPublishSchedule.scheduled_at.is_not(None),
            ContentAIPublishSchedule.scheduled_at <= now,
        )
        .order_by(ContentAIPublishSchedule.scheduled_at.asc())
        .limit(max(1, min(limit, 100)))
    )
    return list(db.execute(q).scalars().all())


def run_publish_worker_tick(db: Session, *, limit: int = 10, stale_seconds: int | None = None) -> dict[str, Any]:
    """One worker iteration: reclaim stale locks, claim due rows, publish."""
    reclaimed = reclaim_stale_publishing(db, stale_seconds=stale_seconds)
    processed: list[dict[str, Any]] = []
    batch = max(1, min(int(limit), 100))
    for _ in range(batch):
        row = claim_next_due_schedule(db)
        if not row:
            break
        outcome = _publish_claimed_row(db, row, force_now=True, raise_on_error=False)
        processed.append(outcome)
    return {
        "ok": True,
        "at": _utc_now().isoformat(),
        "reclaimed": reclaimed,
        "processed": processed,
        "count": len(processed),
    }


def arm_due_schedule_timers(db: Session, *, limit: int = 100) -> int:
    """Arm one-shot timers for currently due scheduled rows (startup catch-up)."""
    due = list_due_schedules(db, limit=limit)
    for row in due:
        when = _as_utc_aware(row.scheduled_at)
        if when is not None:
            _schedule_due_publish(int(row.id), when)
    return len(due)


def run_due_schedules(db: Session, *, limit: int = 20) -> dict[str, Any]:
    """Backward-compatible alias used by older scheduler entrypoints."""
    return run_publish_worker_tick(db, limit=limit)


_BOARD_STATUSES = frozenset({"unscheduled", "scheduled", "publishing", "published", "failed"})


def _schedule_board_status(project: dict[str, Any] | None, schedule: dict[str, Any] | None) -> str:
    if schedule:
        st = str(schedule.get("status") or "").strip().lower()
        if st in ("scheduled", "publishing", "published", "failed"):
            return st
        # draft / cancelled → treat as not on the board calendar
    if project:
        pst = str(project.get("status") or "").strip().lower()
        if pst == "published" or str(project.get("wp_post_url") or "").strip():
            return "published"
    return "unscheduled"


def _board_schedule_payload(schedule: dict[str, Any] | None) -> dict[str, Any] | None:
    if not schedule:
        return None
    out = dict(schedule)
    out.setdefault("publish_at", schedule.get("scheduled_at"))
    out.setdefault("published_url", schedule.get("wp_post_url"))
    return out


def _resolve_website_meta(
    *,
    user_id: int,
    project: dict[str, Any] | None,
    schedule: dict[str, Any] | None,
    site_cache: dict[str, dict[str, Any] | None],
    site_labels: dict[str, str] | None = None,
    site_urls: dict[str, str] | None = None,
) -> tuple[str, str]:
    site_id = ""
    if schedule:
        site_id = str(schedule.get("wp_site_id") or "").strip()
    if not site_id and project:
        site_id = str(project.get("wp_site_id") or "").strip()
    labels = site_labels or {}
    urls = site_urls or {}
    if site_id:
        url = urls.get(site_id) or ""
        if not url:
            if site_id not in site_cache:
                site_cache[site_id] = get_site(site_id, user_id=user_id, reveal_password=False)
            site = site_cache[site_id]
            if site:
                url = normalize_board_website_url(site.get("url")) or str(site.get("url") or "").strip()
        url = normalize_board_website_url(url) or url
        if url:
            return site_id, url
        # Fall back only when no usable URL exists (should be rare).
        if labels.get(site_id):
            return site_id, labels[site_id]
    target = str((project or {}).get("target_website") or "").strip()
    if target:
        norm = normalize_board_website_url(target) or target
        return target, norm
    return site_id, site_id


def build_bulk_publish_board(
    db: Session,
    user: User,
    *,
    project_ids: list[str] | None = None,
    bulk_job_id: str | None = None,
    status: str | None = None,
    q: str | None = None,
    website: str | None = None,
    category_id: str | None = None,
    limit: int = 120,
    include_sites: bool = True,
) -> dict[str, Any]:
    """Build schedule-board rows for Content AI bulk publish UI."""
    uid = int(user.id)
    website_f = str(website or "").strip()
    cap = max(1, min(int(limit or 120), 500))
    site_labels = board_site_label_map(uid)
    site_urls = board_site_url_map(uid)

    summaries, site_options = collect_written_board_summaries(
        user_id=uid,
        website=website_f or None,
        limit=cap,
        collect_sites=include_sites,
        site_labels=site_labels,
    )
    ids = [str(s.get("id") or "").strip() for s in summaries if str(s.get("id") or "").strip()]

    status_f = str(status or "").strip().lower()
    if status_f and status_f not in _BOARD_STATUSES:
        status_f = ""
    q_norm = str(q or "").strip().lower()
    cat_f = str(category_id or "").strip()

    sched_rows = list_schedules(db, user, project_ids=ids, limit=max(len(ids), 1)) if ids else []
    by_project: dict[str, dict[str, Any]] = {}
    for s in sched_rows:
        pid = str(s.get("project_id") or "").strip()
        if not pid:
            continue
        if pid not in by_project:
            by_project[pid] = s
        else:
            cur = by_project[pid]
            if str(cur.get("status") or "") == "cancelled" and str(s.get("status") or "") != "cancelled":
                by_project[pid] = s

    site_cache: dict[str, dict[str, Any] | None] = {}
    items: list[dict[str, Any]] = []
    stats = {
        "total": 0,
        "unscheduled": 0,
        "scheduled": 0,
        "publishing": 0,
        "published": 0,
        "failed": 0,
    }

    for project in summaries:
        pid = str(project.get("id") or "").strip()
        if not pid:
            continue
        schedule = by_project.get(pid)
        if schedule and str(schedule.get("status") or "").lower() == "cancelled":
            schedule = None
        board_st = _schedule_board_status(project, schedule)

        if status_f and board_st != status_f:
            continue

        keyword = str(project.get("primary_keyword") or (schedule or {}).get("keyword") or "").strip()
        title = str(
            project.get("custom_title")
            or project.get("title")
            or (schedule or {}).get("title")
            or ""
        ).strip()
        if q_norm and q_norm not in keyword.lower() and q_norm not in title.lower():
            continue

        website_id, website_label = _resolve_website_meta(
            user_id=uid,
            project=project,
            schedule=schedule,
            site_cache=site_cache,
            site_labels=site_labels,
            site_urls=site_urls,
        )
        website_url = normalize_board_website_url(website_label) or normalize_board_website_url(
            project.get("target_website") if project else ""
        )
        cat_id = None
        if schedule and schedule.get("wp_category_id") is not None:
            try:
                cat_id = int(schedule["wp_category_id"])
            except (TypeError, ValueError):
                cat_id = None
        if cat_id is None and project:
            try:
                cat_id = int(project.get("wp_category_id") or 0) or None
            except (TypeError, ValueError):
                cat_id = None
        cat_label = str(project.get("wp_category_name") or "").strip()
        if not cat_label and cat_id is not None:
            cat_label = str(cat_id)

        if cat_f:
            cat_key = str(cat_id if cat_id is not None else cat_label or "").strip()
            if cat_key != cat_f:
                continue

        stats[board_st] = int(stats.get(board_st) or 0) + 1
        stats["total"] += 1

        draft_out = project.get("draft_output") if isinstance(project.get("draft_output"), dict) else {}
        featured = str(project.get("featured_image") or (draft_out or {}).get("featured_image") or "").strip()

        items.append(
            {
                "project_id": pid,
                "board_status": board_st,
                "keyword": keyword,
                "title": title,
                "website_id": website_id,
                "website_label": website_url or website_label or website_id or "",
                "website_url": website_url,
                "category_id": cat_id,
                "category_label": cat_label,
                "featured_image": featured,
                "slug": str(project.get("slug") or "").strip(),
                "schedule": _board_schedule_payload(schedule),
            }
        )

    out: dict[str, Any] = {"ok": True, "items": items, "stats": stats, "count": len(items)}
    if include_sites:
        out["sites"] = sanitize_board_website_options(site_options)
    return out


def retry_failed_schedule(
    db: Session,
    user: User,
    schedule_id: int,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Re-queue a failed schedule and publish immediately."""
    row = get_schedule_row(db, int(schedule_id), user)
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch đăng.")
    if row.status == "published":
        return _schedule_to_dict(row)
    if row.status == "publishing":
        raise HTTPException(status_code=409, detail="Bài đang được đăng.")
    if row.status not in ("failed", "scheduled"):
        raise HTTPException(status_code=400, detail=f"Trạng thái không hợp lệ để thử lại: {row.status}")
    assert_content_ai_feature(db, user, "wp_publish", quantity=1)
    row.status = "scheduled"
    row.scheduled_at = datetime.now(timezone.utc)
    row.last_error = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return execute_schedule_row(db, row, user=user, request=request, force_now=True)
