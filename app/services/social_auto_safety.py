"""Social Auto — kiểm tra an toàn nền tảng Facebook Fanpage."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from app.services.social_auto_facebook_store import get_safety_settings
from app.services.social_auto_store import list_posts

_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _parse_dt(iso: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def check_duplicate_content(
    user_id: int,
    content: str,
    *,
    exclude_post_id: str | None = None,
    page_id: str | None = None,
    threshold: float = 0.95,
) -> dict[str, Any]:
    posts = list_posts(user_id, platform="facebook")
    for p in posts:
        if exclude_post_id and str(p.get("id")) == str(exclude_post_id):
            continue
        if page_id and str(p.get("page_id") or "") != str(page_id):
            continue
        if str(p.get("status")) not in {"scheduled", "published", "approved"}:
            continue
        other = f"{p.get('title') or ''}\n{p.get('content') or ''}\n{p.get('hashtags') or ''}"
        sim = _similarity(content, other)
        if sim >= threshold:
            return {
                "ok": False,
                "code": "duplicate_content",
                "level": "error",
                "message": f"Nội dung trùng ~{int(sim * 100)}% với bài «{p.get('title') or p.get('id')}».",
                "similarity": round(sim, 3),
            }
    return {"ok": True, "code": "duplicate_content", "level": "passed", "message": "Không trùng 100%."}


def check_posting_density(
    user_id: int,
    scheduled_at: str,
    *,
    page_id: str | None = None,
    exclude_post_id: str | None = None,
) -> dict[str, Any]:
    settings = get_safety_settings(user_id)
    if settings.get("is_paused"):
        return {
            "ok": False,
            "code": "posting_paused",
            "level": "error",
            "message": settings.get("pause_reason") or "Hệ thống tạm dừng đăng bài.",
        }

    target = _parse_dt(scheduled_at)
    if not target:
        return {"ok": False, "code": "invalid_time", "level": "error", "message": "Thời gian lên lịch không hợp lệ."}

    max_day = int(settings.get("max_posts_per_day") or 4)
    min_gap_h = float(settings.get("min_hours_between_posts") or 3)
    min_gap = timedelta(hours=min_gap_h)

    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    posts = list_posts(user_id, platform="facebook", status="scheduled")
    posts += [p for p in list_posts(user_id, platform="facebook", status="published") if p.get("scheduled_at")]

    same_day = 0
    for p in posts:
        if exclude_post_id and str(p.get("id")) == str(exclude_post_id):
            continue
        if page_id and str(p.get("page_id") or "") != str(page_id):
            continue
        when = _parse_dt(str(p.get("scheduled_at") or p.get("created_at") or ""))
        if not when or not (day_start <= when < day_end):
            continue
        same_day += 1
        delta = abs((when - target).total_seconds())
        if delta < min_gap.total_seconds() and delta > 0:
            return {
                "ok": False,
                "code": "too_dense",
                "level": "error",
                "message": f"Mỗi bài cần cách nhau ít nhất {min_gap_h:g} giờ trên cùng Fanpage.",
            }

    if same_day >= max_day:
        return {
            "ok": False,
            "code": "daily_limit",
            "level": "error",
            "message": f"Đã đạt giới hạn {max_day} bài/ngày/Fanpage.",
        }

    if same_day >= max(1, max_day - 1):
        return {
            "ok": True,
            "code": "daily_limit",
            "level": "warning",
            "message": f"Sắp đạt giới hạn {max_day} bài/ngày ({same_day + 1}/{max_day}).",
        }
    return {"ok": True, "code": "posting_density", "level": "passed", "message": "Tần suất đăng an toàn."}


def check_simultaneous_pages(user_id: int, scheduled_at: str, page_id: str) -> dict[str, Any]:
    """Không cho 2 Fanpage đăng cùng thời điểm."""
    target = _parse_dt(scheduled_at)
    if not target:
        return {"ok": True, "code": "simultaneous", "level": "passed", "message": "—"}
    window = timedelta(minutes=5)
    for p in list_posts(user_id, platform="facebook", status="scheduled"):
        if str(p.get("page_id") or "") == str(page_id):
            continue
        when = _parse_dt(str(p.get("scheduled_at") or ""))
        if when and abs((when - target).total_seconds()) < window.total_seconds():
            return {
                "ok": False,
                "code": "simultaneous_pages",
                "level": "error",
                "message": "Không đăng đồng thời lên nhiều Fanpage.",
            }
    return {"ok": True, "code": "simultaneous", "level": "passed", "message": "Không trùng slot đa Page."}


def check_hashtag_spam(hashtags: str) -> dict[str, Any]:
    tags = _HASHTAG_RE.findall(hashtags or "")
    if len(tags) > 8:
        return {"ok": False, "code": "hashtag_spam", "level": "error", "message": f"Quá nhiều hashtag ({len(tags)}). Tối đa 8."}
    lowered = [t.lower() for t in tags]
    if len(lowered) != len(set(lowered)):
        return {"ok": False, "code": "hashtag_spam", "level": "warning", "message": "Hashtag bị lặp."}
    if len(tags) > 5:
        return {"ok": True, "code": "hashtag_spam", "level": "warning", "message": "Nhiều hashtag — nên giảm còn 3–5."}
    return {"ok": True, "code": "hashtag_spam", "level": "passed", "message": "Hashtag ổn."}


def check_caption_relevance(
    *,
    keyword: str,
    title: str,
    content: str,
    source_title: str = "",
) -> dict[str, Any]:
    blob = _norm(f"{title} {content}")
    kw = _norm(keyword)
    if kw and kw not in blob and kw.split()[0] not in blob:
        return {
            "ok": True,
            "code": "caption_relevance",
            "level": "warning",
            "message": "Caption có thể không liên quan từ khóa chính.",
        }
    if source_title and _similarity(title, source_title) < 0.15 and not kw:
        return {
            "ok": True,
            "code": "caption_relevance",
            "level": "warning",
            "message": "Tiêu đề biến thể khác xa bài gốc — kiểm tra lại.",
        }
    return {"ok": True, "code": "caption_relevance", "level": "passed", "message": "Caption liên quan."}


def check_copy_repost(content: str, source_content: str) -> dict[str, Any]:
    if not source_content:
        return {"ok": True, "code": "copy_repost", "level": "passed", "message": "—"}
    sim = _similarity(content, source_content)
    if sim >= 0.9:
        return {
            "ok": False,
            "code": "copy_repost",
            "level": "error",
            "message": f"Nội dung gần như copy nguyên văn bài gốc (~{int(sim * 100)}%). Cần viết lại.",
            "similarity": round(sim, 3),
        }
    if sim >= 0.75:
        return {
            "ok": True,
            "code": "copy_repost",
            "level": "warning",
            "message": f"Nội dung giống bài gốc ~{int(sim * 100)}% — nên chỉnh thêm.",
            "similarity": round(sim, 3),
        }
    return {"ok": True, "code": "copy_repost", "level": "passed", "message": "Không phải copy/repost."}


def run_safety_checks(
    user_id: int,
    *,
    title: str,
    content: str,
    hashtags: str,
    keyword: str = "",
    source_content: str = "",
    source_title: str = "",
    scheduled_at: str | None = None,
    page_id: str | None = None,
    exclude_post_id: str | None = None,
) -> dict[str, Any]:
    full_text = f"{title}\n{content}\n{hashtags}".strip()
    checks = [
        check_duplicate_content(user_id, full_text, exclude_post_id=exclude_post_id, page_id=page_id),
        check_hashtag_spam(hashtags),
        check_caption_relevance(keyword=keyword, title=title, content=content, source_title=source_title),
        check_copy_repost(content, source_content),
    ]
    if scheduled_at:
        checks.append(check_posting_density(user_id, scheduled_at, page_id=page_id, exclude_post_id=exclude_post_id))
        if page_id:
            checks.append(check_simultaneous_pages(user_id, scheduled_at, page_id))

    errors = [c for c in checks if not c.get("ok")]
    warnings = [c for c in checks if c.get("ok") and c.get("level") == "warning"]
    return {
        "passed": len(errors) == 0,
        "can_schedule": len([e for e in errors if e.get("level") == "error"]) == 0,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
