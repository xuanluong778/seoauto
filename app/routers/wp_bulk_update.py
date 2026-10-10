from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.models.user import User
from app.services.auth import get_current_user
from app.services.job_store import cleanup_expired, create_job, ensure_job_schema, get_job, mark_stale_jobs_failed, mark_stale_queued_failed
from app.services.job_store import get_job_for_user
from app.services.user_scope import assert_job_access


router = APIRouter(prefix="/wp", tags=["wordpress"])


class WpBulkUpdateRequest(BaseModel):
    wp_url: str = Field(..., max_length=2000)
    username: str = Field(..., max_length=200)
    app_password: str = Field(..., max_length=300)
    post_type: str = Field(default="posts", max_length=32, description="posts | pages | custom post type slug")
    status: str = Field(default="publish", max_length=16)
    limit: int = Field(default=200, ge=1, le=5000)
    per_page: int = Field(default=30, ge=1, le=100)
    goal: str = Field(default="Bổ sung FAQ + kết luận + CTA", max_length=400)
    max_words: int = Field(default=350, ge=120, le=800)
    dry_run: bool = Field(default=True, description="If true, do not update WP; preview only")


class WpUpdatePostRequest(BaseModel):
    site_id: str | None = None
    wp_site_id: str | None = None
    wp_url: str | None = Field(default="", max_length=2000)
    username: str | None = Field(default="", max_length=200)
    app_password: str | None = Field(default="", max_length=300)
    post_type: str = Field(default="posts", max_length=32)
    post_id: int = Field(..., ge=1)
    content_html: str = Field(..., min_length=1)
    dry_run: bool = Field(default=False)


@router.post("/update-post")
def wp_update_post(
    payload: WpUpdatePostRequest,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """
    Update a single WordPress post content (by ID) from the editor.
    """
    from app.services.wordpress_connection import resolve_wordpress_connection
    from app.services.wp_bulk_update import build_wp_session, normalize_wp_base_url, wp_auth_check, wp_update_post_content

    cred = resolve_wordpress_connection(
        user_id=int(current_user.id),
        site_id=str(payload.site_id or payload.wp_site_id or "").strip() or None,
        site_url=str(payload.wp_url or "").strip() or None,
    )
    wp_base = normalize_wp_base_url(cred["url"])
    username = cred["username"]
    app_password = cred["app_password"]
    post_type = (payload.post_type or "posts").strip() or "posts"
    post_id = int(payload.post_id)
    content_html = str(payload.content_html or "")

    session = None
    last_err = ""
    for strip_spaces in (True, False):
        s = build_wp_session(username, app_password, strip_spaces=strip_spaces)
        try:
            wp_base = wp_auth_check(session=s, wp_base=wp_base)
            session = s
            break
        except Exception as exc:
            last_err = str(exc)
            continue
    if session is None:
        hint = last_err[:180] if last_err else "HTTP 401"
        raise HTTPException(
            status_code=401,
            detail=f"Xác thực WordPress thất bại. {hint}. Kiểm tra Application Password tại Cài đặt → Xuất bản.",
        )

    if payload.dry_run:
        return JSONResponse(
            content={
                "ok": True,
                "dry_run": True,
                "wp_base": wp_base,
                "post_type": post_type,
                "post_id": post_id,
                "content_chars": len(content_html),
            }
        )

    try:
        data = wp_update_post_content(
            session=session,
            wp_base=wp_base,
            post_id=post_id,
            post_type=post_type,
            new_content_html=content_html,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:900]) from exc

    return JSONResponse(
        content={
            "ok": True,
            "dry_run": False,
            "post_id": data.get("id"),
            "status": data.get("status"),
            "link": data.get("link"),
            "edit_link": (data.get("_links", {}).get("self", [{}])[0] or {}).get("href", ""),
        }
    )


@router.post("/bulk-update/start")
def wp_bulk_update_start(
    payload: WpBulkUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """
    Create a persisted job and let the wp_bulk_worker pick it up.
    """
    ensure_job_schema()
    cleanup_expired(ttl_seconds=int(os.getenv("JOB_TTL_SECONDS", "1800")))
    mark_stale_jobs_failed(stale_seconds=int(os.getenv("JOB_WATCHDOG_SECONDS", "300")))
    mark_stale_queued_failed(stale_seconds=int(os.getenv("JOB_QUEUE_STALE_SECONDS", "90")))

    job_payload: dict[str, Any] = {**payload.model_dump(), "user_id": current_user.id}
    job = create_job(job_type="wp_bulk_update", message="Queued", payload=job_payload)
    st = get_job(job.job_id)
    return JSONResponse(
        content={
            "job_id": job.job_id,
            "state": st.state if st else job.state,
            "progress": st.progress if st else job.progress,
            "poll_url": f"/wp/bulk-update/job/{job.job_id}",
            "note": "Chạy worker: scripts/wp_bulk_worker.py (hoặc file .bat tương ứng).",
        }
    )


@router.get("/bulk-update/job/{job_id}")
def wp_bulk_update_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    ensure_job_schema()
    cleanup_expired(ttl_seconds=int(os.getenv("JOB_TTL_SECONDS", "1800")))
    mark_stale_jobs_failed(stale_seconds=int(os.getenv("JOB_WATCHDOG_SECONDS", "300")))
    mark_stale_queued_failed(stale_seconds=int(os.getenv("JOB_QUEUE_STALE_SECONDS", "90")))
    st = get_job_for_user(job_id, user_id=current_user.id)
    if not st:
        raise HTTPException(status_code=404, detail="Không tìm thấy job.")
    out: dict[str, Any] = {
        "job_id": st.job_id,
        "job_type": st.job_type,
        "state": st.state,
        "progress": st.progress,
        "message": st.message,
    }
    if st.state == "SUCCESS" and st.result is not None:
        out["result"] = st.result
    if st.state == "ERROR":
        out["error"] = st.error or "Unknown error"
    # Always avoid returning stored secrets (payload_json may contain them).
    return JSONResponse(content=out)


@router.get("/bulk-update/ping")
def wp_bulk_update_ping() -> JSONResponse:
    return JSONResponse(content={"ok": True, "ts": int(time.time())})

