"""Publish / restore Content Auto Update qua WordPress REST API."""

from __future__ import annotations

from typing import Any

import requests
from fastapi import HTTPException

from app.services.content_backup import get_backup
from app.services.wp_site_connector import get_site_credentials, _wp_headers


def publish_update(
    *,
    user_id: int,
    site_id: str,
    backup_id: str,
    wp_id: int,
    post_type: str,
    title: str,
    content: str,
    excerpt: str,
    mode: str = "draft",
    slug: str = "",
    preserve_wp_status: bool = False,
    status: str | None = None,
) -> dict[str, Any]:
    """mode: draft | publish — backup required.

    preserve_wp_status=True: omit status so WordPress keeps the current status
    (unless an explicit status is provided).
    """
    backup = get_backup(backup_id, user_id)
    if not backup:
        raise HTTPException(status_code=400, detail="Chưa có backup — không thể publish.")

    if int(backup.get("wp_id") or 0) != int(wp_id):
        raise HTTPException(status_code=400, detail="backup không khớp bài viết.")

    cred = get_site_credentials(site_id, user_id)
    resource = "pages" if post_type == "page" else "posts"
    base = cred["url"]
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])

    body: dict[str, Any] = {
        "title": title,
        "content": content,
        "excerpt": excerpt,
    }
    if status is not None and str(status).strip():
        body["status"] = str(status).strip()
    elif not preserve_wp_status:
        body["status"] = "publish" if str(mode).lower() == "publish" else "draft"
    if slug and str(slug).strip():
        body["slug"] = str(slug).strip()

    url = f"{base}/wp-json/wp/v2/{resource}/{int(wp_id)}"
    try:
        r = requests.post(url, headers=headers, auth=auth, json=body, timeout=60)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Không gọi được WordPress: {exc}") from exc

    if r.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Publish thất bại HTTP {r.status_code}: {(r.text or '')[:400]}",
        )

    try:
        data = r.json()
    except ValueError:
        data = {}

    resolved_status = (
        data.get("status")
        or body.get("status")
        or (backup.get("old_status") if preserve_wp_status else None)
        or mode
    )
    modified_gmt = str(data.get("modified_gmt") or "").strip()
    modified_local = str(data.get("modified") or "").strip()
    return {
        "ok": True,
        "wp_id": wp_id,
        "status": resolved_status,
        "link": data.get("link"),
        "backup_id": backup_id,
        "mode": mode,
        "modified": modified_gmt or modified_local,
        "modified_gmt": modified_gmt,
        "modified_local": modified_local,
    }


def restore_from_backup(*, user_id: int, backup_id: str) -> dict[str, Any]:
    backup = get_backup(backup_id, user_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Không tìm thấy backup.")

    site_id = str(backup.get("site_id") or "")
    cred = get_site_credentials(site_id, user_id)
    post_type = str(backup.get("post_type") or "post")
    resource = "pages" if post_type == "page" else "posts"
    wp_id = int(backup.get("wp_id") or 0)
    base = cred["url"]
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])

    body = {
        "title": backup.get("old_title") or "",
        "content": backup.get("old_content") or "",
        "excerpt": backup.get("old_excerpt") or "",
        "status": backup.get("old_status") or "draft",
    }
    url = f"{base}/wp-json/wp/v2/{resource}/{wp_id}"
    try:
        r = requests.post(url, headers=headers, auth=auth, json=body, timeout=60)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Restore thất bại: {exc}") from exc

    if r.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Restore HTTP {r.status_code}: {(r.text or '')[:400]}",
        )

    try:
        data = r.json()
    except ValueError:
        data = {}
    return {
        "ok": True,
        "backup_id": backup_id,
        "wp_id": wp_id,
        "status": data.get("status") or backup.get("old_status"),
        "link": data.get("link") or backup.get("post_url"),
        "message": "Đã khôi phục bản cũ lên WordPress.",
    }
