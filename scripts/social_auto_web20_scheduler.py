"""Web 2.0 scheduled publish runner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.services.social_auto_web20_publish import publish_web20_post
from app.services.social_auto_web20_store import (
    MAX_PUBLISH_RETRIES,
    append_log,
    list_due_scheduled_posts,
    list_retrying_posts,
    update_post,
)


def run_web20_scheduler(*, limit: int = 20) -> dict[str, Any]:
    """Quét bài scheduled/retrying và publish qua provider."""
    now = datetime.now(timezone.utc)
    due = list_due_scheduled_posts(now=now)
    retry = list_retrying_posts(now=now)
    queue = due + [r for r in retry if r not in due]
    queue = queue[: max(1, min(limit, 100))]

    processed: list[dict[str, Any]] = []
    for row in queue:
        post_id = str(row.get("id") or "")
        user_id = int(row.get("user_id") or 0)
        if not post_id or not user_id:
            continue
        source = "scheduler" if str(row.get("status")) == "scheduled" else "retry"
        try:
            result = publish_web20_post(
                post_id,
                user_id,
                source=source,
                skip_schedule_check=True,
            )
            processed.append({"post_id": post_id, "ok": True, "status": result.get("item", {}).get("status")})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            processed.append({"post_id": post_id, "ok": False, "error": detail[:300]})
        except Exception as exc:
            retries = int(row.get("retry_count") or 0) + 1
            patch: dict[str, Any] = {
                "retry_count": retries,
                "last_error_at": datetime.now(timezone.utc).isoformat(),
                "error_message": str(exc)[:500],
                "status": "failed" if retries >= MAX_PUBLISH_RETRIES else "retrying",
            }
            update_post(post_id, user_id, patch)
            append_log(
                user_id,
                level="error",
                code="scheduler_error",
                message=str(exc)[:500],
                post_id=post_id,
                account_id=str(row.get("account_id") or ""),
            )
            processed.append({"post_id": post_id, "ok": False, "error": str(exc)[:300]})

    return {
        "ok": True,
        "at": now.isoformat(),
        "queued": len(queue),
        "processed": processed,
    }
