"""Google Map SEO — quản lý review & phản hồi."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret
from app.models.google_map_gbp import GbpLocation, GbpOAuthConnection, GbpReviewReplyDraft
from app.services.google_map_gbp_api import credentials_from_tokens
from app.services.google_map_gbp_profile_service import _resolve_location
from app.services.google_map_gbp_review_ai import generate_review_reply
from app.services.google_map_gbp_reviews_api import list_location_reviews, post_review_reply

_LOG = logging.getLogger("google_map_gbp.reviews")

REVIEW_FILTERS = frozenset({
    "all", "1", "2", "3", "4", "5", "unreplied", "negative",
})

# Demo reviews theo location_key (mock UI)
_DEMO_REVIEWS: dict[str, list[dict[str, Any]]] = {
    "loc1": [
        {"id": "r1", "author": "Minh Tuấn", "stars": 5, "text": "Dịch vụ SEO rất chuyên nghiệp, tư vấn nhiệt tình.", "date": "2026-06-20T10:00:00Z", "replied": True, "reply_text": "Cảm ơn anh Tuấn đã tin tưởng DigiSEO!", "reply_date": "2026-06-21T09:00:00Z", "is_negative": False},
        {"id": "r2", "author": "Lan Anh", "stars": 4, "text": "Báo cáo rõ ràng, team hỗ trợ nhanh.", "date": "2026-06-15T08:00:00Z", "replied": False, "reply_text": "", "reply_date": "", "is_negative": False},
        {"id": "r3", "author": "Hoàng Nam", "stars": 5, "text": "Tối ưu Google Map giúp shop nhận thêm khách gọi điện.", "date": "2026-06-10T12:00:00Z", "replied": False, "reply_text": "", "reply_date": "", "is_negative": False},
        {"id": "r4", "author": "Thu Hà", "stars": 2, "text": "Thời gian triển khai lâu hơn cam kết, cần cải thiện.", "date": "2026-06-05T14:00:00Z", "replied": False, "reply_text": "", "reply_date": "", "is_negative": True},
        {"id": "r5", "author": "Đức Phong", "stars": 1, "text": "Chưa thấy kết quả rõ sau 2 tháng, hơi thất vọng.", "date": "2026-06-01T16:00:00Z", "replied": False, "reply_text": "", "reply_date": "", "is_negative": True},
    ],
    "loc2": [
        {"id": "r6", "author": "Ngọc Linh", "stars": 4, "text": "Tư vấn Local SEO hữu ích.", "date": "2026-06-18T11:00:00Z", "replied": True, "reply_text": "Cảm ơn chị Linh!", "reply_date": "2026-06-19T10:00:00Z", "is_negative": False},
        {"id": "r7", "author": "Bảo Long", "stars": 3, "text": "Ổn nhưng cần thêm báo cáo chi tiết.", "date": "2026-06-12T09:00:00Z", "replied": False, "reply_text": "", "reply_date": "", "is_negative": False},
    ],
    "loc3": [
        {"id": "r8", "author": "Hà My", "stars": 5, "text": "Hỗ trợ nhanh qua Zalo.", "date": "2026-06-22T08:00:00Z", "replied": False, "reply_text": "", "reply_date": "", "is_negative": False},
        {"id": "r9", "author": "Kiên", "stars": 2, "text": "Chưa nhận được báo cáo đúng hạn.", "date": "2026-06-08T15:00:00Z", "replied": False, "reply_text": "", "reply_date": "", "is_negative": True},
    ],
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _apply_filter(reviews: list[dict[str, Any]], filt: str) -> list[dict[str, Any]]:
    f = str(filt or "all").strip().lower()
    if f == "all":
        return reviews
    if f == "unreplied":
        return [r for r in reviews if not r.get("replied")]
    if f == "negative":
        return [r for r in reviews if r.get("is_negative") or int(r.get("stars") or 0) <= 2]
    if f in {"1", "2", "3", "4", "5"}:
        star = int(f)
        return [r for r in reviews if int(r.get("stars") or 0) == star]
    return reviews


def _summary(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    if not reviews:
        return {"count": 0, "avg_stars": None, "unreplied": 0, "negative": 0}
    stars = [int(r.get("stars") or 0) for r in reviews if int(r.get("stars") or 0) > 0]
    unreplied = sum(1 for r in reviews if not r.get("replied"))
    negative = sum(1 for r in reviews if r.get("is_negative") or int(r.get("stars") or 0) <= 2)
    avg = round(sum(stars) / len(stars), 1) if stars else None
    return {"count": len(reviews), "avg_stars": avg, "unreplied": unreplied, "negative": negative}


def list_reviews(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    review_filter: str = "all",
) -> dict[str, Any]:
    filt = str(review_filter or "all").strip().lower()
    if filt not in REVIEW_FILTERS:
        raise HTTPException(status_code=400, detail="Bộ lọc review không hợp lệ.")

    gbp_row, loc_ui = _resolve_location(db, user_id, location_key)
    source = "demo"
    reviews: list[dict[str, Any]] = []

    if gbp_row:
        conn = db.get(GbpOAuthConnection, gbp_row.connection_id)
        if conn and conn.status == "active":
            refresh = decrypt_secret(str(conn.refresh_token_encrypted or "")).strip()
            access = decrypt_secret(str(conn.access_token_encrypted or "")).strip() or None
            creds = credentials_from_tokens(
                refresh_token=refresh,
                access_token=access,
                token_expiry=conn.token_expires_at,
            )
            if creds:
                try:
                    reviews = list_location_reviews(
                        creds,
                        account_resource=gbp_row.google_account_resource,
                        location_resource=gbp_row.google_location_resource,
                    )
                    source = "google_business_profile"
                except Exception as exc:
                    _LOG.exception("GBP reviews list failed loc=%s", gbp_row.id)
                    raise HTTPException(
                        status_code=502,
                        detail=f"Không lấy được review từ Google: {exc}",
                    ) from exc

    if not reviews:
        reviews = [dict(r) for r in _DEMO_REVIEWS.get(location_key, _DEMO_REVIEWS.get("loc1", []))]
        if gbp_row and source != "google_business_profile":
            source = "demo"

    filtered = _apply_filter(reviews, filt)
    return {
        "source": source,
        "location_key": location_key,
        "filter": filt,
        "summary": _summary(reviews),
        "reviews": filtered,
        "can_post_reply": source == "google_business_profile",
        "business": loc_ui,
    }


def ai_reply(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    review: dict[str, Any],
    tone: str,
    business: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _, loc_ui = _resolve_location(db, user_id, location_key)
    biz = {**(loc_ui or {}), **(business or {})}
    try:
        return generate_review_reply(user_id=user_id, review=review, business=biz, tone=tone)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def save_reply_draft(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    review_id: str,
    tone: str,
    reply_text: str,
) -> dict[str, Any]:
    rid = str(review_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="Thiếu review_id.")
    row = db.execute(
        select(GbpReviewReplyDraft).where(
            GbpReviewReplyDraft.user_id == user_id,
            GbpReviewReplyDraft.location_key == location_key,
            GbpReviewReplyDraft.review_id == rid,
        )
    ).scalar_one_or_none()
    if row is None:
        row = GbpReviewReplyDraft(
            user_id=user_id,
            location_key=location_key,
            review_id=rid,
            tone=tone,
            reply_text=reply_text,
        )
        db.add(row)
    else:
        row.tone = tone
        row.reply_text = reply_text
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "review_id": row.review_id,
        "tone": row.tone,
        "reply_text": row.reply_text,
        "updated_at": _iso(row.updated_at),
    }


def get_reply_drafts(db: Session, user_id: int, *, location_key: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(GbpReviewReplyDraft).where(
            GbpReviewReplyDraft.user_id == user_id,
            GbpReviewReplyDraft.location_key == location_key,
        )
    ).scalars().all()
    return [
        {
            "review_id": r.review_id,
            "tone": r.tone,
            "reply_text": r.reply_text,
            "updated_at": _iso(r.updated_at),
        }
        for r in rows
    ]


def post_reply(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    review_id: str,
    review_resource_name: str,
    reply_text: str,
) -> dict[str, Any]:
    gbp_row, _ = _resolve_location(db, user_id, location_key)
    if gbp_row is None:
        raise HTTPException(
            status_code=400,
            detail="Chưa kết nối địa điểm GBP — lưu nháp và dán thủ công trên Google.",
        )
    resource = str(review_resource_name or "").strip()
    if not resource:
        raise HTTPException(status_code=400, detail="Thiếu review_resource_name từ Google.")

    conn = db.get(GbpOAuthConnection, gbp_row.connection_id)
    if not conn or conn.status != "active":
        raise HTTPException(status_code=400, detail="Kết nối GBP không còn hiệu lực.")

    refresh = decrypt_secret(str(conn.refresh_token_encrypted or "")).strip()
    access = decrypt_secret(str(conn.access_token_encrypted or "")).strip() or None
    creds = credentials_from_tokens(
        refresh_token=refresh,
        access_token=access,
        token_expiry=conn.token_expires_at,
    )
    if not creds:
        raise HTTPException(status_code=400, detail="Token GBP không hợp lệ.")

    try:
        post_review_reply(creds, resource, reply_text)
    except Exception as exc:
        _LOG.exception("GBP post reply failed review=%s", review_id)
        raise HTTPException(status_code=502, detail=f"Không gửi được phản hồi: {exc}") from exc

    save_reply_draft(
        db,
        user_id,
        location_key=location_key,
        review_id=review_id,
        tone="",
        reply_text=reply_text,
    )
    return {"posted": True, "review_id": review_id, "message": "Đã gửi phản hồi lên Google Business Profile."}
