"""Publish readiness checks for Content AI bulk publish center."""

from __future__ import annotations

from typing import Any

from app.services.content_ai_content_images import compute_project_image_status
from app.services.content_ai_project_store import _resolve_project_content, get_content_ai_project


def _field_errors(project: dict[str, Any] | None, *, require_image: bool) -> list[str]:
    if not project:
        return ["Không tìm thấy project."]
    errors: list[str] = []
    keyword = str(project.get("primary_keyword") or "").strip()
    title = str(project.get("custom_title") or project.get("title") or "").strip()
    meta = str(
        project.get("custom_description") or project.get("meta_description") or ""
    ).strip()
    slug = str(project.get("slug") or "").strip()
    content = _resolve_project_content(project)
    if not keyword:
        errors.append("Thiếu keyword.")
    if not title:
        errors.append("Thiếu title.")
    if not meta:
        errors.append("Thiếu meta description.")
    if not str(content or "").strip():
        errors.append("Thiếu content_html.")
    if not slug:
        errors.append("Thiếu slug.")
    if require_image:
        img_st = compute_project_image_status(project)
        if str(img_st.get("status") or "") != "ok":
            feat = img_st.get("featured") or {}
            if not str((feat or {}).get("url") or project.get("featured_image") or "").strip():
                errors.append("Thiếu ảnh featured.")
            elif img_st.get("error"):
                errors.append(str(img_st.get("error")))
    return errors


def check_project_publish_readiness(
    project_id: str,
    *,
    user_id: int,
    require_image: bool = False,
    require_category: bool = False,
    wp_category_id: int | None = None,
) -> dict[str, Any]:
    pid = str(project_id or "").strip()
    project = get_content_ai_project(pid, user_id=user_id) if pid else None
    keyword = str((project or {}).get("primary_keyword") or "")
    title = str((project or {}).get("custom_title") or (project or {}).get("title") or "")
    errors = _field_errors(project, require_image=require_image)
    cat_id = wp_category_id
    if cat_id is None and project:
        try:
            cat_id = int(project.get("wp_category_id") or 0) or None
        except (TypeError, ValueError):
            cat_id = None
    if require_category and not cat_id:
        errors.append("Thiếu category WordPress.")
    img_st = compute_project_image_status(project) if project else {"status": "none"}
    return {
        "project_id": pid,
        "keyword": keyword,
        "title": title,
        "ready": len(errors) == 0,
        "errors": errors,
        "image_status": img_st.get("status"),
        "wp_category_id": cat_id,
    }


def bulk_publish_readiness(
    project_ids: list[str],
    *,
    user_id: int,
    require_image: bool = False,
    require_category: bool = False,
    wp_category_id: int | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for pid in project_ids:
        pid = str(pid or "").strip()
        if not pid:
            continue
        items.append(
            check_project_publish_readiness(
                pid,
                user_id=user_id,
                require_image=require_image,
                require_category=require_category,
                wp_category_id=wp_category_id,
            )
        )
    ready_n = sum(1 for x in items if x.get("ready"))
    return {
        "ok": True,
        "items": items,
        "ready_count": ready_n,
        "error_count": len(items) - ready_n,
    }
