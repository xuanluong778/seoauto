"""Background bulk article writer — one keyword at a time, persisted via job_store."""

from __future__ import annotations

import os
import re
from typing import Any

from app.services.content_ai_bulk_parse import normalize_bulk_job_items
from app.services.content_ai_project_store import save_or_update_written_bulk_project
from app.services.content_draft_builder import build_draft_payload, suggest_content_ai_field
from app.services.job_store import fail_job, finish_job, update_job
from app.services.llm_content_writer import generate_content_ai_suggestion


def _fallback_content_html(*, primary_keyword: str, title: str, outline_content: str) -> str:
    """Minimal HTML fallback when LLM returns empty (avoids importing pages router)."""
    kw = (primary_keyword or "").strip()
    t = (title or "").strip() or kw or "Nội dung dịch vụ"
    outline = (outline_content or "").strip()
    h2_items: list[str] = []
    if outline:
        for ln in outline.splitlines():
            s = re.sub(r"^\s*#+\s*", "", str(ln or "").strip())
            if len(s) >= 4:
                h2_items.append(s)
            if len(h2_items) >= 6:
                break
    if not h2_items:
        h2_items = [f"Giới thiệu {kw or 'dịch vụ'}", "Quy trình và chi phí", "Liên hệ đặt lịch"]
    parts = [f"<h1>{t}</h1>", f"<p><strong>Bạn đang tìm {kw or 'dịch vụ'} — nội dung tổng hợp dưới đây.</strong></p>"]
    for h2 in h2_items:
        parts.append(f"<h2>{h2}</h2>")
        parts.append("<p>Nội dung chi tiết được triển khai theo dàn ý bài viết.</p>")
    parts.append("<h2>Liên hệ</h2><p>Gọi hotline hoặc nhắn Zalo để được tư vấn nhanh.</p>")
    return "\n".join(parts)


def _first_line(text: str) -> str:
    parts = [x.strip() for x in str(text or "").replace("\r", "").split("\n") if x.strip()]
    return parts[0] if parts else str(text or "").strip()


def _llm_mode() -> str:
    mode = (os.getenv("CONTENT_AI_LLM_MODE", "auto") or "auto").strip().lower()
    return mode if mode in {"off", "auto", "title_meta_only", "content_only"} else "auto"


def _load_llm_cfg():
    try:
        from app.services.llm_content_writer import load_llm_config

        return load_llm_config()
    except Exception:
        return None


def _llm_fields(mode: str) -> set[str]:
    if mode == "off":
        return set()
    if mode == "title_meta_only":
        return {"title", "meta_description", "outline_content", "slug", "tags", "secondary_keywords"}
    if mode == "content_only":
        return {"content"}
    return {"title", "meta_description", "outline_content", "content", "slug", "tags", "secondary_keywords"}


def _suggest(
    field: str,
    *,
    primary_keyword: str,
    target_website: str = "",
    title: str = "",
    outline_content: str = "",
    content: str = "",
    meta_description: str = "",
    slug: str = "",
    tags: str = "",
    secondary_keywords: str = "",
    target_word_count: int | None = None,
) -> str:
    f = (field or "").strip().lower()
    mode = _llm_mode()
    llm_cfg = _load_llm_cfg()
    use_llm = bool(llm_cfg) and f in _llm_fields(mode)
    if use_llm:
        try:
            out = generate_content_ai_suggestion(
                field=f,
                title=title,
                content=content,
                target_website=target_website,
                slug=slug,
                tags=tags,
                meta_description=meta_description,
                primary_keyword=primary_keyword,
                secondary_keywords=secondary_keywords,
                outline_content=outline_content,
                target_word_count=target_word_count,
            )
            if str(out or "").strip():
                return str(out).strip()
        except Exception:
            if f == "content":
                pass
            else:
                raise
    if f == "content":
        return _fallback_content_html(primary_keyword=primary_keyword, title=title, outline_content=outline_content)
    return suggest_content_ai_field(
        field=f,
        title=title,
        content=content,
        target_website=target_website,
        slug=slug,
        tags=tags,
        meta_description=meta_description,
        primary_keyword=primary_keyword,
        secondary_keywords=secondary_keywords,
        outline_content=outline_content,
    )


def _bulk_planning_notes(*, search_volume: int = 0, content_type: str = "", brand_name: str = "") -> str:
    parts: list[str] = []
    bn = str(brand_name or "").strip()
    if bn:
        parts.append(f"BRAND_NAME: {bn}")
    ct = str(content_type or "").strip()
    if ct:
        parts.append(f"CONTENT_TYPE: {ct}")
    if search_volume and search_volume > 0:
        parts.append(f"SEARCH_VOLUME: {search_volume}")
    return "\n".join(parts)


def _write_one_article(
    *,
    user_id: int,
    primary_keyword: str,
    target_website: str,
    target_word_count: int,
    secondary_keywords: list[str],
    custom_title: str = "",
    custom_description: str = "",
    custom_outline: str = "",
    search_volume: int = 0,
    content_type: str = "",
    competitor_url: str = "",
    brand_name: str = "",
    wp_category_id: int = 0,
) -> str:
    pk = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    if not pk:
        raise ValueError("Từ khóa trống")
    sec_str = ", ".join(str(x).strip() for x in (secondary_keywords or []) if str(x).strip())
    c_title = re.sub(r"\s+", " ", str(custom_title or "").strip())
    c_desc = re.sub(r"\s+", " ", str(custom_description or "").strip())
    c_outline = str(custom_outline or "").strip()

    if c_outline:
        outline = c_outline
    else:
        outline = _suggest(
            "outline_content",
            primary_keyword=pk,
            target_website=target_website,
            secondary_keywords=sec_str,
            target_word_count=target_word_count,
        )
    plan_notes = _bulk_planning_notes(
        search_volume=search_volume, content_type=content_type, brand_name=brand_name
    )
    if competitor_url and not c_outline:
        plan_notes = f"{plan_notes}\nCOMPETITOR_URL: {competitor_url}".strip()
    content = _suggest(
        "content",
        primary_keyword=pk,
        target_website=target_website,
        outline_content=outline,
        secondary_keywords=sec_str,
        target_word_count=target_word_count,
        title=c_title,
        meta_description=c_desc,
        content=plan_notes,
    )
    if c_title:
        title = _first_line(c_title) or pk
    else:
        title = _first_line(
            _suggest(
                "title",
                primary_keyword=pk,
                target_website=target_website,
                outline_content=outline,
                content=content,
                secondary_keywords=sec_str,
            )
        ) or pk
    if c_desc:
        meta = _first_line(c_desc)
    else:
        meta = _first_line(
            _suggest(
                "meta_description",
                primary_keyword=pk,
                target_website=target_website,
                title=title,
                outline_content=outline,
                content=content,
                secondary_keywords=sec_str,
            )
        )
    slug = _first_line(
        _suggest(
            "slug",
            primary_keyword=pk,
            title=title,
            outline_content=outline,
            target_website=target_website,
        )
    )
    tags_raw = _suggest(
        "tags",
        primary_keyword=pk,
        title=title,
        content=content,
        outline_content=outline,
        secondary_keywords=sec_str,
    )
    tag_list = [x.strip() for x in re.split(r"[,;]", str(tags_raw or "")) if x.strip()]

    try:
        wpc = int(wp_category_id or 0)
    except (TypeError, ValueError):
        wpc = 0
    draft_cats = [wpc] if wpc > 0 else None

    draft = build_draft_payload(
        title=title,
        content=content,
        slug=slug,
        tags=tag_list,
        meta_description=meta,
        target_website=target_website,
        primary_keyword=pk,
        secondary_keywords=secondary_keywords,
        outline_content=outline,
        categories=draft_cats,
    )
    source = {
        "title": title,
        "content": content,
        "slug": slug,
        "tags": tag_list,
        "meta_description": meta,
        "target_website": target_website,
        "primary_keyword": pk,
        "secondary_keywords": secondary_keywords,
        "outline_content": outline,
        "target_word_count": target_word_count,
        "custom_title": c_title,
        "custom_description": c_desc,
        "custom_outline": c_outline,
        "search_volume": int(search_volume or 0),
        "content_type": str(content_type or "").strip(),
        "competitor_url": str(competitor_url or "").strip(),
        "target_word_count": int(target_word_count or 1000),
        "wp_category_id": wpc,
    }
    return save_or_update_written_bulk_project(
        user_id=user_id,
        source_payload=source,
        draft_payload=draft,
    )


def run_content_ai_bulk_job(job_id: str, payload: dict[str, Any]) -> None:
    from app.core.user_context import bind_request_user_id, unbind_request_user_id

    raw_items = payload.get("items")
    raw_kw = payload.get("keywords") or []
    kw_list: list[str] = []
    if isinstance(raw_kw, str):
        for line in raw_kw.replace("\r", "\n").split("\n"):
            k = line.strip()
            if k:
                kw_list.append(k)
    elif isinstance(raw_kw, list):
        for item in raw_kw:
            k = str(item or "").strip()
            if k:
                kw_list.append(k)

    item_dicts: list[dict[str, Any]] | None = None
    if isinstance(raw_items, list) and raw_items:
        item_dicts = [x for x in raw_items if isinstance(x, dict)]

    bulk_rows = normalize_bulk_job_items(keywords=kw_list, items=item_dicts)
    keywords = [r["keyword"] for r in bulk_rows]

    if not keywords:
        fail_job(job_id, error="Danh sách từ khóa trống.")
        return

    try:
        bulk_user_id = int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        bulk_user_id = 0
    if bulk_user_id <= 0:
        fail_job(job_id, error="Thiếu user_id trong job — hãy đăng nhập và chạy lại bulk.")
        return

    user_ctx_token = bind_request_user_id(bulk_user_id)
    try:
        _run_content_ai_bulk_job_body(
            job_id=job_id,
            payload=payload,
            bulk_rows=bulk_rows,
            keywords=keywords,
            bulk_user_id=bulk_user_id,
        )
    finally:
        unbind_request_user_id(user_ctx_token)


def _run_content_ai_bulk_job_body(
    *,
    job_id: str,
    payload: dict[str, Any],
    bulk_rows: list[dict[str, Any]],
    keywords: list[str],
    bulk_user_id: int,
) -> None:
    target_website = str(payload.get("target_website") or "").strip()
    try:
        target_word_count = int(payload.get("target_word_count") or 1000)
    except (TypeError, ValueError):
        target_word_count = 1000
    target_word_count = max(200, min(8000, target_word_count))

    sec_raw = payload.get("secondary_keywords") or []
    secondary: list[str] = []
    if isinstance(sec_raw, str):
        secondary = [x.strip() for x in sec_raw.split(",") if x.strip()]
    elif isinstance(sec_raw, list):
        secondary = [str(x).strip() for x in sec_raw if str(x).strip()]

    brand_name = str(payload.get("brand_name") or "").strip()
    try:
        wp_cat = int(payload.get("wp_category_id") or 0)
    except (TypeError, ValueError):
        wp_cat = 0
    if wp_cat < 0:
        wp_cat = 0
    total = len(keywords)
    items: list[dict[str, Any]] = []
    success_n = 0

    for i, row in enumerate(bulk_rows):
        kw = row["keyword"]
        pct = int((i / max(total, 1)) * 100)
        update_job(
            job_id,
            progress=max(1, min(99, pct)),
            message=f"Đang viết bài {i + 1}/{total}: {kw}",
        )
        try:
            row_wc = int(row.get("target_word_count") or 0)
            item_wc = row_wc if row_wc >= 200 else target_word_count
            row_sec_raw = row.get("secondary_keywords")
            row_secondary: list[str] = []
            if isinstance(row_sec_raw, list):
                row_secondary = [str(x).strip() for x in row_sec_raw if str(x).strip()]
            elif isinstance(row_sec_raw, str):
                row_secondary = [x.strip() for x in re.split(r"[,;\n\r]+", row_sec_raw) if x.strip()]
            use_secondary = row_secondary if row_secondary else secondary
            try:
                row_wp = int(row.get("wp_category_id") or 0)
            except (TypeError, ValueError):
                row_wp = 0
            if row_wp <= 0:
                row_wp = wp_cat
            project_id = _write_one_article(
                user_id=bulk_user_id,
                primary_keyword=kw,
                target_website=target_website,
                target_word_count=item_wc,
                secondary_keywords=use_secondary,
                custom_title=row.get("custom_title") or "",
                custom_description=row.get("custom_description") or "",
                custom_outline=row.get("custom_outline") or "",
                search_volume=int(row.get("search_volume") or 0),
                content_type=str(row.get("content_type") or ""),
                competitor_url=str(row.get("competitor_url") or ""),
                brand_name=brand_name,
                wp_category_id=row_wp,
            )
            success_n += 1
            items.append(
                {
                    "keyword": kw,
                    "status": "success",
                    "project_id": project_id,
                    "custom_title": row.get("custom_title") or "",
                    "custom_description": row.get("custom_description") or "",
                    "custom_outline": row.get("custom_outline") or "",
                }
            )
        except Exception as exc:
            items.append({"keyword": kw, "status": "error", "error": str(exc)[:800]})

    finish_job(
        job_id,
        result={
            "total": total,
            "success": success_n,
            "failed": total - success_n,
            "target_website": target_website,
            "items": items,
        },
    )
