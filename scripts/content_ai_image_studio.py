"""AI Visual Content Studio — preview generation & selective insert (Content AI)."""

from __future__ import annotations

import re
from typing import Any

from app.services.content_ai_content_images import (
    inject_images_into_content_html,
    prepare_content_html_for_images,
    suggest_image_alt_text,
    suggest_image_caption,
)
from app.services.content_ai_project_store import (
    get_content_ai_project,
    update_content_ai_project_fields,
)
from app.services.content_ai_thumbnail import generate_openai_image_variants
from app.services.image_prompt_engine import (
    build_professional_image_prompt,
    build_studio_context_from_project,
    extract_h2_list,
    section_snippet_for_h2,
)
from app.services.image_style_presets import list_style_presets, normalize_style_preset


def _clamp_count(n: int) -> int:
    return max(2, min(int(n or 3), 4))


def _resolve_h2_targets(
    h2s: list[str],
    *,
    h2_headings: list[str] | None = None,
    h2_indices: list[int] | None = None,
    section_heading: str = "",
    h2_index: int | None = None,
) -> list[tuple[str, int | None]]:
    """Return list of (heading, index) for prompt generation."""
    selected: list[tuple[str, int | None]] = []
    if h2_headings:
        for raw in h2_headings:
            h = str(raw or "").strip()
            if not h:
                continue
            try:
                idx = h2s.index(h)
            except ValueError:
                idx = None
            if (h, idx) not in selected:
                selected.append((h, idx))
    if not selected and h2_indices:
        for idx in h2_indices:
            i = int(idx)
            if 0 <= i < len(h2s):
                pair = (h2s[i], i)
                if pair not in selected:
                    selected.append(pair)
    if not selected:
        h2 = str(section_heading or "").strip()
        if h2:
            try:
                selected.append((h2, h2s.index(h2)))
            except ValueError:
                selected.append((h2, None))
        elif h2_index is not None and 0 <= int(h2_index) < len(h2s):
            i = int(h2_index)
            selected.append((h2s[i], i))
        elif h2s:
            selected.append((h2s[0], 0))
        else:
            selected.append(("", None))
    return selected


def generate_professional_previews(
    *,
    user_id: int,
    title: str = "",
    primary_keyword: str = "",
    secondary_keywords: list[str] | None = None,
    content_html: str = "",
    outline_content: str = "",
    section_heading: str = "",
    h2_index: int | None = None,
    h2_headings: list[str] | None = None,
    h2_indices: list[int] | None = None,
    target_audience: str = "",
    industry: str = "",
    brand_name: str = "",
    brand_tone: str = "professional",
    image_type: str = "inline_h2",
    style_preset: str = "seo_3d_premium",
    aspect_ratio: str = "16:9",
    custom_width: int | None = None,
    custom_height: int | None = None,
    count: int = 3,
    include_text: bool = False,
    text_hint: str = "",
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Generate 2–4 preview images without modifying project content.
    """
    ctx: dict[str, Any] = {
        "title": title,
        "primary_keyword": primary_keyword,
        "secondary_keywords": secondary_keywords or [],
        "content_html": content_html,
        "outline_content": outline_content,
        "target_audience": target_audience,
        "industry": industry,
        "brand_name": brand_name,
    }
    if project_id:
        row = get_content_ai_project(project_id, user_id=user_id)
        if not row:
            raise ValueError("Không tìm thấy dự án.")
        merged = build_studio_context_from_project(row)
        for k, v in ctx.items():
            if not str(ctx.get(k) or "").strip() and v:
                ctx[k] = v
        if not str(title or "").strip():
            ctx["title"] = merged["title"]
        if not str(primary_keyword or "").strip():
            ctx["primary_keyword"] = merged["primary_keyword"]
        if not str(content_html or "").strip():
            ctx["content_html"] = merged["content_html"]
        if not str(outline_content or "").strip():
            ctx["outline_content"] = merged["outline_content"]

    pk = str(ctx.get("primary_keyword") or "").strip()
    if not pk:
        raise ValueError("Cần từ khóa chính để tạo ảnh AI.")

    html = str(ctx.get("content_html") or "")
    outline = str(ctx.get("outline_content") or "")
    h2s = extract_h2_list(html, outline)
    h2_targets = _resolve_h2_targets(
        h2s,
        h2_headings=h2_headings,
        h2_indices=h2_indices,
        section_heading=section_heading,
        h2_index=h2_index,
    )

    ar_label = str(aspect_ratio or "16:9")
    use_custom = str(aspect_ratio or "").strip().lower() in ("custom", "tu_chinh", "tùy chỉnh")
    cw = int(custom_width) if custom_width else None
    ch = int(custom_height) if custom_height else None
    if use_custom and cw and ch:
        ar_label = f"{cw}x{ch}"

    n = _clamp_count(count)
    preset = normalize_style_preset(style_preset)
    prompts: list[str] = []
    slot_meta: list[dict[str, Any]] = []
    for i in range(n):
        h2, h2_idx = h2_targets[i % len(h2_targets)]
        section_summary = section_snippet_for_h2(html, h2) if h2 else ""
        prompts.append(
            build_professional_image_prompt(
                title=str(ctx.get("title") or ""),
                primary_keyword=pk,
                secondary_keywords=ctx.get("secondary_keywords"),
                content_html=html,
                outline_content=outline,
                section_heading=h2,
                section_summary=section_summary,
                target_audience=str(ctx.get("target_audience") or ""),
                industry=str(ctx.get("industry") or ""),
                brand_name=str(ctx.get("brand_name") or ""),
                brand_tone=brand_tone,
                image_type=image_type,
                style_preset=preset,
                aspect_ratio=ar_label,
                include_text=include_text,
                text_hint=text_hint,
                variation_index=i,
            )
        )
        slot_meta.append({"section_heading": h2, "h2_index": h2_idx})

    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", pk)[:36].strip("-") or "studio"
    try:
        variants = generate_openai_image_variants(
            prompts=prompts,
            aspect_ratio=aspect_ratio,
            stem=f"studio-{stem}",
            custom_width=cw if use_custom else None,
            custom_height=ch if use_custom else None,
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Tạo ảnh AI thất bại: {exc}") from exc

    previews = []
    for vi, v in enumerate(variants):
        meta = slot_meta[vi] if vi < len(slot_meta) else slot_meta[0] if slot_meta else {}
        h2 = str(meta.get("section_heading") or "")
        summary = section_snippet_for_h2(html, h2) if h2 else ""
        img_ctx = {"heading": h2, "content": summary}
        previews.append(
            {
                "url": v["url"],
                "index": v.get("index", vi),
                "prompt": v.get("prompt", ""),
                "alt": suggest_image_alt_text(img_ctx, pk),
                "section_heading": h2,
                "h2_index": meta.get("h2_index"),
            }
        )

    h2_labels = [t[0] for t in h2_targets if t[0]]
    msg_extra = ""
    if len(h2_labels) > 1:
        msg_extra = f" ({len(h2_labels)} mục H2: {', '.join(h2_labels[:3])}{'…' if len(h2_labels) > 3 else ''})"

    return {
        "ok": True,
        "previews": previews,
        "prompts": prompts,
        "style_preset": preset,
        "aspect_ratio": ar_label,
        "image_type": image_type,
        "section_headings": h2_labels,
        "h2_indices": [t[1] for t in h2_targets if t[1] is not None],
        "count": len(previews),
        "message": f"Đã tạo {len(previews)} ảnh preview{msg_extra} — chọn ảnh rồi bấm Chèn vào bài hoặc Featured.",
    }


def insert_selected_image(
    *,
    user_id: int,
    url: str,
    mode: str = "inline",
    project_id: str | None = None,
    content_html: str = "",
    title: str = "",
    primary_keyword: str = "",
    section_heading: str = "",
    h2_index: int | None = None,
    alt: str = "",
    caption: str = "",
) -> dict[str, Any]:
    """
    Insert a user-selected preview URL into content or set featured_image.
    mode: inline | featured | append
    """
    img_url = str(url or "").strip()
    if not img_url:
        raise ValueError("Thiếu URL ảnh.")
    mode_l = str(mode or "inline").strip().lower()
    if mode_l not in ("inline", "featured", "append"):
        mode_l = "inline"

    project: dict[str, Any] | None = None
    if project_id:
        project = get_content_ai_project(project_id, user_id=user_id)
        if not project:
            raise ValueError("Không tìm thấy dự án.")

    pk = str(primary_keyword or (project or {}).get("primary_keyword") or "").strip()
    ttl = str(title or (project or {}).get("title") or "").strip()
    html = str(content_html or (project or {}).get("content") or "")
    outline = str((project or {}).get("outline_content") or "")
    html = prepare_content_html_for_images(html, outline)

    img_ctx = {"heading": section_heading, "content": ""}
    alt_text = str(alt or "").strip() or suggest_image_alt_text(img_ctx, pk)
    cap = str(caption or "").strip() or suggest_image_caption(img_ctx)

    updates: dict[str, Any] = {}
    new_html = html

    if mode_l == "featured":
        updates["featured_image"] = img_url
    elif mode_l == "append":
        from app.services.content_ai_content_images import _figure_snippet

        new_html = (html or "") + _figure_snippet(img_url, alt_text, cap)
        updates["content"] = new_html
    else:
        insert: dict[str, Any] = {
            "url": img_url,
            "alt": alt_text,
            "caption": cap,
        }
        if h2_index is not None:
            insert["h2_index"] = int(h2_index)
        elif section_heading:
            h2s = extract_h2_list(html, outline)
            try:
                insert["h2_index"] = h2s.index(section_heading.strip())
            except ValueError:
                insert["h2_index"] = 0
        else:
            insert["h2_index"] = 0
        new_html = inject_images_into_content_html(html, [insert])
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
        "mode": mode_l,
        "url": img_url,
        "content": updates.get("content", html),
        "featured_image": updates.get("featured_image") or (project or {}).get("featured_image") or "",
        "gallery_images": updates.get("gallery_images") or gallery,
        "alt": alt_text,
        "project": updated_project,
        "project_id": project_id,
    }


def studio_catalog() -> dict[str, Any]:
    return {
        "style_presets": list_style_presets(),
        "image_types": [
            {"id": "hero_featured", "label_vi": "Ảnh đại diện (Featured)"},
            {"id": "inline_h2", "label_vi": "Minh họa trong bài (H2)"},
            {"id": "thumbnail", "label_vi": "Thumbnail / Preview"},
            {"id": "social_cover", "label_vi": "Ảnh bìa social"},
            {"id": "ads_creative", "label_vi": "Creative quảng cáo"},
        ],
        "aspect_ratios": [
            {"id": "16:9", "label_vi": "16:9 Ngang (blog)"},
            {"id": "1:1", "label_vi": "1:1 Vuông"},
            {"id": "9:16", "label_vi": "9:16 Dọc"},
            {"id": "4:3", "label_vi": "4:3"},
            {"id": "custom", "label_vi": "Tùy chỉnh (px)"},
        ],
        "brand_tones": [
            {"id": "professional", "label_vi": "Chuyên nghiệp"},
            {"id": "friendly", "label_vi": "Thân thiện"},
            {"id": "bold", "label_vi": "Nổi bật"},
            {"id": "luxury", "label_vi": "Cao cấp"},
            {"id": "tech", "label_vi": "Công nghệ"},
            {"id": "neutral", "label_vi": "Trung tính"},
        ],
    }
