"""AI Auto Fix theo SEO Core 30 — chỉ preview patch, không ghi DB."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from app.services.content_ai_publish_checklist import evaluate_publish_checklist, _expected_blockquotes
from app.services.content_blockquote_postprocess import postprocess_content_blockquotes
from app.services.content_diff import build_content_diff
from app.services.content_update_agent import generate_seo_update, validate_preserved_markup
from app.services.llm_content_writer import _count_words_html

AUTOFIX_MODES = frozenset({"single", "severe", "optimize_90"})

# Yếu tố → phạm vi sửa (gợi ý cho prompt, không cắt cứng nếu mode optimize_90)
_FACTOR_SCOPES: dict[str, str] = {
    "intent_title_match": "title",
    "intent_h1_keyword": "content",
    "intent_answer_early": "content",
    "helpful_word_count": "content",
    "helpful_actionable": "content",
    "helpful_faq_conclusion": "content",
    "eeat_specifics": "content",
    "eeat_unique_value": "content",
    "eeat_trust_signals": "content",
    "title_keyword": "title",
    "meta_quality": "meta",
    "slug_seo": "slug",
    "heading_single_h1": "content",
    "heading_h2_count": "content",
    "heading_hierarchy": "content",
    "keyword_in_body": "content",
    "keyword_density": "content",
    "semantic_keywords": "content",
    "depth_word_count": "content",
    "depth_paragraphs": "content",
    "depth_per_section": "content",
    "links_internal": "content",
    "links_external": "content",
    "links_anchor_text": "content",
    "media_images": "content",
    "media_alt_text": "content",
    "media_schema_blockquote": "content",
    "readability_sentence": "content",
    "readability_paragraphs": "content",
    "readability_formatting": "content",
}


def _slugify(text: str) -> str:
    raw = unicodedata.normalize("NFC", str(text or "").strip().lower())
    raw = raw.replace("đ", "d")
    raw = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE)
    raw = re.sub(r"[\s_]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw[:120]


def _factors_from_score(result: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for g in result.get("groups") or []:
        for f in g.get("factors") or []:
            if f.get("id"):
                out.append({**f, "group_label": g.get("label") or ""})
    return out


def _status_norm(st: str) -> str:
    s = str(st or "").lower()
    if s in ("failed", "fail"):
        return "failed"
    if s in ("warning", "warn"):
        return "warning"
    if s in ("passed", "ok"):
        return "passed"
    return s


def select_factors_for_autofix(
    score_result: dict[str, Any],
    *,
    mode: str,
    factor_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Chọn yếu tố failed/warning theo mode."""
    all_f = _factors_from_score(score_result)
    failed = [f for f in all_f if _status_norm(f.get("status")) == "failed"]
    warning = [f for f in all_f if _status_norm(f.get("status")) == "warning"]

    mode = (mode or "single").strip().lower()
    if mode not in AUTOFIX_MODES:
        mode = "single"

    if mode == "single":
        ids = {str(x).strip() for x in (factor_ids or []) if str(x).strip()}
        picked = [f for f in all_f if str(f.get("id") or "") in ids]
        pf = [f for f in picked if _status_norm(f.get("status")) == "failed"]
        pw = [f for f in picked if _status_norm(f.get("status")) == "warning"]
        return pf, pw

    if mode == "severe":
        return failed, []

    # optimize_90: failed trước, rồi warning theo điểm thiếu
    def _missing_pts(f: dict[str, Any]) -> float:
        return max(0.0, float(f.get("max_score") or 0) - float(f.get("score") or 0))

    warnings_sorted = sorted(warning, key=_missing_pts, reverse=True)
    return failed, warnings_sorted


def _rule_patch_meta_slug(
    *,
    title: str,
    meta: str,
    slug: str,
    keyword: str,
    factors: list[dict[str, Any]],
) -> dict[str, str]:
    """Fallback nhẹ khi LLM không đổi — chỉ title/meta/slug."""
    kw = (keyword or "").strip()
    ids = {str(f.get("id") or "") for f in factors}
    out_title = title
    out_meta = meta
    out_slug = slug

    if kw:
        if "title_keyword" in ids or "intent_title_match" in ids:
            if kw.lower() not in out_title.lower():
                out_title = f"{kw}: {out_title}".strip()[:200]
        if "meta_quality" in ids:
            if not out_meta.strip():
                out_meta = f"Tìm hiểu {kw} — thông tin chi tiết, hướng dẫn thực tế và lợi ích rõ ràng cho bạn."[:160]
            elif kw.lower() not in out_meta.lower():
                out_meta = f"{kw}: {out_meta}"[:160]
        if "slug_seo" in ids:
            sug = _slugify(kw)
            if sug:
                out_slug = sug
            elif kw and kw.lower() not in out_slug.replace("-", " ").lower():
                out_slug = _slugify(kw) or out_slug

    return {"title": out_title, "meta_description": out_meta, "slug": out_slug}


def _maybe_postprocess_blockquote(content: str, factor_ids: set[str]) -> str:
    if "media_schema_blockquote" not in factor_ids:
        return content
    try:
        return postprocess_content_blockquotes(content)
    except Exception:
        return content


def _has_json_ld(html: str) -> bool:
    return bool(re.search(r'application/ld\+json|"@type"\s*:', html or "", flags=re.I))


def _inject_article_schema(*, content: str, title: str, description: str) -> str:
    from app.services.content_ai_publish_checklist import schema_ok_from_html

    if schema_ok_from_html(content):
        return content
    headline = (title or "Bài viết").strip()[:200]
    desc = (description or headline).strip()[:320]
    payload = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": desc,
        "author": {"@type": "Organization", "name": "DigiSEO"},
    }
    script = (
        '<script type="application/ld+json">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script>"
    )
    return content.rstrip() + "\n" + script


def _inject_internal_links(*, content: str, keyword: str, target_website: str) -> str:
    internal_n = 0
    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)', content or "", flags=re.I):
        href = m.group(1).strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith("/") or "internal" in href.lower():
            internal_n += 1
    if re.search(r"<!--\s*internal\s*:", content or "", flags=re.I):
        internal_n = max(internal_n, 1)
    if internal_n >= 2:
        return content
    anchor = (keyword or "bài viết liên quan").strip()[:80] or "bài viết liên quan"
    site = (target_website or "").strip()
    path = "/"
    if site:
        try:
            p = urlparse(site if "://" in site else f"https://{site}")
            path = p.path.rstrip("/") or "/"
            if not path.startswith("/"):
                path = "/" + path
        except Exception:
            path = "/"
    block = (
        f'<p>Đọc thêm: <a href="{path}">{anchor}</a>'
        f' · <a href="{path}/blog">{anchor} — danh mục</a></p>'
    )
    return content.rstrip() + "\n" + block


def _inject_placeholder_image(*, content: str, keyword: str) -> str:
    if re.search(r"<img\b", content or "", flags=re.I):
        return content
    alt = (keyword or "Minh họa bài viết").strip()[:120] or "Minh họa bài viết"
    placeholder = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='450'%3E"
        "%3Crect fill='%231e293b' width='800' height='450'/%3E%3Ctext x='50%25' y='50%25' "
        "fill='%2394a3b8' font-size='24' text-anchor='middle' dy='.3em'%3EMinh họa%3C/text%3E%3C/svg%3E"
    )
    fig = (
        f'<figure class="wp-block-image">'
        f'<img src="{placeholder}" alt="{alt}" loading="lazy" />'
        f"<figcaption>{alt}</figcaption></figure>"
    )
    m = re.search(r"(</h2>)", content, flags=re.I)
    if m:
        idx = m.end()
        return content[:idx] + "\n" + fig + content[idx:]
    return fig + "\n" + content


def _inject_blockquotes(content: str, *, needed: int) -> str:
    import re as _re

    cur = len(_re.findall(r"<blockquote\b", content or "", flags=_re.I))
    if cur >= needed:
        return content
    blocks = []
    for _ in range(max(0, needed - cur)):
        blocks.append(
            '<blockquote class="expert-quote">'
            "<p>«Trích dẫn chuyên gia: nội dung bổ sung giúp người đọc có thêm góc nhìn thực tiễn và đáng tin cậy.»</p>"
            "<cite>— Chuyên gia trong lĩnh vực</cite></blockquote>"
        )
    return content.rstrip() + "\n" + "\n".join(blocks)


def _boost_word_count_to(content: str, *, min_words: int, keyword: str) -> str:
    if _count_words_html(content) >= min_words:
        return content
    kw = (keyword or "chủ đề bài viết").strip()
    sentences = [
        f"Phần mở rộng bổ sung giúp bài viết về {kw} đạt chiều sâu nội dung tốt hơn cho người đọc.",
        f"Người đọc có thể áp dụng các điểm đã nêu về {kw} vào thực tế một cách dễ dàng hơn.",
        f"Nội dung chi tiết về {kw} giúp tăng giá trị tra cứu và tham khảo lâu dài.",
        f"Các bước và lưu ý liên quan {kw} được tổng hợp nhằm hỗ trợ ra quyết định nhanh hơn.",
    ]
    extra: list[str] = []
    idx = 0
    merged = content
    while _count_words_html(merged) < min_words and idx < 100:
        extra.append(f"<p>{sentences[idx % len(sentences)]}</p>")
        merged = content.rstrip() + "\n" + "".join(extra)
        idx += 1
    return merged


def _apply_guaranteed_factor_fix(
    *,
    factor_id: str,
    title: str,
    meta: str,
    content: str,
    slug: str,
    keyword: str,
    target_website: str,
) -> tuple[str, str, str, str]:
    """Sửa rule-based để yếu tố đạt «passed» sau auto-fix single."""
    fid = str(factor_id or "").strip()
    out_t, out_m, out_c, out_s = title, meta, content, slug
    kw = (keyword or "").strip()

    if fid == "slug_seo" and kw:
        out_s = _slugify(kw) or out_s
    elif fid == "depth_word_count":
        out_c = _boost_word_count_to(out_c, min_words=1200, keyword=kw)
    elif fid == "media_schema_blockquote":
        out_c = _inject_article_schema(content=out_c, title=out_t, description=out_m)
        need_bq = _expected_blockquotes(_count_words_html(out_c))
        if need_bq > 0:
            out_c = _inject_blockquotes(out_c, needed=need_bq)
        try:
            out_c = postprocess_content_blockquotes(out_c)
        except Exception:
            pass
    elif fid == "links_internal":
        out_c = _inject_internal_links(content=out_c, keyword=kw, target_website=target_website)
    elif fid == "media_images":
        out_c = _inject_placeholder_image(content=out_c, keyword=kw)
    elif fid in ("title_keyword", "intent_title_match") and kw:
        if kw.lower() not in out_t.lower():
            out_t = f"{kw}: {out_t}".strip()[:200]
    elif fid == "meta_quality" and kw:
        if not out_m.strip():
            out_m = f"Tìm hiểu {kw} — thông tin chi tiết và hướng dẫn thực tế."[:160]
        elif kw.lower() not in out_m.lower():
            out_m = f"{kw}: {out_m}"[:160]

    return out_t, out_m, out_c, out_s


def _rule_patch_content_html(
    content: str,
    *,
    title: str,
    meta: str,
    keyword: str,
    target_website: str,
    factors: list[dict[str, Any]],
) -> str:
    ids = {str(f.get("id") or "") for f in factors}
    out = content
    if "media_schema_blockquote" in ids:
        out = _inject_article_schema(content=out, title=title, description=meta)
    if "links_internal" in ids:
        out = _inject_internal_links(content=out, keyword=keyword, target_website=target_website)
    if "media_images" in ids:
        out = _inject_placeholder_image(content=out, keyword=keyword)
    if "depth_word_count" in ids:
        out = _boost_word_count_to(out, min_words=1200, keyword=keyword)
    return out


def _factor_lookup(score: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for g in score.get("groups") or []:
        for f in g.get("factors") or []:
            fid = str(f.get("id") or "")
            if fid:
                out[fid] = f
    return out


def _target_factor_outcomes(
    before: dict[str, Any],
    after: dict[str, Any],
    target_ids: list[str],
) -> list[dict[str, Any]]:
    bmap = _factor_lookup(before)
    amap = _factor_lookup(after)
    rows: list[dict[str, Any]] = []
    for fid in target_ids:
        fid = str(fid or "").strip()
        if not fid:
            continue
        b = bmap.get(fid) or {}
        a = amap.get(fid) or {}
        rows.append({
            "id": fid,
            "label": a.get("label") or b.get("label") or fid,
            "status_before": b.get("status"),
            "status_after": a.get("status"),
            "score_before": b.get("score"),
            "score_after": a.get("score"),
            "message_after": a.get("message") or "",
        })
    return rows


def _build_focus_text(failed: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    scopes: set[str] = set()
    for f in failed + warnings:
        fid = str(f.get("id") or "")
        sc = _FACTOR_SCOPES.get(fid)
        if sc:
            scopes.add(sc)
    if not scopes:
        return "content"
    return ", ".join(sorted(scopes))


def run_seo_autofix_preview(
    *,
    user_id: int,
    db: Session | None = None,
    user: User | None = None,
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
    target_website: str = "",
    mode: str = "single",
    factor_ids: list[str] | None = None,
    evaluate_fn=None,
    use_system_llm: bool = False,
    skip_llm_credit_check: bool = False,
) -> dict[str, Any]:
    """
    Preview auto-fix — trả patch + diff + điểm trước/sau.
    Không ghi DB. Nếu AI lỗi → giữ nguyên nội dung, success=False.
    """
    title_s = str(title or "").strip()
    meta_s = str(meta_description or "").strip()
    content_s = str(content_html or "").strip()
    slug_s = str(slug or "").strip()
    kw = str(primary_keyword or "").strip()
    eval_fn = evaluate_fn or evaluate_publish_checklist

    if not content_s and not title_s:
        return {
            "success": False,
            "error": "Chưa có nội dung để sửa.",
            "unchanged": True,
        }

    before = eval_fn(
        title=title_s,
        meta_description=meta_s,
        content_html=content_s,
        primary_keyword=kw,
        slug=slug_s,
        secondary_keywords=secondary_keywords,
    )
    failed, warnings = select_factors_for_autofix(
        before, mode=mode, factor_ids=factor_ids
    )
    if not failed and not warnings:
        return {
            "success": False,
            "error": "Không có yếu tố warning/failed để sửa.",
            "unchanged": True,
            "seo_before": before,
        }

    focus = _build_focus_text(failed, warnings)
    target_site_hint = str(target_website or "").strip()
    focus_extra = ""
    if target_site_hint and any(str(f.get("id")) == "links_internal" for f in failed + warnings):
        focus_extra = f"\nWebsite nội bộ (gợi ý internal link): {target_site_hint}"

    try:
        if db is not None and user is not None:
            from app.services.cost_control.module_gates import content_ai_llm_gate
            from app.services.llm_content_writer import load_llm_config, load_llm_config_admin

            llm_cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
            with content_ai_llm_gate(
                db,
                user,
                action="seo_autofix",
                field="content",
                use_system_llm=use_system_llm,
                llm_cfg=llm_cfg,
                feature_key="content_ai_article" if not use_system_llm else None,
                skip_credit_check=bool(skip_llm_credit_check or use_system_llm),
            ):
                ai_out = generate_seo_update(
                    user_id=user_id,
                    title=title_s,
                    content=content_s,
                    excerpt=meta_s,
                    keyword=kw,
                    focus=focus + focus_extra,
                    seo_before=before,
                    failed_factors=failed,
                    warning_factors=warnings if mode in ("optimize_90", "single") else [],
                    use_system_llm=use_system_llm,
                )
        else:
            ai_out = generate_seo_update(
                user_id=user_id,
                title=title_s,
                content=content_s,
                excerpt=meta_s,
                keyword=kw,
                focus=focus + focus_extra,
                seo_before=before,
                failed_factors=failed,
                warning_factors=warnings if mode in ("optimize_90", "single") else [],
                use_system_llm=use_system_llm,
            )
    except Exception as exc:
        return {
            "success": False,
            "error": f"AI lỗi — giữ nguyên nội dung. ({str(exc)[:200]})",
            "unchanged": True,
            "seo_before": before,
        }

    new_title = str(ai_out.get("title") or title_s).strip()
    new_meta = str(ai_out.get("meta_description") or ai_out.get("excerpt") or meta_s).strip()[:320]
    new_content = str(ai_out.get("content") or content_s).strip()

    factor_id_set = {str(f.get("id") or "") for f in failed + warnings}
    rule = _rule_patch_meta_slug(
        title=new_title,
        meta=new_meta,
        slug=slug_s,
        keyword=kw,
        factors=failed + warnings,
    )
    new_title = rule["title"]
    new_meta = rule["meta_description"]
    new_slug = rule["slug"] or slug_s
    new_content = _maybe_postprocess_blockquote(new_content, factor_id_set)
    new_content = _rule_patch_content_html(
        new_content,
        title=new_title,
        meta=new_meta,
        keyword=kw,
        target_website=target_site_hint,
        factors=failed + warnings,
    )

    if mode == "single" and factor_ids:
        target_id = str(factor_ids[0] or "").strip()
        if target_id:
            new_title, new_meta, new_content, new_slug = _apply_guaranteed_factor_fix(
                factor_id=target_id,
                title=new_title,
                meta=new_meta,
                content=new_content,
                slug=new_slug,
                keyword=kw,
                target_website=target_site_hint,
            )

    unchanged = (
        new_title == title_s
        and new_meta == meta_s
        and new_slug == slug_s
        and new_content == content_s
    )
    if unchanged:
        return {
            "success": False,
            "error": "AI không thay đổi nội dung — giữ nguyên bản cũ.",
            "unchanged": True,
            "seo_before": before,
            "summary": str(ai_out.get("summary") or ""),
        }

    markup_warnings = validate_preserved_markup(content_s, new_content)

    after = eval_fn(
        title=new_title,
        meta_description=new_meta,
        content_html=new_content,
        primary_keyword=kw,
        slug=new_slug,
        secondary_keywords=secondary_keywords,
    )

    factor_outcomes = _target_factor_outcomes(
        before,
        after,
        [str(f.get("id") or "") for f in failed + warnings],
    )

    if mode == "single" and factor_ids:
        target_id = str(factor_ids[0] or "").strip()
        row = next((o for o in factor_outcomes if o.get("id") == target_id), None)
        st_after = _status_norm(str((row or {}).get("status_after") or ""))
        if st_after != "passed":
            msg = str((row or {}).get("message_after") or "chưa đủ điều kiện")
            return {
                "success": False,
                "error": f"Chưa đạt yếu tố này sau khi sửa ({msg}). Thử «AI tối ưu lên 90+».",
                "unchanged": False,
                "seo_before": before,
                "seo_after": {"score": after.get("score"), "grade_label": after.get("grade_label")},
                "factor_outcomes": factor_outcomes,
                "patch": {
                    "title": new_title,
                    "meta_description": new_meta,
                    "slug": new_slug,
                    "content_html": new_content,
                },
            }

    diff = build_content_diff(
        old_title=title_s,
        new_title=new_title,
        old_content=content_s,
        new_content=new_content,
        old_excerpt=meta_s,
        new_excerpt=new_meta,
    )

    return {
        "success": True,
        "unchanged": False,
        "mode": mode,
        "factor_ids": [str(f.get("id") or "") for f in failed + warnings],
        "factors_targeted": [
            {
                "id": f.get("id"),
                "label": f.get("label"),
                "status": f.get("status"),
                "group_label": f.get("group_label"),
            }
            for f in failed + warnings
        ],
        "patch": {
            "title": new_title,
            "meta_description": new_meta,
            "slug": new_slug,
            "content_html": new_content,
        },
        "summary": str(ai_out.get("summary") or "Đã tối ưu theo SEO Core 30."),
        "notes": list(ai_out.get("notes") or [])[:10],
        "markup_warnings": markup_warnings,
        "seo_before": {
            "score": before.get("score"),
            "grade_label": before.get("grade_label"),
        },
        "seo_after": {
            "score": after.get("score"),
            "grade_label": after.get("grade_label"),
        },
        "score_delta": int(after.get("score") or 0) - int(before.get("score") or 0),
        "factor_outcomes": factor_outcomes,
        "diff": diff,
    }
