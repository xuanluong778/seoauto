"""Content AI — tự lấy & chèn ảnh theo ngữ cảnh (bulk + single)."""

from __future__ import annotations

import re
from typing import Any, Callable

from app.services.content_ai_image_finder import find_best_for_slot
from app.services.content_ai_image_inserter import (
    count_content_images,
    extract_h2_headings,
    inject_images_into_content_html,
    prepare_content_html_for_images,
)
from app.services.content_ai_image_optimizer import optimize_remote_image
from app.services.content_ai_image_rules import (
    inline_image_count_for_word_count,
    resolve_image_orientation,
)
from app.services.content_ai_project_store import _resolve_project_content
from app.services.content_image_context import (
    choose_image_placement,
    extract_image_contexts_from_article,
    get_default_content_ai_image_style,
    suggest_image_alt_text,
    suggest_image_caption,
)

MAX_INLINE_IMAGES = 4
MIN_WORDS_FOR_INLINE = 250


def _strip_html_text(html: str) -> str:
    from app.services.content_ai_image_inserter import _strip_html_text as _s

    return _s(html)


def _image_strategy() -> str:
    import os
    from pathlib import Path

    from dotenv import dotenv_values

    env = Path(__file__).resolve().parents[2] / "env.local"
    raw = (os.getenv("CONTENT_AI_IMAGE_STRATEGY") or "").strip().lower()
    if not raw and env.is_file():
        raw = str((dotenv_values(env) or {}).get("CONTENT_AI_IMAGE_STRATEGY") or "").strip().lower()
    if raw in ("ai", "web", "hybrid"):
        return raw
    return "web"


def _resolve_strategy(image_strategy_override: str | None = None) -> str:
    raw = str(image_strategy_override or "").strip().lower()
    if raw in ("web", "ai", "hybrid"):
        return raw
    return _image_strategy()


def _slot_orientation(
    *,
    featured: bool,
    industry: str,
    keyword: str,
    brand_name: str,
    section_heading: str,
) -> str:
    if featured:
        return "landscape"
    resolved = resolve_image_orientation(
        industry=industry,
        keyword=keyword,
        brand_name=brand_name,
        section_heading=section_heading,
    )
    return resolved if resolved != "any" else "landscape"


def _generate_slot_image_ai(
    *,
    primary_keyword: str,
    title: str,
    section_heading: str,
    section_content: str = "",
    brand_name: str = "",
    target_audience: str = "",
    industry: str = "",
    image_style: str = "",
    stem: str,
    orientation: str = "any",
    user_id: int | None = None,
    project_id: str | None = None,
    db=None,
    user=None,
) -> tuple[str, str, dict[str, Any]]:
    from app.services.content_ai_openrouter_images import generate_image_bytes
    from app.services.content_image_context import build_seo_image_generation_prompt
    from app.services.content_ai_image_optimizer import save_optimized_image

    style = image_style or get_default_content_ai_image_style()
    prompt = build_seo_image_generation_prompt(
        main_keyword=primary_keyword,
        article_title=title,
        section_heading=section_heading or title,
        section_summary=section_content,
        brand_name=brand_name,
        target_audience=target_audience,
        industry=industry,
        image_style=style,
        language="vi",
        include_brand_logo=False,
    )
    image_model = None
    if db is not None and user is not None:
        from app.services.cost_control.module_gates import content_ai_llm_gate
        from app.services.llm_content_writer import load_llm_config_admin

        with content_ai_llm_gate(
            db,
            user,
            action="image_ai_slot",
            field="content",
            use_system_llm=True,
            llm_cfg=load_llm_config_admin(),
            feature_key="image_generate",
            skip_credit_check=True,
        ):
            image_bytes = generate_image_bytes(prompt=prompt)
    else:
        image_bytes = generate_image_bytes(prompt=prompt)
    orient = orientation if orientation in ("landscape", "portrait") else (
        "landscape" if "feat" in stem else "landscape"
    )
    opt = save_optimized_image(
        image_bytes,
        stem=stem,
        orientation=orient,
        prefer_landscape_crop=orient == "landscape",
        user_id=user_id,
        project_id=project_id,
    )
    if db is not None and user is not None:
        from app.services.content_ai_entitlement import record_content_ai_usage

        record_content_ai_usage(db, user, "image_generate", quantity=1)
    meta = {
        "provider": "openrouter_image",
        "source_url": "",
        "license": "AI generated",
        "author": "",
        "filename": opt.filename,
        "alt": "",
        "caption": "",
        "role": "featured" if "feat" in stem else "inline",
        "bytes": opt.bytes_size,
        "width": opt.width,
        "height": opt.height,
    }
    return opt.local_url, prompt[:200], meta


def _pick_and_download_for_slot(
    *,
    primary_keyword: str,
    title: str,
    section_heading: str,
    section_content: str = "",
    outline: str = "",
    brand_name: str = "",
    target_audience: str = "",
    industry: str = "",
    image_style: str = "",
    stem: str,
    used_links: set[str],
    used_locals: set[str],
    user_id: int | None = None,
    project_id: str | None = None,
    featured: bool = False,
    image_strategy_override: str | None = None,
    on_status: Callable[[str], None] | None = None,
    db=None,
    user=None,
) -> tuple[str, str, str, str, dict[str, Any]]:
    """Trả (local_url, remote_link, search_query, source, metadata)."""
    strategy = _resolve_strategy(image_strategy_override)
    orientation = _slot_orientation(
        featured=featured,
        industry=industry,
        keyword=primary_keyword,
        brand_name=brand_name,
        section_heading=section_heading,
    )
    query = ""

    if strategy != "ai":
        if on_status:
            on_status("Đang tìm ảnh…")
        picked, source, query = find_best_for_slot(
            keyword=primary_keyword,
            title=title,
            section_heading=section_heading,
            section_content=section_content,
            outline=outline,
            brand_name=brand_name,
            orientation=orientation,
            db=db,
            user=user,
        )
        if picked:
            link = str(picked.get("link") or "")
            if link in used_links:
                picked = None
            if picked and link:
                try:
                    if on_status:
                        on_status("Đang tối ưu ảnh…")
                    opt = optimize_remote_image(
                        link,
                        stem=stem,
                        orientation=orientation,
                        prefer_landscape_crop=orientation == "landscape",
                        user_id=user_id,
                        project_id=project_id,
                    )
                    if opt.local_url in used_locals:
                        return "", "", query, source or "", {}
                    ctx = {"heading": section_heading, "content": section_content}
                    meta = {
                        "provider": picked.get("provider") or source,
                        "source_url": picked.get("source_url") or link,
                        "license": picked.get("license") or "",
                        "author": picked.get("author") or "",
                        "filename": opt.filename,
                        "alt": suggest_image_alt_text(ctx, primary_keyword),
                        "caption": suggest_image_caption(ctx),
                        "role": "featured" if featured else "inline",
                        "bytes": opt.bytes_size,
                        "width": opt.width,
                        "height": opt.height,
                        "query": query,
                    }
                    return opt.local_url, link, query, source or "licensed_api", meta
                except ValueError:
                    pass

    if strategy == "web":
        return "", "", query, "", {}

    try:
        if on_status:
            on_status("Đang tạo ảnh AI…")
        local_url, prompt_used, meta = _generate_slot_image_ai(
            primary_keyword=primary_keyword,
            title=title,
            section_heading=section_heading,
            section_content=section_content,
            brand_name=brand_name,
            target_audience=target_audience,
            industry=industry,
            image_style=image_style,
            stem=stem,
            orientation=orientation,
            user_id=user_id,
            project_id=project_id,
            db=db,
            user=user,
        )
        if local_url and local_url not in used_locals:
            meta["query"] = prompt_used
            return local_url, "openrouter-generated", prompt_used, "openrouter_image", meta
    except ValueError as exc:
        if strategy == "ai":
            raise ValueError(str(exc)) from exc
    return "", "", query, "", {}


def enrich_project_with_context_images(
    project: dict[str, Any],
    *,
    max_inline: int | None = None,
    word_count_target: int | None = None,
    update_featured: bool = True,
    require_featured: bool = True,
    force: bool = False,
    image_strategy_override: str | None = None,
    on_status: Callable[[str], None] | None = None,
    db=None,
    user=None,
) -> dict[str, Any]:
    pk = str(project.get("primary_keyword") or "").strip()
    title = str(project.get("title") or project.get("custom_title") or "").strip()
    outline = str(project.get("outline_content") or project.get("custom_outline") or "").strip()
    secondary = project.get("secondary_keywords") or []
    if not isinstance(secondary, list):
        secondary = []
    raw_content = _resolve_project_content(project)
    content = prepare_content_html_for_images(raw_content, outline)
    word_count = len(_strip_html_text(content).split()) if content else 0
    if max_inline is None:
        wc_basis = int(word_count_target or word_count or 0)
        max_slots = inline_image_count_for_word_count(wc_basis)
    else:
        max_slots = max(0, min(int(max_inline), 6))

    if not pk:
        raise ValueError("Cần từ khóa chính để tìm ảnh đúng ngữ cảnh.")

    brand_name = str(project.get("brand_name") or project.get("target_website") or "").strip()
    target_audience = str(project.get("target_audience") or "").strip()
    industry = str(project.get("industry") or "").strip()
    image_style = get_default_content_ai_image_style()
    intro_content = _strip_html_text(content)[:500]

    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", pk or title or "content-img")[:40].strip("-") or "content-img"
    used_links: set[str] = set()
    used_locals: set[str] = set()
    gallery: list[str] = list(project.get("gallery_images") or [])
    if not isinstance(gallery, list):
        gallery = []
    image_assets: list[dict[str, Any]] = list(project.get("image_assets") or [])
    if not isinstance(image_assets, list):
        image_assets = []

    existing_featured = str(project.get("featured_image") or "").strip()
    featured_local = existing_featured if existing_featured and not force else ""
    used_query = ""
    image_source = "licensed_api"
    owner_id = int(project.get("user_id") or 0) or None
    project_id = str(project.get("id") or "").strip() or None

    if update_featured and not featured_local:
        local_url, link, used_query, src, meta = _pick_and_download_for_slot(
            primary_keyword=pk,
            title=title,
            section_heading=title or pk,
            section_content=intro_content,
            outline=outline,
            brand_name=brand_name,
            target_audience=target_audience,
            industry=industry,
            image_style=image_style,
            stem=f"{stem}-feat",
            used_links=used_links,
            used_locals=used_locals,
            user_id=owner_id,
            project_id=project_id,
            featured=True,
            image_strategy_override=image_strategy_override,
            on_status=on_status,
            db=db,
            user=user,
        )
        if src:
            image_source = src
        if local_url:
            featured_local = local_url
            if link and link not in ("openai-generated", "openrouter-generated"):
                used_links.add(link)
            if local_url not in gallery:
                gallery.insert(0, local_url)
            if meta:
                image_assets.append({**meta, "url": local_url, "role": "featured"})
        if not featured_local and not existing_featured and require_featured:
            raise ValueError(
                "Không tìm được ảnh đại diện phù hợp. Cấu hình GOOGLE_CSE hoặc PEXELS/UNSPLASH/PIXABAY trong env.local."
            )
    elif update_featured and featured_local and featured_local not in gallery:
        gallery.insert(0, featured_local)

    inline_inserts: list[dict[str, Any]] = []
    existing_imgs = count_content_images(content)
    h2s = extract_h2_headings(content, outline)
    need_inline = force or existing_imgs < max(1, max_slots)

    if content and word_count >= MIN_WORDS_FOR_INLINE and need_inline and max_slots > 0:
        placements = choose_image_placement(article_outline=outline, article_html=content, max_images=max_slots)
        if placements:
            for pi, placement in enumerate(placements):
                ctx = placement.get("context") or {}
                h2 = str(ctx.get("heading") or "").strip()
                section_body = str(ctx.get("content") or "").strip()
                h2_index = int(placement.get("h2_index") or pi)
                local_url, link, q_used, src, meta = _pick_and_download_for_slot(
                    primary_keyword=pk,
                    title=title,
                    section_heading=h2,
                    section_content=section_body,
                    outline=outline,
                    brand_name=brand_name,
                    target_audience=target_audience,
                    industry=industry,
                    image_style=image_style,
                    stem=f"{stem}-s{pi + 1}",
                    used_links=used_links,
                    used_locals=used_locals,
                    user_id=owner_id,
                    project_id=project_id,
                    featured=False,
                    image_strategy_override=image_strategy_override,
                    on_status=on_status,
                    db=db,
                    user=user,
                )
                if q_used and not used_query:
                    used_query = q_used
                if src:
                    image_source = src
                if local_url:
                    if link and link not in ("openai-generated", "openrouter-generated"):
                        used_links.add(link)
                    used_locals.add(local_url)
                    if local_url not in gallery:
                        gallery.append(local_url)
                    alt = meta.get("alt") or suggest_image_alt_text(ctx, pk)
                    caption = meta.get("caption") or suggest_image_caption(ctx)
                    if meta:
                        image_assets.append({**meta, "url": local_url, "role": "inline"})
                    inline_inserts.append(
                        {
                            "h2_index": h2_index,
                            "url": local_url,
                            "alt": alt,
                            "caption": caption,
                            "meta": meta,
                        }
                    )
        elif h2s:
            section_map = {
                str(c.get("heading") or "").strip().lower(): c
                for c in extract_image_contexts_from_article(article_html=content, outline=outline)
            }
            for hi, h2 in enumerate(h2s[:max_slots]):
                ctx = section_map.get(h2.strip().lower()) or {"heading": h2, "content": ""}
                section_body = str(ctx.get("content") or "").strip()
                local_url, link, q_used, src, meta = _pick_and_download_for_slot(
                    primary_keyword=pk,
                    title=title,
                    section_heading=h2,
                    section_content=section_body,
                    outline=outline,
                    brand_name=brand_name,
                    target_audience=target_audience,
                    industry=industry,
                    image_style=image_style,
                    stem=f"{stem}-s{hi + 1}",
                    used_links=used_links,
                    used_locals=used_locals,
                    user_id=owner_id,
                    project_id=project_id,
                    image_strategy_override=image_strategy_override,
                    on_status=on_status,
                    db=db,
                    user=user,
                )
                if q_used and not used_query:
                    used_query = q_used
                if src:
                    image_source = src
                if local_url:
                    if link and link not in ("openai-generated", "openrouter-generated"):
                        used_links.add(link)
                    used_locals.add(local_url)
                    if local_url not in gallery:
                        gallery.append(local_url)
                    if meta:
                        image_assets.append({**meta, "url": local_url, "role": "inline"})
                    inline_inserts.append(
                        {
                            "h2_index": hi,
                            "url": local_url,
                            "alt": meta.get("alt") or suggest_image_alt_text(ctx, pk),
                            "caption": meta.get("caption") or suggest_image_caption(ctx),
                            "meta": meta,
                        }
                    )

    if inline_inserts and on_status:
        on_status("Đang chèn ảnh vào bài…")
    new_content = inject_images_into_content_html(content, inline_inserts) if inline_inserts else content
    from app.services.content_ai_image_guard import repair_content_html_images

    site_base = str(project.get("target_website") or brand_name or "").strip().rstrip("/")
    new_content = repair_content_html_images(
        new_content,
        site_base=site_base,
        source="enrich_project_images",
        probe_remote=False,
    )

    return {
        "featured_image": featured_local or existing_featured,
        "content": new_content,
        "gallery_images": gallery,
        "image_assets": image_assets,
        "used_query": used_query,
        "image_source": image_source,
        "inline_images_count": len(inline_inserts),
        "content_images_total": count_content_images(new_content),
        "content_prepared": content != raw_content,
    }


def auto_insert_images_to_project(
    project_id: str,
    *,
    user_id: int,
    max_inline: int | None = None,
    word_count_target: int | None = None,
    update_featured: bool = True,
    require_featured: bool = True,
    force: bool = False,
    image_strategy_override: str | None = None,
    on_status: Callable[[str], None] | None = None,
    db=None,
    user=None,
) -> dict[str, Any]:
    from app.services.content_ai_project_store import (
        get_content_ai_project,
        update_content_ai_project_fields,
    )

    project = get_content_ai_project(project_id, user_id=user_id)
    if not project:
        raise ValueError("Không tìm thấy dự án.")
    if not _resolve_project_content(project) and not str(project.get("outline_content") or "").strip():
        raise ValueError("Bài chưa có nội dung — hãy viết content trước khi chèn ảnh tự động.")
    if not str(project.get("primary_keyword") or "").strip():
        raise ValueError("Cần từ khóa chính (primary keyword) để tìm ảnh phù hợp.")

    enriched = enrich_project_with_context_images(
        project,
        max_inline=max_inline,
        word_count_target=word_count_target,
        update_featured=update_featured,
        require_featured=require_featured,
        force=force,
        image_strategy_override=image_strategy_override,
        on_status=on_status,
        db=db,
        user=user,
    )
    fields: dict[str, Any] = {
        "content": enriched["content"],
        "gallery_images": enriched["gallery_images"],
        "image_assets": enriched.get("image_assets") or [],
    }
    if enriched.get("featured_image"):
        fields["featured_image"] = enriched["featured_image"]
    updated = update_content_ai_project_fields(project_id, fields, user_id=user_id)
    if not updated:
        raise ValueError("Không cập nhật được dự án.")
    full = get_content_ai_project(project_id, user_id=user_id) or updated
    return {
        "ok": True,
        "project_id": project_id,
        "featured_image": enriched.get("featured_image") or "",
        "inline_images_count": enriched.get("inline_images_count") or 0,
        "content_images_total": enriched.get("content_images_total") or 0,
        "source": enriched.get("image_source") or "licensed_api",
        "query": enriched.get("used_query") or "",
        "image_assets": enriched.get("image_assets") or [],
        "project": full,
    }


def bulk_fetch_images_for_projects(
    project_ids: list[str],
    *,
    user_id: int,
    max_inline: int = 4,
    force: bool = False,
    only_without_images: bool = True,
    db=None,
    user=None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for pid in project_ids:
        pid = str(pid or "").strip()
        if not pid:
            continue
        try:
            from app.services.content_ai_project_store import get_content_ai_project

            row = get_content_ai_project(pid, user_id=user_id)
            if not row:
                errors.append({"project_id": pid, "error": "Không tìm thấy project."})
                continue
            if only_without_images:
                html = _resolve_project_content(row)
                if str(row.get("featured_image") or "").strip() and count_content_images(html) >= 1:
                    results.append({"project_id": pid, "skipped": True, "reason": "already_has_images"})
                    continue
            out = auto_insert_images_to_project(
                pid,
                user_id=user_id,
                max_inline=max_inline,
                update_featured=True,
                force=force,
                db=db,
                user=user,
            )
            results.append(
                {
                    "project_id": pid,
                    "ok": True,
                    "featured_image": out.get("featured_image"),
                    "inline_images_count": out.get("inline_images_count"),
                    "source": out.get("source"),
                }
            )
        except Exception as exc:
            errors.append({"project_id": pid, "error": str(exc)[:500]})
    return {"ok": True, "results": results, "errors": errors, "count": len([r for r in results if r.get("ok")])}


MAX_IMAGE_BYTES = 200 * 1024
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "WEBP", "JPG"})


def _featured_asset(project: dict[str, Any]) -> dict[str, Any] | None:
    assets = project.get("image_assets") or []
    if not isinstance(assets, list):
        return None
    for a in assets:
        if isinstance(a, dict) and str(a.get("role") or "") == "featured":
            return a
    return assets[0] if assets and isinstance(assets[0], dict) else None


def compute_project_image_status(project: dict[str, Any] | None) -> dict[str, Any]:
    """Trả status UI: none|ok|bad_format|too_large + metadata."""
    if not project:
        return {"status": "none", "error": "", "featured": None, "assets": []}
    from app.services.content_ai_project_store import _resolve_project_content

    content = _resolve_project_content(project)
    if not str(content or "").strip():
        return {"status": "none", "error": "Chưa có nội dung bài viết.", "featured": None, "assets": []}
    featured_url = str(project.get("featured_image") or "").strip()
    assets = [a for a in (project.get("image_assets") or []) if isinstance(a, dict)]
    feat = _featured_asset(project) or {}
    if not featured_url and not assets:
        if count_content_images(content) > 0:
            return {
                "status": "ok",
                "error": "",
                "featured": {"url": "", "alt": "", "caption": ""},
                "assets": assets,
            }
        return {"status": "none", "error": "", "featured": None, "assets": []}
    fmt = str(feat.get("format") or "").upper().replace("JPG", "JPEG")
    if fmt and fmt not in ALLOWED_IMAGE_FORMATS and fmt != "JPEG":
        return {
            "status": "bad_format",
            "error": f"Định dạng {fmt} không được phép (chỉ JPG/WEBP).",
            "featured": _pack_featured(feat, featured_url),
            "assets": assets,
        }
    nbytes = int(feat.get("bytes") or 0)
    if nbytes > MAX_IMAGE_BYTES:
        return {
            "status": "too_large",
            "error": f"Ảnh {round(nbytes / 1024, 1)}KB vượt 200KB.",
            "featured": _pack_featured(feat, featured_url),
            "assets": assets,
        }
    return {
        "status": "ok",
        "error": "",
        "featured": _pack_featured(feat, featured_url),
        "assets": assets,
    }


def _pack_featured(feat: dict[str, Any], url: str) -> dict[str, Any]:
    return {
        "url": url or str(feat.get("url") or ""),
        "alt": str(feat.get("alt") or ""),
        "caption": str(feat.get("caption") or ""),
        "source_url": str(feat.get("source_url") or ""),
        "license": str(feat.get("license") or ""),
        "author": str(feat.get("author") or ""),
        "provider": str(feat.get("provider") or ""),
        "format": str(feat.get("format") or ""),
        "bytes": int(feat.get("bytes") or 0),
        "filename": str(feat.get("filename") or ""),
        "width": feat.get("width"),
        "height": feat.get("height"),
    }


def bulk_image_status_for_projects(project_ids: list[str], *, user_id: int) -> dict[str, Any]:
    from app.services.content_ai_project_store import get_content_ai_project

    items: list[dict[str, Any]] = []
    for pid in project_ids:
        pid = str(pid or "").strip()
        if not pid:
            continue
        row = get_content_ai_project(pid, user_id=user_id)
        st = compute_project_image_status(row)
        items.append({"project_id": pid, "keyword": str((row or {}).get("primary_keyword") or ""), **st})
    return {"ok": True, "items": items}


def clear_project_images(project_id: str, *, user_id: int) -> dict[str, Any]:
    import re

    from app.services.content_ai_project_store import (
        _resolve_project_content,
        get_content_ai_project,
        update_content_ai_project_fields,
    )

    project = get_content_ai_project(project_id, user_id=user_id)
    if not project:
        raise ValueError("Không tìm thấy project.")
    raw = _resolve_project_content(project)
    cleaned = re.sub(
        r'<figure[^>]*class="[^"]*content-ai-inline-image[^"]*"[^>]*>.*?</figure>',
        "",
        raw or "",
        flags=re.I | re.S,
    )
    cleaned = re.sub(r"<figure[^>]*>.*?</figure>", "", cleaned, count=5, flags=re.I | re.S)
    update_content_ai_project_fields(
        project_id,
        {
            "featured_image": "",
            "gallery_images": [],
            "image_assets": [],
            "content": cleaned,
        },
        user_id=user_id,
    )
    return {"ok": True, "project_id": project_id}
