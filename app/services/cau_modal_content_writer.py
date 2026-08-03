"""Viết lại / mở rộng content trong popup Sửa SEO (Auto Update)."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.cau_seo_analyzer import build_cau_fix_change_report, evaluate_cau_modal_seo
from app.services.llm_content_writer import (
    generate_cau_modal_append_sections_html,
    generate_cau_modal_auto_append_sections_html,
    generate_cau_modal_rewrite_html,
    resolve_wc_for_content,
)

FACTOR_REWRITE = "modal_content_rewrite"
FACTOR_APPEND = "modal_content_append"
FACTOR_APPEND_LABEL = "Tự thêm heading mới"


def validate_rewrite_modal_brief(
    *,
    title: str,
    meta_description: str,
    slug: str,
    primary_keyword: str,
    secondary_keywords: str,
    outline_content: str,
) -> None:
    """Kiểm tra brief đủ trước khi viết lại content."""
    if not str(title or "").strip():
        raise ValueError("Hãy nhập Title để tiến hành viết bài.")
    if not str(primary_keyword or "").strip():
        raise ValueError("Hãy nhập Focus keyword (từ khóa chính) để tiến hành viết bài.")
    if not str(secondary_keywords or "").strip():
        raise ValueError("Hãy nhập từ khóa phụ để tiến hành viết bài.")
    if not str(slug or "").strip():
        raise ValueError("Hãy nhập Slug để tiến hành viết bài.")
    if not str(meta_description or "").strip():
        raise ValueError("Hãy nhập Meta description để tiến hành viết bài.")
    outline = str(outline_content or "").strip()
    if not outline:
        raise ValueError("Hãy nhập outline content để tiến hành viết bài.")
    if not re.search(r"(^|\n)\s*#{1,3}\s+\S", outline, flags=re.M):
        raise ValueError("Outline cần có ít nhất 1 heading (ví dụ: ## Tiêu đề mục).")


def _norm_heading(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def extract_existing_headings(content_html: str) -> list[str]:
    try:
        soup = BeautifulSoup(str(content_html or "")[:400_000], "html.parser")
    except Exception:
        return []
    out: list[str] = []
    for el in soup.find_all(re.compile(r"^h[1-4]$", re.I)):
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if t:
            out.append(t)
    return out


def filter_new_headings(requested: list[str], content_html: str) -> tuple[list[str], list[str]]:
    """Trả (headings hợp lệ, headings bị bỏ vì trùng)."""
    existing = {_norm_heading(h) for h in extract_existing_headings(content_html)}
    accepted: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for raw in requested:
        h = re.sub(r"\s+", " ", str(raw or "").strip())
        if not h:
            continue
        key = _norm_heading(h)
        if key in existing or key in seen:
            skipped.append(h)
            continue
        seen.add(key)
        accepted.append(h)
    return accepted, skipped


def extract_new_headings_from_sections_html(sections_html: str) -> list[str]:
    """Lấy text H2/H3 từ fragment section mới."""
    try:
        soup = BeautifulSoup(str(sections_html or "")[:200_000], "html.parser")
    except Exception:
        return []
    out: list[str] = []
    for el in soup.find_all(re.compile(r"^h[2-3]$", re.I)):
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if t:
            out.append(t)
    return out


def validate_append_sections_html(
    sections_html: str,
    content_html: str,
    *,
    max_headings: int = 3,
) -> tuple[list[str], list[str]]:
    """Kiểm tra fragment mới: không trùng heading cũ, có 1–max_headings mục mới."""
    existing = {_norm_heading(h) for h in extract_existing_headings(content_html)}
    new_heads = extract_new_headings_from_sections_html(sections_html)
    if not new_heads:
        raise ValueError("AI không tạo được heading mới hợp lệ (cần H2/H3 + nội dung).")

    accepted: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for h in new_heads:
        key = _norm_heading(h)
        if key in existing or key in seen:
            skipped.append(h)
            continue
        seen.add(key)
        accepted.append(h)
        if len(accepted) >= max_headings:
            break

    if not accepted:
        dup = ", ".join(skipped[:5])
        raise ValueError(f"Heading AI trùng với bài hiện có: {dup}")

    if len(accepted) > max_headings:
        accepted = accepted[:max_headings]
    return accepted, skipped


def _estimate_word_count(content_html: str) -> int:
    try:
        text = BeautifulSoup(str(content_html or ""), "html.parser").get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", content_html or "")
    n = len(text.split())
    if n < 300:
        return 1000
    return max(600, min(2500, n))


def _insert_sections_html(content_html: str, new_sections_html: str) -> str:
    """Chèn fragment section mới — không sửa/xóa/thay thế node HTML hiện có."""
    soup = BeautifulSoup(str(content_html or "") or "<div></div>", "html.parser")
    insert_before = None
    for h2 in soup.find_all("h2"):
        t = h2.get_text(" ", strip=True).lower()
        if any(k in t for k in ("faq", "câu hỏi", "kết luận", "tổng kết")):
            insert_before = h2
            break
    if insert_before is None:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            insert_before = script
            break
    frag = BeautifulSoup(new_sections_html, "html.parser")
    nodes = [n for n in frag.children if getattr(n, "name", None) or str(n).strip()]
    if not nodes:
        raise ValueError("Không có section HTML để chèn.")
    if insert_before is not None:
        for node in reversed(nodes):
            insert_before.insert_before(node)
    else:
        for node in nodes:
            soup.append(node)
    return str(soup)


def _build_preview_result(
    *,
    factor_id: str,
    factor_label: str,
    summary: str,
    reason: str,
    before_title: str,
    before_meta: str,
    before_slug: str,
    before_content: str,
    after_content: str,
    secondary_keywords: list[str] | None,
    primary_keyword: str,
    post_url: str,
    append_snippet: str = "",
) -> dict[str, Any]:
    seo_before = evaluate_cau_modal_seo(
        title=before_title,
        meta_description=before_meta,
        content_html=before_content,
        primary_keyword=primary_keyword,
        slug=before_slug,
        secondary_keywords=secondary_keywords,
        post_url=post_url,
    )
    seo_after = evaluate_cau_modal_seo(
        title=before_title,
        meta_description=before_meta,
        content_html=after_content,
        primary_keyword=primary_keyword,
        slug=before_slug,
        secondary_keywords=secondary_keywords,
        post_url=post_url,
    )
    patch_row: dict[str, Any] = {
        "field": "content_html",
        "position": "Nội dung bài viết",
        "reason": reason,
    }
    if append_snippet:
        patch_row["old_value"] = before_content
        patch_row["new_value"] = after_content
        patch_row["position"] = "Bản mới = nội dung cũ + heading/section mới"
        patch_row["preview_full_content"] = True
    else:
        patch_row["old_value"] = before_content
        patch_row["new_value"] = after_content

    fix_result: dict[str, Any] = {
        "success": True,
        "source": "llm",
        "summary": summary,
        "patch": {"content_html": after_content},
        "patches": [patch_row],
        "factors_targeted": [{"id": factor_id, "label": factor_label}],
        "factor_outcomes": [],
        "seo_before": seo_before,
        "seo_after": seo_after,
        "before_snapshot": {
            "title": before_title,
            "meta_description": before_meta,
            "slug": before_slug,
            "content_html": before_content,
        },
        "factor_snap_before": {
            "title": before_title,
            "meta_description": before_meta,
            "slug": before_slug,
            "content_html": before_content,
        },
        "factor_snap_after": {
            "title": before_title,
            "meta_description": before_meta,
            "slug": before_slug,
            "content_html": after_content,
        },
    }
    change_report = build_cau_fix_change_report(
        factor_id=factor_id,
        before_title=before_title,
        before_meta=before_meta,
        before_slug=before_slug,
        before_content=before_content,
        fix_result=fix_result,
    )
    change_report["factor_id"] = factor_id
    return {
        "ok": True,
        "preview_only": True,
        "success": True,
        "factor_id": factor_id,
        "patch": fix_result["patch"],
        "before_snapshot": fix_result["before_snapshot"],
        "change_report": change_report,
        "source": "llm",
        "seo": seo_after,
        "seo_before": seo_before,
        "seo_after": seo_after,
        "message": summary,
    }


def preview_rewrite_modal_content(
    *,
    title: str,
    meta_description: str,
    slug: str,
    primary_keyword: str,
    secondary_keywords: list[str] | None,
    outline_content: str,
    content_html: str,
    post_url: str = "",
    target_word_count: int | None = None,
    user_id: int | None = None,
    use_system_llm: bool = False,
) -> dict[str, Any]:
    validate_rewrite_modal_brief(
        title=title,
        meta_description=meta_description,
        slug=slug,
        primary_keyword=primary_keyword,
        secondary_keywords=", ".join(secondary_keywords or []),
        outline_content=outline_content,
    )
    wc = target_word_count or _estimate_word_count(content_html)
    new_html = generate_cau_modal_rewrite_html(
        title=title,
        meta_description=meta_description,
        slug=slug,
        primary_keyword=primary_keyword,
        secondary_keywords=", ".join(secondary_keywords or []),
        outline_content=outline_content,
        content_html=content_html,
        target_website=post_url,
        user_id=user_id,
        use_system_llm=use_system_llm,
        target_word_count=resolve_wc_for_content(wc),
    )
    if not str(new_html or "").strip():
        raise ValueError("Không tạo được nội dung mới.")
    return _build_preview_result(
        factor_id=FACTOR_REWRITE,
        factor_label="Viết lại Content",
        summary="AI đã viết lại toàn bộ content — xem bản cũ / bản mới trước khi áp dụng.",
        reason="Viết lại toàn bộ nội dung theo title, keyword, outline và tối ưu SEO.",
        before_title=title,
        before_meta=meta_description,
        before_slug=slug,
        before_content=content_html,
        after_content=new_html,
        secondary_keywords=secondary_keywords,
        primary_keyword=primary_keyword,
        post_url=post_url,
    )


def preview_append_headings_modal_content(
    *,
    headings: list[str],
    title: str,
    meta_description: str,
    slug: str,
    primary_keyword: str,
    secondary_keywords: list[str] | None,
    outline_content: str,
    content_html: str,
    post_url: str = "",
    user_id: int | None = None,
    use_system_llm: bool = False,
    auto_generate_heading: bool = False,
) -> dict[str, Any]:
    manual = [re.sub(r"\s+", " ", str(h or "").strip()) for h in headings if str(h or "").strip()]
    use_auto = bool(auto_generate_heading) or not manual

    if use_auto:
        sections_html = generate_cau_modal_auto_append_sections_html(
            title=title,
            meta_description=meta_description,
            primary_keyword=primary_keyword,
            secondary_keywords=", ".join(secondary_keywords or []),
            outline_content=outline_content,
            content_html=content_html,
            existing_headings=extract_existing_headings(content_html),
            target_website=post_url,
            user_id=user_id,
            use_system_llm=use_system_llm,
        )
        accepted, skipped = validate_append_sections_html(sections_html, content_html)
        reason = (
            "AI phân tích bài, tự đề xuất heading còn thiếu và viết nội dung mới — "
            "không sửa/xóa section cũ."
        )
        summary = (
            f"AI tự thêm {len(accepted)} heading mới: {', '.join(accepted[:3])}"
            + ("…" if len(accepted) > 3 else "")
            + " — xem bản cũ / bản mới trước khi áp dụng."
        )
        if skipped:
            summary += f" (Bỏ qua {len(skipped)} heading trùng.)"
    else:
        accepted, skipped = filter_new_headings(manual, content_html)
        if not accepted:
            msg = "Tất cả heading đã tồn tại trong bài hoặc trùng nhau."
            if skipped:
                msg += " Trùng: " + ", ".join(skipped[:5])
            raise ValueError(msg)

        sections_html = generate_cau_modal_append_sections_html(
            headings=accepted,
            title=title,
            meta_description=meta_description,
            primary_keyword=primary_keyword,
            secondary_keywords=", ".join(secondary_keywords or []),
            outline_content=outline_content,
            content_html=content_html,
            existing_headings=extract_existing_headings(content_html),
            target_website=post_url,
            user_id=user_id,
            use_system_llm=use_system_llm,
        )
        validate_append_sections_html(sections_html, content_html, max_headings=len(accepted) + 2)
        reason = "Viết nội dung cho heading do bạn nhập — chèn thêm, giữ nguyên phần cũ."
        summary = f"Đã viết thêm {len(accepted)} section — xem bản cũ / bản mới trước khi áp dụng."
        if skipped:
            summary += f" (Bỏ qua {len(skipped)} heading trùng.)"

    new_html = _insert_sections_html(content_html, sections_html)
    return _build_preview_result(
        factor_id=FACTOR_APPEND,
        factor_label=FACTOR_APPEND_LABEL,
        summary=summary,
        reason=reason,
        before_title=title,
        before_meta=meta_description,
        before_slug=slug,
        before_content=content_html,
        after_content=new_html,
        secondary_keywords=secondary_keywords,
        primary_keyword=primary_keyword,
        post_url=post_url,
        append_snippet=sections_html,
    )
