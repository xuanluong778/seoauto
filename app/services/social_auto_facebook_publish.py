"""Facebook Fanpage publish with retry + quota hooks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.social_auto_facebook_service import (
    is_mock_mode,
    publish_to_fanpage,
)
from app.services.social_auto_facebook_store import list_pages
from app.services.social_auto_production import assert_publish_not_mock
from app.services.social_auto_quota import assert_publish_allowed, record_publish_usage
from app.services.social_auto_safety import run_safety_checks
from app.services.social_auto_store import (
    MAX_PUBLISH_RETRIES,
    _find_campaign,
    _find_post,
    compute_next_retry_at,
    mark_published,
    update_post,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_message(post: dict[str, Any]) -> str:
    return "\n\n".join(x for x in [post.get("content"), post.get("hashtags"), post.get("cta")] if x).strip()


def _apply_publish_failure(post_id: str, owner_id: int, err: str, retry_count: int) -> None:
    patch: dict[str, Any] = {
        "error_message": err[:500],
        "last_error": err[:500],
        "last_error_at": _now_iso(),
        "retry_count": retry_count,
    }
    if retry_count >= MAX_PUBLISH_RETRIES:
        patch["status"] = "failed"
        patch["next_retry_at"] = None
    else:
        patch["status"] = "retrying"
        patch["next_retry_at"] = compute_next_retry_at(retry_count)
    update_post(post_id, owner_id, patch)


def publish_facebook_post(
    post_id: str,
    user_id: int,
    *,
    db: Session | None = None,
    user: User | None = None,
    source: str = "manual",
    page_id: str | None = None,
    skip_safety: bool = False,
) -> dict[str, Any]:
    row = _find_post(post_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    owner_id = int(row.get("user_id") or user_id)
    status = str(row.get("status") or "draft")
    if status == "publishing":
        raise HTTPException(status_code=409, detail="Bài đang được đăng.")
    if status == "published" and source not in {"retry", "scheduler"}:
        raise HTTPException(status_code=400, detail="Bài đã published.")

    pid = page_id or row.get("page_id")
    if not pid:
        raise HTTPException(status_code=400, detail="Chọn Fanpage trước khi đăng.")

    pages = list_pages(owner_id)
    page = next((p for p in pages if str(p.get("page_id")) == str(pid)), None)
    if not page:
        raise HTTPException(status_code=404, detail="Không tìm thấy Fanpage.")

    is_mock = bool(page.get("is_mock")) or is_mock_mode()
    if user is not None:
        assert_publish_not_mock(user, is_mock=is_mock, platform="Facebook")

    if db is not None and user is not None:
        assert_publish_allowed(db, user)

    camp = _find_campaign(str(row.get("campaign_id") or ""), owner_id)
    if not skip_safety:
        safety = run_safety_checks(
            owner_id,
            title=str(row.get("title") or ""),
            content=str(row.get("content") or ""),
            hashtags=str(row.get("hashtags") or ""),
            keyword=str((camp or {}).get("keyword") or ""),
            source_content=str((camp or {}).get("source_content") or ""),
            source_title=str((camp or {}).get("source_title") or ""),
            page_id=str(pid),
            exclude_post_id=post_id,
            scheduled_at=str(row.get("scheduled_at") or "") if source == "scheduler" else None,
        )
        need_pass = safety.get("passed") if source in {"manual", "retry"} else safety.get("can_schedule")
        if not need_pass:
            raise HTTPException(status_code=400, detail={"message": "Không đạt kiểm tra an toàn.", "safety": safety})

    update_post(post_id, owner_id, {"status": "publishing", "error_message": None, "page_id": str(pid)})
    message = _build_message(row)
    if not message:
        raise HTTPException(status_code=400, detail="Nội dung bài trống.")

    try:
        result = publish_to_fanpage(owner_id, str(pid), message)
    except HTTPException as exc:
        retries = int(row.get("retry_count") or 0) + 1
        err = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        _apply_publish_failure(post_id, owner_id, err, retries)
        raise
    except Exception as exc:
        retries = int(row.get("retry_count") or 0) + 1
        _apply_publish_failure(post_id, owner_id, str(exc), retries)
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc

    item = mark_published(post_id, owner_id, str(result.get("permalink_url") or ""))
    if db is not None and user is not None:
        record_publish_usage(db, user)
    return {"item": item, "facebook": result, "source": source}
