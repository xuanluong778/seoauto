"""Unified Social Auto scheduler — Facebook Fanpage + Web 2.0."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.social_auto_facebook_publish import publish_facebook_post
from app.services.social_auto_store import list_due_scheduled_posts as list_fb_due
from app.services.social_auto_store import list_retrying_posts as list_fb_retry
from app.services.social_auto_web20_scheduler import run_web20_scheduler


def run_facebook_scheduler(*, db: Session | None = None, limit: int = 20) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    due = list_fb_due(now=now, platform="facebook")
    retry = list_fb_retry(now=now, platform="facebook")
    queue = due + [r for r in retry if r not in due]
    queue = queue[: max(1, min(limit, 100))]

    processed: list[dict[str, Any]] = []
    for row in queue:
        post_id = str(row.get("id") or "")
        owner_id = int(row.get("user_id") or 0)
        if not post_id or not owner_id:
            continue
        source = "scheduler" if str(row.get("status")) == "scheduled" else "retry"
        user = db.query(User).filter(User.id == owner_id).one_or_none() if db is not None else None
        try:
            result = publish_facebook_post(
                post_id,
                owner_id,
                db=db,
                user=user,
                source=source,
                skip_safety=False,
            )
            processed.append({"post_id": post_id, "channel": "facebook", "ok": True, "status": result.get("item", {}).get("status")})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            processed.append({"post_id": post_id, "channel": "facebook", "ok": False, "error": detail[:300]})
        except Exception as exc:
            processed.append({"post_id": post_id, "channel": "facebook", "ok": False, "error": str(exc)[:300]})

    return {
        "ok": True,
        "channel": "facebook",
        "at": now.isoformat(),
        "queued": len(queue),
        "processed": processed,
    }


def run_social_auto_scheduler(*, db: Session | None = None, limit: int = 20) -> dict[str, Any]:
    """Run Facebook + Web 2.0 scheduled/retry queues."""
    fb = run_facebook_scheduler(db=db, limit=limit)
    w20 = run_web20_scheduler(limit=limit, db=db)
    return {
        "ok": True,
        "at": datetime.now(timezone.utc).isoformat(),
        "facebook": fb,
        "web20": w20,
    }
