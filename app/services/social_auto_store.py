"""Social Auto — JSON file store (per-user campaigns & posts)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from pathlib import Path

from app.services.user_scope import belongs_to_user, is_admin_role

CAMPAIGNS_FILE = Path("data/social_auto_campaigns.json")
POSTS_FILE = Path("data/social_auto_posts.json")
MAX_CAMPAIGNS = 200
MAX_POSTS = 1000
MAX_PUBLISH_RETRIES = 3

PLATFORMS = frozenset({"facebook", "zalo", "web20"})
CAMPAIGN_STATUSES = frozenset({"draft", "active", "completed", "archived"})
POST_STATUSES = frozenset(
    {"draft", "scheduled", "publishing", "published", "failed", "retrying", "cancelled", "approved"}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _write_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def compute_next_retry_at(retry_count: int) -> str:
    from datetime import timedelta

    minutes = min(30, 5 * max(1, int(retry_count)))
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _owned_rows(items: list[dict[str, Any]], user_id: int, role: str | None = None) -> list[dict[str, Any]]:
    if is_admin_role(role):
        return list(items)
    return [x for x in items if belongs_to_user(x, user_id)]


def _campaigns_for_user(user_id: int, role: str | None = None) -> list[dict[str, Any]]:
    return _owned_rows(_read_list(CAMPAIGNS_FILE), user_id, role)


def _posts_for_user(user_id: int, role: str | None = None) -> list[dict[str, Any]]:
    return _owned_rows(_read_list(POSTS_FILE), user_id, role)


def _find_campaign(campaign_id: str, user_id: int, role: str | None = None) -> dict[str, Any] | None:
    for c in _read_list(CAMPAIGNS_FILE):
        if str(c.get("id")) != str(campaign_id):
            continue
        if is_admin_role(role) or belongs_to_user(c, user_id):
            return c
    return None


def _find_post(post_id: str, user_id: int, role: str | None = None) -> dict[str, Any] | None:
    for p in _read_list(POSTS_FILE):
        if str(p.get("id")) != str(post_id):
            continue
        if is_admin_role(role) or belongs_to_user(p, user_id):
            return p
    return None


def get_overview_stats(user_id: int, role: str | None = None) -> dict[str, int]:
    campaigns = _campaigns_for_user(user_id, role)
    posts = _posts_for_user(user_id, role)
    return {
        "campaigns": len(campaigns),
        "drafts": sum(1 for p in posts if str(p.get("status")) in {"draft", "approved"}),
        "scheduled": sum(1 for p in posts if str(p.get("status")) == "scheduled"),
        "published": sum(1 for p in posts if str(p.get("status")) == "published"),
        "failed": sum(1 for p in posts if str(p.get("status")) in {"failed", "retrying"}),
    }


def list_campaigns(user_id: int, role: str | None = None) -> list[dict[str, Any]]:
    items = _campaigns_for_user(user_id, role)
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return items


def list_posts(
    user_id: int,
    *,
    campaign_id: str | None = None,
    status: str | None = None,
    platform: str | None = None,
    role: str | None = None,
) -> list[dict[str, Any]]:
    items = _posts_for_user(user_id, role)
    if campaign_id:
        items = [p for p in items if str(p.get("campaign_id")) == str(campaign_id)]
    if status:
        items = [p for p in items if str(p.get("status")) == str(status)]
    if platform:
        items = [p for p in items if str(p.get("platform")) == str(platform)]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return items


def create_campaign(
    *,
    user_id: int,
    name: str,
    source_title: str = "",
    source_content: str = "",
    keyword: str = "",
    target_url: str = "",
    status: str = "draft",
) -> dict[str, Any]:
    st = status if status in CAMPAIGN_STATUSES else "draft"
    all_c = _read_list(CAMPAIGNS_FILE)
    if len([c for c in all_c if belongs_to_user(c, user_id)]) >= MAX_CAMPAIGNS:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn chiến dịch.")
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "name": (name or source_title or "Chiến dịch mới").strip()[:200],
        "source_title": (source_title or "").strip()[:500],
        "source_content": (source_content or "").strip()[:50000],
        "keyword": (keyword or "").strip()[:200],
        "target_url": (target_url or "").strip()[:2000],
        "status": st,
        "created_at": _now(),
    }
    all_c.append(entry)
    _write_list(CAMPAIGNS_FILE, all_c)
    return entry


def update_campaign(campaign_id: str, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    all_c = _read_list(CAMPAIGNS_FILE)
    for i, c in enumerate(all_c):
        if str(c.get("id")) != str(campaign_id) or not belongs_to_user(c, user_id):
            continue
        merged = dict(c)
        for key in ("name", "source_title", "source_content", "keyword", "target_url", "status"):
            if key in patch and patch[key] is not None:
                val = patch[key]
                if key == "status":
                    if val not in CAMPAIGN_STATUSES:
                        raise HTTPException(status_code=400, detail="status chiến dịch không hợp lệ.")
                    merged[key] = val
                else:
                    merged[key] = str(val).strip()[:50000 if key == "source_content" else 2000]
        all_c[i] = merged
        _write_list(CAMPAIGNS_FILE, all_c)
        return merged
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chiến dịch.")


def create_post(
    *,
    user_id: int,
    campaign_id: str,
    platform: str,
    title: str = "",
    content: str = "",
    hashtags: str = "",
    cta: str = "",
    status: str = "draft",
    page_id: str | None = None,
) -> dict[str, Any]:
    plat = str(platform or "").strip().lower()
    if plat not in PLATFORMS:
        raise HTTPException(status_code=400, detail="platform không hợp lệ.")
    if not _find_campaign(campaign_id, user_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy chiến dịch.")
    st = status if status in POST_STATUSES else "draft"
    all_p = _read_list(POSTS_FILE)
    if len([p for p in all_p if belongs_to_user(p, user_id)]) >= MAX_POSTS:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn bài đăng.")
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "campaign_id": str(campaign_id),
        "platform": plat,
        "title": (title or "").strip()[:500],
        "content": (content or "").strip()[:20000],
        "hashtags": (hashtags or "").strip()[:500],
        "cta": (cta or "").strip()[:1000],
        "status": st,
        "page_id": (str(page_id).strip() if page_id else None) or None,
        "scheduled_at": None,
        "published_url": None,
        "error_message": None,
        "retry_count": 0,
        "last_error": None,
        "last_error_at": None,
        "next_retry_at": None,
        "created_at": _now(),
    }
    all_p.append(entry)
    _write_list(POSTS_FILE, all_p)
    return entry


def upsert_variant_post(
    *,
    user_id: int,
    campaign_id: str,
    platform: str,
    title: str,
    content: str,
    hashtags: str = "",
    cta: str = "",
    page_id: str | None = None,
) -> dict[str, Any]:
    """Replace draft/approved variant for platform in campaign, or create new."""
    plat = str(platform or "").strip().lower()
    all_p = _read_list(POSTS_FILE)
    for i, p in enumerate(all_p):
        if (
            belongs_to_user(p, user_id)
            and str(p.get("campaign_id")) == str(campaign_id)
            and str(p.get("platform")) == plat
            and str(p.get("status")) in {"draft", "approved"}
        ):
            merged = dict(p)
            merged["title"] = (title or "").strip()[:500]
            merged["content"] = (content or "").strip()[:20000]
            merged["hashtags"] = (hashtags or "").strip()[:500]
            merged["cta"] = (cta or "").strip()[:1000]
            merged["status"] = "draft"
            if page_id:
                merged["page_id"] = str(page_id)
            all_p[i] = merged
            _write_list(POSTS_FILE, all_p)
            return merged
    return create_post(
        user_id=user_id,
        campaign_id=campaign_id,
        platform=plat,
        title=title,
        content=content,
        hashtags=hashtags,
        cta=cta,
        status="draft",
        page_id=page_id,
    )


def update_post(post_id: str, user_id: int, patch: dict[str, Any], role: str | None = None) -> dict[str, Any]:
    all_p = _read_list(POSTS_FILE)
    for i, p in enumerate(all_p):
        if str(p.get("id")) != str(post_id):
            continue
        if not is_admin_role(role) and not belongs_to_user(p, user_id):
            continue
        owner_id = int(p.get("user_id") or user_id)
        merged = dict(p)
        for key in (
            "title", "content", "hashtags", "cta", "status", "page_id",
            "scheduled_at", "published_url", "error_message",
            "retry_count", "last_error", "last_error_at", "next_retry_at",
        ):
            if key not in patch:
                continue
            val = patch[key]
            if key == "status":
                if val is not None and val not in POST_STATUSES:
                    raise HTTPException(status_code=400, detail="status bài đăng không hợp lệ.")
                merged[key] = val
            elif key in ("scheduled_at", "published_url", "error_message", "page_id", "last_error", "last_error_at", "next_retry_at"):
                merged[key] = (str(val).strip() if val else None) or None
            elif key == "retry_count":
                merged[key] = max(0, int(val or 0))
            else:
                merged[key] = str(val or "").strip()[:20000 if key == "content" else 1000]
        all_p[i] = merged
        _write_list(POSTS_FILE, all_p)
        return merged
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bài đăng.")


def schedule_post(post_id: str, user_id: int, scheduled_at: str, role: str | None = None) -> dict[str, Any]:
    when = str(scheduled_at or "").strip()
    if not when:
        raise HTTPException(status_code=400, detail="Thiếu scheduled_at.")
    return update_post(
        post_id,
        user_id,
        {
            "scheduled_at": when,
            "status": "scheduled",
            "error_message": None,
            "last_error": None,
            "next_retry_at": None,
        },
        role=role,
    )


def cancel_schedule(post_id: str, user_id: int, role: str | None = None) -> dict[str, Any]:
    post = _find_post(post_id, user_id, role)
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    return update_post(
        post_id,
        user_id,
        {"scheduled_at": None, "status": "cancelled", "next_retry_at": None},
        role=role,
    )


def mark_published(post_id: str, user_id: int, published_url: str, role: str | None = None) -> dict[str, Any]:
    url = str(published_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Thiếu published_url.")
    return update_post(
        post_id,
        user_id,
        {
            "published_url": url,
            "status": "published",
            "error_message": None,
            "last_error": None,
            "scheduled_at": None,
            "next_retry_at": None,
        },
        role=role,
    )


def list_due_scheduled_posts(*, now: datetime | None = None, platform: str | None = "facebook") -> list[dict[str, Any]]:
    """Scheduled posts due for publish (system-wide cron scan)."""
    now = now or datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    for row in _read_list(POSTS_FILE):
        if str(row.get("status") or "") != "scheduled":
            continue
        if platform and str(row.get("platform") or "") != str(platform):
            continue
        at = _parse_iso(str(row.get("scheduled_at") or ""))
        if at and at <= now:
            due.append(row)
    due.sort(key=lambda x: str(x.get("scheduled_at") or ""))
    return due


def list_retrying_posts(*, now: datetime | None = None, platform: str | None = "facebook") -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for row in _read_list(POSTS_FILE):
        if str(row.get("status") or "") != "retrying":
            continue
        if platform and str(row.get("platform") or "") != str(platform):
            continue
        retries = int(row.get("retry_count") or 0)
        if retries >= MAX_PUBLISH_RETRIES:
            continue
        nxt = _parse_iso(str(row.get("next_retry_at") or ""))
        if nxt and nxt > now:
            continue
        if not nxt:
            last = _parse_iso(str(row.get("last_error_at") or ""))
            if last:
                backoff_min = min(30, 5 * max(1, retries))
                if (now - last).total_seconds() < backoff_min * 60:
                    continue
        out.append(row)
    return out
