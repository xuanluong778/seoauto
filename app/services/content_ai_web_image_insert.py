"""Tìm ảnh Google/Web và chèn vào bài Content AI."""

from __future__ import annotations

import re
from typing import Any

import requests

from app.services.content_ai_content_images import (
    inject_image_smart_into_content_html,
    prepare_content_html_for_images,
)
from app.services.content_ai_image_output import (
    WEB_IMAGE_MIN_PX,
    build_seo_image_alt,
    build_seo_image_filename,
    figure_snippet_seo,
    list_web_image_size_presets,
    normalize_output_format,
    resolve_web_image_dimensions,
    save_content_ai_image,
)
from app.services.content_ai_project_store import (
    get_content_ai_project,
    update_content_ai_project_fields,
)
from app.services.content_image_context import build_image_search_query_for_section
from app.services.web_image_search import search_web_images


def web_image_catalog() -> dict[str, Any]:
    return {
        "size_presets": list_web_image_size_presets(),
        "output_formats": [
            {"id": "webp", "label_vi": "WEBP (nén)"},
            {"id": "jpeg", "label_vi": "JPEG"},
            {"id": "png", "label_vi": "PNG"},
        ],
        "query_modes": [
            {"id": "keyword", "label_vi": "Từ khóa chính"},
            {"id": "title", "label_vi": "Tiêu đề bài"},
            {"id": "h2", "label_vi": "Heading H2"},
            {"id": "custom", "label_vi": "Từ khóa tùy chỉnh"},
        ],
    }


def build_web_image_search_query(
    *,
    query_mode: str = "keyword",
    primary_keyword: str = "",
    title: str = "",
    h2_heading: str = "",
    custom_query: str = "",
) -> str:
    custom = str(custom_query or "").strip()
    if custom:
        return custom
    mode = str(query_mode or "keyword").strip().lower()
    pk = str(primary_keyword or "").strip()
    ttl = str(title or "").strip()
    h2 = str(h2_heading or "").strip()
    if mode == "title":
        return ttl or pk
    if mode == "h2":
        if h2:
            return build_image_search_query_for_section(
                section_heading=h2,
                section_content="",
                main_keyword=pk or ttl,
            )
        return pk or ttl
    return pk or ttl or h2


def search_web_images_for_content(
    *,
    query_mode: str = "keyword",
    primary_keyword: str = "",
    title: str = "",
    h2_heading: str = "",
    custom_query: str = "",
    num: int = 12,
) -> dict[str, Any]:
    q = build_web_image_search_query(
        query_mode=query_mode,
        primary_keyword=primary_keyword,
        title=title,
        h2_heading=h2_heading,
        custom_query=custom_query,
    )
    if not q:
        raise ValueError("Cần từ khóa, tiêu đề hoặc H2 để tìm ảnh.")
    n = max(1, min(int(num or 12), 20))
    items, source = search_web_images(q=q, num=n)
    return {
        "ok": True,
        "query": q,
        "query_mode": query_mode,
        "items": items,
        "source": source,
        "count": len(items),
    }


def download_remote_image_bytes(src: str) -> bytes:
    url = str(src or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL ảnh không hợp lệ.")
    try:
        r = requests.get(
            url,
            timeout=25,
            stream=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
    except Exception as exc:
        raise ValueError(f"Không tải được ảnh: {exc}") from exc
    if r.status_code != 200:
        raise ValueError(f"Không tải được ảnh (HTTP {r.status_code}).")
    ctype = str(r.headers.get("content-type") or "").lower()
    if "image" not in ctype and not re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.I):
        raise ValueError(f"URL không trả về ảnh (content-type={ctype or 'unknown'}).")
    max_bytes = 8 * 1024 * 1024
    data = b""
    for chunk in r.iter_content(chunk_size=65536):
        if not chunk:
            continue
        data += chunk
        if len(data) > max_bytes:
            raise ValueError("Ảnh quá lớn (giới hạn ~8MB).")
    if len(data) < 400:
        raise ValueError("File ảnh tải về quá nhỏ hoặc không hợp lệ.")
    return data


def import_web_image_processed(
    remote_url: str,
    *,
    primary_keyword: str = "",
    section_heading: str = "",
    size_preset: str = "",
    target_width: int | None = None,
    target_height: int | None = None,
    output_format: str = "webp",
) -> dict[str, Any]:
    """Tải ảnh về server, resize, đổi tên SEO."""
    w, h = resolve_web_image_dimensions(
        size_preset=size_preset,
        target_width=target_width,
        target_height=target_height,
    )
    fmt = normalize_output_format(output_format or "webp")
    raw = download_remote_image_bytes(remote_url)
    filename = build_seo_image_filename(
        primary_keyword or "anh-web",
        section_heading=section_heading,
        output_format=fmt,
    )
    local_url = save_content_ai_image(
        raw,
        filename=filename,
        output_format=fmt,
        width=w,
        height=h,
        min_px=WEB_IMAGE_MIN_PX if (w and h) else None,
    )

    return {
        "url": local_url,
        "filename": filename,
        "width": w,
        "height": h,
        "output_format": fmt,
        "remote_url": remote_url,
    }


def insert_web_image_into_content(
    *,
    user_id: int,
    remote_url: str,
    content_html: str = "",
    outline_content: str = "",
    title: str = "",
    primary_keyword: str = "",
    section_heading: str = "",
    h2_index: int | None = None,
    project_id: str | None = None,
    size_preset: str = "",
    target_width: int | None = None,
    target_height: int | None = None,
    output_format: str = "webp",
    download_to_server: bool = True,
    mode: str = "inline",
    alt: str = "",
    caption: str = "",
) -> dict[str, Any]:
    pk = str(primary_keyword or "").strip()
    h2 = str(section_heading or "").strip()
    mode_l = str(mode or "inline").strip().lower()
    if mode_l not in ("inline", "append", "featured"):
        mode_l = "inline"

    w, h = resolve_web_image_dimensions(
        size_preset=size_preset,
        target_width=target_width,
        target_height=target_height,
    )

    if download_to_server:
        imported = import_web_image_processed(
            remote_url,
            primary_keyword=pk,
            section_heading=h2,
            size_preset=size_preset,
            target_width=target_width,
            target_height=target_height,
            output_format=output_format,
        )
        img_url = imported["url"]
        if w is None and imported.get("width"):
            w, h = imported.get("width"), imported.get("height")
    else:
        img_url = str(remote_url or "").strip()
        if not img_url:
            raise ValueError("Thiếu URL ảnh.")

    alt_text = str(alt or "").strip() or build_seo_image_alt(
        primary_keyword=pk,
        section_heading=h2,
        title=title,
    )

    project: dict[str, Any] | None = None
    if project_id:
        project = get_content_ai_project(project_id, user_id=user_id)
        if not project:
            raise ValueError("Không tìm thấy dự án.")
        if not pk:
            pk = str(project.get("primary_keyword") or "").strip()
        if not title:
            title = str(project.get("title") or "").strip()

    html = str(content_html or (project or {}).get("content") or "")
    outline = str(outline_content or (project or {}).get("outline_content") or "")
    html = prepare_content_html_for_images(html, outline)

    updates: dict[str, Any] = {}
    placement_meta: dict[str, Any] = {}

    if mode_l == "featured":
        updates["featured_image"] = img_url
    elif mode_l == "append":
        new_html = (html or "") + figure_snippet_seo(
            img_url, alt_text, width=w, height=h, caption=caption
        )
        updates["content"] = new_html
        placement_meta = {"placement": "append"}
    else:
        insert = {
            "url": img_url,
            "alt": alt_text,
            "caption": caption,
            "section_heading": h2,
            "h2_index": h2_index,
            "width": w,
            "height": h,
        }
        new_html, placement_meta = inject_image_smart_into_content_html(
            html, insert, outline=outline
        )
        updates["content"] = new_html

    gallery: list[str] = []
    if project:
        raw_g = project.get("gallery_images")
        if isinstance(raw_g, list):
            gallery = [str(x) for x in raw_g if str(x).strip()]
        if img_url not in gallery:
            gallery.append(img_url)
        updates["gallery_images"] = gallery[-20:]

    updated_project = None
    if project_id and updates:
        updated_project = update_content_ai_project_fields(project_id, updates, user_id=user_id)

    return {
        "ok": True,
        "url": img_url,
        "alt": alt_text,
        "width": w,
        "height": h,
        "mode": mode_l,
        "placement": placement_meta,
        "content": updates.get("content", html),
        "featured_image": updates.get("featured_image") or (project or {}).get("featured_image") or "",
        "gallery_images": updates.get("gallery_images") or gallery,
        "project": updated_project,
        "project_id": project_id,
    }
