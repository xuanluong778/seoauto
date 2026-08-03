"""Web 2.0 scheduled publish runner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.social_auto_store import compute_next_retry_at
from app.services.social_auto_web20_publish import publish_web20_post
from app.services.social_auto_web20_store import (
    MAX_PUBLISH_RETRIES,
    _find_account,
    append_log,
    list_due_scheduled_posts,
    list_retrying_posts,
    update_post,
)


def run_web20_scheduler(*, limit: int = 20, db: Session | None = None) -> dict[str, Any]:
    """Quét bài scheduled/retrying và publish qua provider (trừ Google Sites manual)."""
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
        account_id = str(row.get("account_id") or "")
        account = _find_account(account_id, user_id) if account_id else None
        platform = str((account or row).get("platform") or "")
        if platform == "google_sites_manual":
            processed.append({"post_id": post_id, "ok": False, "skipped": "manual_platform"})
            continue

        source = "scheduler" if str(row.get("status")) == "scheduled" else "retry"
        user = db.query(User).filter(User.id == user_id).one_or_none() if db is not None else None
        try:
            result = publish_web20_post(
                post_id,
                user_id,
                db=db,
                user=user,
                source=source,
                skip_schedule_check=True,
            )
            processed.append({"post_id": post_id, "ok": True, "status": result.get("item", {}).get("status")})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            retries = int(row.get("retry_count") or 0) + 1
            patch: dict[str, Any] = {
                "error_message": detail[:500],
                "last_error": detail[:500],
                "retry_count": retries,
                "last_error_at": now.isoformat(),
            }
            if retries >= MAX_PUBLISH_RETRIES:
                patch["status"] = "failed"
                patch["next_retry_at"] = None
            else:
                patch["status"] = "retrying"
                patch["next_retry_at"] = compute_next_retry_at(retries)
            update_post(post_id, user_id, patch)
            processed.append({"post_id": post_id, "ok": False, "error": detail[:300]})
        except Exception as exc:
            retries = int(row.get("retry_count") or 0) + 1
            patch = {
                "retry_count": retries,
                "last_error_at": now.isoformat(),
                "last_error": str(exc)[:500],
                "error_message": str(exc)[:500],
                "status": "failed" if retries >= MAX_PUBLISH_RETRIES else "retrying",
                "next_retry_at": None if retries >= MAX_PUBLISH_RETRIES else compute_next_retry_at(retries),
            }
            update_post(post_id, user_id, patch)
            append_log(
                user_id,
                level="error",
                code="scheduler_error",
                message=str(exc)[:500],
                post_id=post_id,
                account_id=account_id,
            )
            processed.append({"post_id": post_id, "ok": False, "error": str(exc)[:300]})

    return {
        "ok": True,
        "at": now.isoformat(),
        "queued": len(queue),
        "processed": processed,
    }
