"""Google Map SEO — quản lý bài đăng Google Map."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret
from app.models.google_map_gbp import GbpLocation, GbpOAuthConnection, GbpPost
from app.services.google_map_gbp_api import credentials_from_tokens
from app.services.google_map_gbp_post_ai import (
    CTA_LABELS,
    CTA_TYPES,
    POST_TYPE_LABELS,
    POST_TYPES,
    generate_map_post,
)
from app.services.google_map_gbp_posts_api import create_local_post
from app.services.google_map_gbp_profile_service import _resolve_location

_LOG = logging.getLogger("google_map_gbp.posts")

POST_STATUSES = frozenset({"draft", "scheduled", "published", "error"})
SCHEDULE_MODES = frozenset({"once", "weekly", "monthly"})

STATUS_LABELS = {
    "draft": "Nháp",
    "scheduled": "Đã lên lịch",
    "published": "Đã đăng",
    "error": "Lỗi",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="scheduled_at không hợp lệ (ISO 8601).") from None


def _load_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def post_to_dict(row: GbpPost) -> dict[str, Any]:
    suggestions = _load_json(row.image_suggestions_json)
    if not isinstance(suggestions, list):
        suggestions = []
    inp = _load_json(row.input_json)
    return {
        "id": row.id,
        "location_key": row.location_key,
        "post_type": row.post_type,
        "post_type_label": POST_TYPE_LABELS.get(row.post_type, row.post_type),
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "title": row.title or "",
        "content": row.content or "",
        "cta_type": row.cta_type or "",
        "cta_label": row.cta_label or "",
        "image_suggestions": suggestions,
        "input": inp,
        "schedule_mode": row.schedule_mode,
        "scheduled_at": _iso(row.scheduled_at),
        "published_at": _iso(row.published_at),
        "google_post_name": row.google_post_name,
        "last_error": row.last_error,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _can_publish_gbp(db: Session, gbp_row: GbpLocation | None) -> bool:
    if gbp_row is None:
        return False
    conn = db.get(GbpOAuthConnection, gbp_row.connection_id)
    return bool(conn and conn.status == "active")


def list_posts(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    status_filter: str | None = None,
) -> dict[str, Any]:
    gbp_row, loc_ui = _resolve_location(db, user_id, location_key)
    q = select(GbpPost).where(
        GbpPost.user_id == user_id,
        GbpPost.location_key == location_key,
    )
    if status_filter:
        sf = str(status_filter).strip().lower()
        if sf not in POST_STATUSES:
            raise HTTPException(status_code=400, detail="status không hợp lệ.")
        q = q.where(GbpPost.status == sf)
    rows = db.execute(q.order_by(GbpPost.updated_at.desc())).scalars().all()
    return {
        "location_key": location_key,
        "can_publish": _can_publish_gbp(db, gbp_row),
        "business": loc_ui,
        "posts": [post_to_dict(r) for r in rows],
        "summary": {
            "total": len(rows),
            "draft": sum(1 for r in rows if r.status == "draft"),
            "scheduled": sum(1 for r in rows if r.status == "scheduled"),
            "published": sum(1 for r in rows if r.status == "published"),
            "error": sum(1 for r in rows if r.status == "error"),
        },
    }


def get_calendar(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    date_from: str | None,
    date_to: str | None,
) -> dict[str, Any]:
    dt_from = _parse_dt(date_from) if date_from else None
    dt_to = _parse_dt(date_to) if date_to else None
    rows = db.execute(
        select(GbpPost).where(
            GbpPost.user_id == user_id,
            GbpPost.location_key == location_key,
        ).order_by(GbpPost.scheduled_at.asc().nullslast(), GbpPost.updated_at.desc())
    ).scalars().all()

    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = post_to_dict(row)
        key_date = None
        if row.scheduled_at:
            key_date = row.scheduled_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        elif row.published_at:
            key_date = row.published_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        elif row.status == "draft":
            key_date = row.updated_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if not key_date:
            continue
        if dt_from and datetime.fromisoformat(key_date).replace(tzinfo=timezone.utc) < dt_from.replace(hour=0, minute=0, second=0):
            continue
        if dt_to and datetime.fromisoformat(key_date).replace(tzinfo=timezone.utc) > dt_to.replace(hour=23, minute=59, second=59):
            continue
        by_date.setdefault(key_date, []).append(item)

    return {
        "location_key": location_key,
        "from": date_from,
        "to": date_to,
        "days": [{"date": d, "posts": by_date[d]} for d in sorted(by_date.keys())],
    }


def ai_generate(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    post_type: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    ptype = str(post_type or "").strip().lower()
    if ptype not in POST_TYPES:
        raise HTTPException(status_code=400, detail="post_type không hợp lệ.")
    _, loc_ui = _resolve_location(db, user_id, location_key)
    biz = {**(loc_ui or {}), **(input_data or {})}
    try:
        return generate_map_post(
            user_id=user_id,
            post_type=ptype,
            inp=input_data,
            business=biz,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def create_post(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    post_type: str,
    title: str,
    content: str,
    cta_type: str,
    cta_label: str,
    image_suggestions: list[str] | None = None,
    input_data: dict[str, Any] | None = None,
    status: str = "draft",
    scheduled_at: str | None = None,
    schedule_mode: str | None = None,
) -> dict[str, Any]:
    ptype = str(post_type or "").strip().lower()
    if ptype not in POST_TYPES:
        raise HTTPException(status_code=400, detail="post_type không hợp lệ.")
    cta = str(cta_type or "learn_more").strip().lower()
    if cta not in CTA_TYPES:
        cta = "learn_more"
    st = str(status or "draft").strip().lower()
    if st not in POST_STATUSES:
        st = "draft"
    smode = str(schedule_mode or "").strip().lower() or None
    if smode and smode not in SCHEDULE_MODES:
        raise HTTPException(status_code=400, detail="schedule_mode không hợp lệ.")

    gbp_row, _ = _resolve_location(db, user_id, location_key)
    sched = _parse_dt(scheduled_at)
    if sched and st == "draft":
        st = "scheduled"

    row = GbpPost(
        user_id=user_id,
        location_key=location_key,
        gbp_location_id=gbp_row.id if gbp_row else None,
        post_type=ptype,
        status=st,
        title=str(title or "").strip()[:255],
        content=str(content or "").strip(),
        cta_type=cta,
        cta_label=str(cta_label or CTA_LABELS[cta])[:120],
        image_suggestions_json=json.dumps(image_suggestions or [], ensure_ascii=False),
        input_json=json.dumps(input_data or {}, ensure_ascii=False),
        schedule_mode=smode,
        scheduled_at=sched,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return post_to_dict(row)


def update_post(
    db: Session,
    user_id: int,
    post_id: int,
    *,
    title: str | None = None,
    content: str | None = None,
    cta_type: str | None = None,
    cta_label: str | None = None,
    image_suggestions: list[str] | None = None,
    status: str | None = None,
    scheduled_at: str | None = None,
    schedule_mode: str | None = None,
) -> dict[str, Any]:
    row = db.get(GbpPost, post_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    if title is not None:
        row.title = str(title).strip()[:255]
    if content is not None:
        row.content = str(content).strip()
    if cta_type is not None:
        cta = str(cta_type).strip().lower()
        if cta in CTA_TYPES:
            row.cta_type = cta
    if cta_label is not None:
        row.cta_label = str(cta_label).strip()[:120]
    if image_suggestions is not None:
        row.image_suggestions_json = json.dumps(image_suggestions, ensure_ascii=False)
    if schedule_mode is not None:
        smode = str(schedule_mode).strip().lower() or None
        if smode and smode not in SCHEDULE_MODES:
            raise HTTPException(status_code=400, detail="schedule_mode không hợp lệ.")
        row.schedule_mode = smode
    if scheduled_at is not None:
        row.scheduled_at = _parse_dt(scheduled_at)
        if row.scheduled_at and row.status == "draft":
            row.status = "scheduled"
    if status is not None:
        st = str(status).strip().lower()
        if st not in POST_STATUSES:
            raise HTTPException(status_code=400, detail="status không hợp lệ.")
        row.status = st
    db.commit()
    db.refresh(row)
    return post_to_dict(row)


def schedule_post(
    db: Session,
    user_id: int,
    post_id: int,
    *,
    scheduled_at: str,
    schedule_mode: str = "once",
) -> dict[str, Any]:
    smode = str(schedule_mode or "once").strip().lower()
    if smode not in SCHEDULE_MODES:
        raise HTTPException(status_code=400, detail="schedule_mode không hợp lệ.")
    sched = _parse_dt(scheduled_at)
    if sched is None:
        raise HTTPException(status_code=400, detail="Thiếu scheduled_at.")
    if sched <= _now():
        raise HTTPException(status_code=400, detail="Thời gian lên lịch phải ở tương lai.")
    return update_post(
        db,
        user_id,
        post_id,
        scheduled_at=scheduled_at,
        schedule_mode=smode,
        status="scheduled",
    )


def publish_post(db: Session, user_id: int, post_id: int) -> dict[str, Any]:
    row = db.get(GbpPost, post_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    if not row.title or not row.content:
        raise HTTPException(status_code=400, detail="Bài đăng thiếu tiêu đề hoặc nội dung.")

    gbp_row, _ = _resolve_location(db, user_id, row.location_key)
    if gbp_row is None or not _can_publish_gbp(db, gbp_row):
        row.status = "draft"
        row.last_error = "Chưa kết nối GBP — bài lưu nháp nội bộ. Sao chép và đăng thủ công trên Google."
        db.commit()
        db.refresh(row)
        return {
            **post_to_dict(row),
            "published": False,
            "message": row.last_error,
        }

    conn = db.get(GbpOAuthConnection, gbp_row.connection_id)
    refresh = decrypt_secret(str(conn.refresh_token_encrypted or "")).strip()
    access = decrypt_secret(str(conn.access_token_encrypted or "")).strip() or None
    creds = credentials_from_tokens(
        refresh_token=refresh,
        access_token=access,
        token_expiry=conn.token_expires_at,
    )
    if not creds:
        row.status = "error"
        row.last_error = "Token GBP không hợp lệ."
        db.commit()
        db.refresh(row)
        raise HTTPException(status_code=400, detail=row.last_error)

    try:
        result = create_local_post(
            creds,
            account_resource=gbp_row.google_account_resource,
            location_resource=gbp_row.google_location_resource,
            post_type=row.post_type,
            title=row.title or "",
            content=row.content or "",
            cta_type=row.cta_type or "learn_more",
        )
        row.status = "published"
        row.published_at = _now()
        row.google_post_name = result.get("name") or None
        row.last_error = None
    except Exception as exc:
        _LOG.exception("GBP publish post failed id=%s", post_id)
        row.status = "error"
        row.last_error = str(exc)[:500]
        db.commit()
        db.refresh(row)
        raise HTTPException(
            status_code=502,
            detail=f"Không đăng được lên Google — đã lưu nháp. {exc}",
        ) from exc

    db.commit()
    db.refresh(row)
    return {
        **post_to_dict(row),
        "published": True,
        "message": "Đã đăng bài lên Google Business Profile.",
    }
