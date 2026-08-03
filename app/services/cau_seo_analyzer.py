"""SEO analyzer cho popup Sửa SEO (Content Auto Update) — không dùng chung tab khác."""

from __future__ import annotations

import difflib
import html
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.content_ai_publish_checklist import (
    _grade_from_score,
    _make_factor,
    _make_group,
    evaluate_publish_checklist,
)
from app.services.content_ai_seo_autofix import _FACTOR_SCOPES

_SKIP_LINK_PREFIXES = ("javascript:", "mailto:", "tel:", "#")

_FACTOR_LOCATION_LABELS: dict[str, str] = {
    "title_keyword": "Title",
    "intent_title_match": "Title",
    "meta_quality": "Meta description",
    "slug_seo": "Slug",
    "heading_single_h1": "H1",
    "heading_h2_count": "H2",
    "heading_hierarchy": "H2",
    "intent_h1_keyword": "H1",
    "links_internal": "Internal link",
    "links_external": "External link",
    "links_anchor_text": "Internal link",
    "media_images": "Ảnh",
    "media_alt_text": "Ảnh",
    "media_schema_blockquote": "Schema",
    "keyword_in_body": "Đoạn văn",
    "keyword_density": "Đoạn văn",
    "semantic_keywords": "Đoạn văn",
    "depth_word_count": "Đoạn văn",
    "depth_paragraphs": "Đoạn văn",
    "depth_per_section": "Đoạn văn",
    "readability_sentence": "Đoạn văn",
    "readability_paragraphs": "Đoạn văn",
    "readability_formatting": "Đoạn văn",
    "helpful_word_count": "Đoạn văn",
    "helpful_actionable": "Đoạn văn",
    "helpful_faq_conclusion": "Đoạn văn",
    "eeat_specifics": "Đoạn văn",
    "eeat_unique_value": "Đoạn văn",
    "eeat_trust_signals": "Đoạn văn",
    "intent_answer_early": "Đoạn văn",
}

_FIELD_LOCATION_LABELS = {
    "title": "Title",
    "meta_description": "Meta description",
    "slug": "Slug",
    "content_html": "Nội dung HTML",
}

_CONTENT_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "p", "li", "blockquote", "figure", "ul", "ol")


def normalize_vietnamese_seo_text(text: str) -> str:
    """Lowercase, bỏ dấu tiếng Việt, chuẩn hóa khoảng trắng."""
    raw = unicodedata.normalize("NFD", str(text or "").strip().lower())
    raw = raw.replace("đ", "d").replace("Đ", "d")
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = re.sub(r"[^\w\s-]", " ", raw, flags=re.UNICODE)
    raw = re.sub(r"[\s_\-]+", " ", raw).strip()
    return raw


def _compact_seo_text(text: str) -> str:
    return normalize_vietnamese_seo_text(text).replace(" ", "").replace("-", "")


def is_internal_link(href: str, post_url: str = "") -> bool:
    """Internal nếu path /... hoặc cùng domain với bài viết."""
    h = str(href or "").strip()
    if not h:
        return False
    lower = h.lower()
    if lower.startswith(_SKIP_LINK_PREFIXES):
        return False
    if h.startswith("/"):
        return True
    if "internal" in lower:
        return True
    try:
        link = urlparse(h if "://" in h else f"https://{h}")
        if link.scheme and link.scheme not in ("http", "https"):
            return False
        post = urlparse(str(post_url or "").strip())
        link_host = (link.netloc or "").lower().lstrip("www.")
        post_host = (post.netloc or "").lower().lstrip("www.")
        if link_host and post_host and link_host == post_host:
            return True
    except Exception:
        return False
    return False


def count_internal_links(content_html: str, post_url: str = "") -> int:
    try:
        soup = BeautifulSoup(str(content_html or "")[:800_000], "html.parser")
    except Exception:
        soup = BeautifulSoup("", "html.parser")
    n = 0
    for a in soup.find_all("a", href=True):
        if is_internal_link(str(a.get("href") or ""), post_url):
            n += 1
    if re.search(r"<!--\s*internal\s*:", str(content_html or ""), re.I):
        n = max(n, 1)
    return n


def has_wordpress_h1(title: str, content_html: str) -> bool:
    """WordPress dùng post.title làm H1 mặc định."""
    if str(title or "").strip():
        return True
    try:
        soup = BeautifulSoup(str(content_html or "")[:800_000], "html.parser")
        return bool(soup.find("h1"))
    except Exception:
        return False


def _wordpress_effective_h1_count(title: str, content_html: str) -> int:
    try:
        soup = BeautifulSoup(str(content_html or "")[:800_000], "html.parser")
        h1_n = len(soup.find_all("h1"))
    except Exception:
        h1_n = 0
    if h1_n > 0:
        return h1_n
    return 1 if str(title or "").strip() else 0


def slug_matches_keyword(slug: str, keyword: str) -> bool:
    """Slug đạt nếu chứa đủ token chính của keyword sau khi normalize."""
    slug_raw = str(slug or "").strip().lower()
    kw_raw = str(keyword or "").strip()
    if not slug_raw:
        return False
    if not kw_raw:
        return bool(re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug_raw))
    slug_compact = _compact_seo_text(slug_raw.replace("-", " "))
    slug_spaced = normalize_vietnamese_seo_text(slug_raw.replace("-", " "))
    tokens = [t for t in normalize_vietnamese_seo_text(kw_raw).split() if t]
    if not tokens:
        return True
    for token in tokens:
        if token in slug_compact:
            continue
        if token in slug_spaced.split():
            continue
        return False
    return True


def get_seo_fix_action(factor_id: str) -> dict[str, str]:
    """Phạm vi sửa AI cho từng yếu tố."""
    fid = str(factor_id or "").strip()
    scope = _FACTOR_SCOPES.get(fid, "content")
    labels = {
        "title": "Tiêu đề",
        "meta": "Meta description",
        "slug": "Slug",
        "content": "Nội dung",
    }
    return {
        "factor_id": fid,
        "scope": scope,
        "scope_label": labels.get(scope, "Nội dung"),
        "mode": "single",
    }


def _set_factor(result: dict[str, Any], factor: dict[str, Any]) -> None:
    fid = str(factor.get("id") or "")
    for g in result.get("groups") or []:
        for i, row in enumerate(g.get("factors") or []):
            if str(row.get("id") or "") == fid:
                g["factors"][i] = factor
                return


def _patch_internal_link_factor(result: dict[str, Any], *, internal_n: int) -> None:
    if internal_n >= 2:
        f = _make_factor(
            "links_internal", "Internal link", 3, "passed",
            f"Có {internal_n} liên kết nội bộ.", "Giữ 2–5 internal link phù hợp.",
        )
    elif internal_n >= 1:
        f = _make_factor(
            "links_internal", "Internal link", 3, "passed",
            f"Có {internal_n} internal link.", "Có thể thêm 1–2 internal link liên quan.",
        )
    else:
        f = _make_factor(
            "links_internal", "Internal link", 3, "failed",
            "Chưa có internal link.", "Thêm liên kết nội bộ tới bài/trang cùng website.",
        )
    _set_factor(result, f)


def _patch_h1_factors(
    result: dict[str, Any],
    *,
    title: str,
    content_html: str,
) -> None:
    try:
        soup = BeautifulSoup(str(content_html or "")[:800_000], "html.parser")
        h1s = soup.find_all("h1")
        h2s = soup.find_all("h2")
        h3s = soup.find_all("h3")
    except Exception:
        h1s, h2s, h3s = [], [], []

    effective_h1 = _wordpress_effective_h1_count(title, content_html)
    title_ok = bool(str(title or "").strip())

    if effective_h1 == 1:
        msg = "WordPress title đóng vai trò H1." if title_ok and not h1s else "Có đúng 1 thẻ H1."
        f_h1 = _make_factor("heading_single_h1", "Một H1 duy nhất", 2, "passed", msg, "Không thêm H1 phụ.")
    elif effective_h1 == 0:
        f_h1 = _make_factor(
            "heading_single_h1", "Một H1 duy nhất", 2, "failed",
            "Thiếu title và không có H1 trong nội dung.", "Nhập tiêu đề hoặc thêm một H1 chính.",
        )
    else:
        f_h1 = _make_factor(
            "heading_single_h1", "Một H1 duy nhất", 2, "failed",
            f"Có {len(h1s)} H1 trong nội dung.", "Chỉ giữ một H1, chuyển heading phụ sang H2.",
        )
    _set_factor(result, f_h1)

    if (title_ok or h1s) and h2s and not h3s:
        f_hier = _make_factor(
            "heading_hierarchy", "Thứ bậc heading", 3, "passed",
            "H1 (title) → H2 hợp lý.", "Có thể thêm H3 cho mục con nếu cần.",
        )
    elif not title_ok and not h1s and h2s:
        f_hier = _make_factor(
            "heading_hierarchy", "Thứ bậc heading", 3, "warning",
            "Thiếu H1, chỉ có H2.", "Nhập title WordPress hoặc thêm H1.",
        )
    elif h3s and not h2s:
        f_hier = _make_factor(
            "heading_hierarchy", "Thứ bậc heading", 3, "failed",
            "Có H3 nhưng thiếu H2.", "Sửa thứ bậc: H2 trước H3.",
        )
    else:
        f_hier = _make_factor(
            "heading_hierarchy", "Thứ bậc heading", 3, "passed",
            "Thứ bậc heading ổn.", "Tránh nhảy cấp heading.",
        )
    _set_factor(result, f_hier)


def _patch_slug_factor(result: dict[str, Any], *, slug: str, keyword: str) -> None:
    slug_s = str(slug or "").strip().lower()
    pk = str(keyword or "").strip()
    if not slug_s:
        f = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "warning", "Chưa có slug.", "Tạo slug ngắn, có từ khóa, không dấu.")
    elif pk and slug_matches_keyword(slug_s, pk):
        f = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "passed", "Slug khớp từ khóa chính.", "Giữ slug ngắn gọn, dùng dấu gạch ngang.")
    elif re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", slug_s):
        f = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "warning", "Slug OK nhưng chưa khớp từ khóa.", "Thêm token từ khóa vào slug.")
    else:
        f = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "failed", "Slug chưa chuẩn SEO.", "Dùng chữ thường, gạch ngang, không dấu.")
    _set_factor(result, f)


def _finalize_cau_result(result: dict[str, Any]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    all_factors: list[dict[str, Any]] = []
    for g in result.get("groups") or []:
        rebuilt = _make_group(
            str(g.get("id") or ""),
            str(g.get("label") or ""),
            list(g.get("factors") or []),
        )
        groups.append(rebuilt)
        for f in rebuilt.get("factors") or []:
            clean = {k: v for k, v in f.items() if not k.startswith("_")}
            if str(clean.get("status") or "") in ("failed", "warning"):
                clean["fix_action"] = get_seo_fix_action(str(clean.get("id") or ""))
            all_factors.append(clean)

    total = round(sum(float(g.get("score") or 0) for g in groups), 1)
    tier, grade_label = _grade_from_score(total)
    clean_groups = []
    for g in groups:
        clean_groups.append({
            "id": g["id"],
            "label": g["label"],
            "max_score": g["max_score"],
            "score": g["score"],
            "factors": [{k: v for k, v in f.items() if not k.startswith("_")} for f in g.get("factors") or []],
        })

    out = dict(result)
    out["groups"] = clean_groups
    out["factors"] = all_factors
    out["score_raw"] = total
    out["score"] = int(round(total))
    out["grade_tier"] = tier
    out["grade_label"] = grade_label
    return out


def evaluate_cau_modal_seo(
    *,
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
    post_url: str = "",
) -> dict[str, Any]:
    """Chấm SEO cho popup Auto Update với rule WordPress."""
    base = evaluate_publish_checklist(
        title=title,
        meta_description=meta_description,
        content_html=content_html,
        primary_keyword=primary_keyword,
        slug=slug,
        secondary_keywords=secondary_keywords,
    )
    internal_n = count_internal_links(content_html, post_url)
    _patch_internal_link_factor(base, internal_n=internal_n)
    _patch_h1_factors(base, title=title, content_html=content_html)
    _patch_slug_factor(base, slug=slug, keyword=primary_keyword)
    return _finalize_cau_result(base)


def _factor_location_label(factor_id: str, field_key: str = "") -> str:
    fid = str(factor_id or "").strip()
    if fid and fid in _FACTOR_LOCATION_LABELS:
        return _FACTOR_LOCATION_LABELS[fid]
    return _FIELD_LOCATION_LABELS.get(field_key, "Đoạn văn")


def _esc_html(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def _highlight_inline_diff(old: str, new: str) -> tuple[str, str]:
    old_s = str(old or "")
    new_s = str(new or "")
    if old_s == new_s:
        return _esc_html(old_s), _esc_html(new_s)
    sm = difflib.SequenceMatcher(None, old_s, new_s)
    old_parts: list[str] = []
    new_parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            old_parts.append(_esc_html(old_s[i1:i2]))
            new_parts.append(_esc_html(new_s[j1:j2]))
        elif tag == "delete":
            old_parts.append(f'<mark class="cau-diff-del">{_esc_html(old_s[i1:i2])}</mark>')
        elif tag == "insert":
            new_parts.append(f'<mark class="cau-diff-add">{_esc_html(new_s[j1:j2])}</mark>')
        elif tag == "replace":
            old_parts.append(f'<mark class="cau-diff-del">{_esc_html(old_s[i1:i2])}</mark>')
            new_parts.append(f'<mark class="cau-diff-add">{_esc_html(new_s[j1:j2])}</mark>')
    return "".join(old_parts), "".join(new_parts)


def _strip_html_text(value: str) -> str:
    try:
        soup = BeautifulSoup(str(value or "")[:120_000], "html.parser")
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def _content_blocks(html_value: str) -> list[tuple[str, str, str]]:
    try:
        soup = BeautifulSoup(str(html_value or "")[:800_000], "html.parser")
    except Exception:
        return []
    blocks: list[tuple[str, str, str]] = []
    for el in soup.find_all(_CONTENT_BLOCK_TAGS):
        outer = str(el)
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if text or el.name in ("figure", "img"):
            blocks.append((el.name, text, outer))
    return blocks


def _extract_content_change_snippets(old_html: str, new_html: str, *, max_snippets: int = 3) -> list[dict[str, Any]]:
    old_blocks = _content_blocks(old_html)
    new_blocks = _content_blocks(new_html)
    snippets: list[dict[str, Any]] = []
    if not old_blocks and not new_blocks:
        if (old_html or "").strip() != (new_html or "").strip():
            old_txt = _strip_html_text(old_html)[:1200]
            new_txt = _strip_html_text(new_html)[:1200]
            old_h, new_h = _highlight_inline_diff(old_txt, new_txt)
            snippets.append({
                "location": "Đoạn văn",
                "location_key": "content",
                "old_text": old_txt[:500],
                "new_text": new_txt[:500],
                "old_html": old_h,
                "new_html": new_h,
                "is_snippet": True,
            })
        return snippets

    matcher = difflib.SequenceMatcher(
        None,
        [b[1] for b in old_blocks],
        [b[1] for b in new_blocks],
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_slice = old_blocks[i1:i2]
        new_slice = new_blocks[j1:j2]
        old_join = " ".join(x[1] for x in old_slice).strip()
        new_join = " ".join(x[1] for x in new_slice).strip()
        if not old_join and not new_join:
            continue
        tag_name = (new_slice[0][0] if new_slice else old_slice[0][0] if old_slice else "p")
        loc_map = {"h1": "H1", "h2": "H2", "h3": "H2", "h4": "H2", "figure": "Ảnh", "img": "Ảnh"}
        location = loc_map.get(tag_name, "Đoạn văn")
        old_outer = "\n".join(x[2] for x in old_slice)[:2500]
        new_outer = "\n".join(x[2] for x in new_slice)[:2500]
        old_h, new_h = _highlight_inline_diff(
            _strip_html_text(old_outer)[:1200] or old_join[:1200],
            _strip_html_text(new_outer)[:1200] or new_join[:1200],
        )
        snippets.append({
            "location": location,
            "location_key": tag_name,
            "old_text": (old_join or _strip_html_text(old_outer))[:500],
            "new_text": (new_join or _strip_html_text(new_outer))[:500],
            "old_html": old_h,
            "new_html": new_h,
            "is_snippet": True,
        })
        if len(snippets) >= max_snippets:
            break
    return snippets


def _factor_status_rank(status: str) -> int:
    return {"failed": 0, "warning": 1, "passed": 2}.get(str(status or "").lower(), -1)


def _factor_status_improved(before: str, after: str) -> bool:
    return _factor_status_rank(after) > _factor_status_rank(before)


def _resolve_fix_status(factor_id: str, fix_result: dict[str, Any]) -> str:
    if fix_result.get("error"):
        return "failed"
    if fix_result.get("unchanged"):
        return "no_change"
    outcomes = fix_result.get("factor_outcomes") or []
    row = next((o for o in outcomes if str(o.get("id") or "") == factor_id), None)
    st_before = str((row or {}).get("status_before") or "").lower()
    st_after = str((row or {}).get("status_after") or "").lower()
    if st_after == "passed":
        return "fixed"
    if _factor_status_improved(st_before, st_after):
        return "fixed"
    patch = fix_result.get("patch") or {}
    if patch and fix_result.get("success"):
        return "fixed"
    if patch:
        return "failed"
    return "no_change"


def _score_value(seo: dict[str, Any] | None) -> int | None:
    if not seo:
        return None
    if seo.get("score") is not None:
        return int(seo.get("score") or 0)
    return None


def build_cau_fix_change_report(
    *,
    factor_id: str,
    before_title: str,
    before_meta: str,
    before_slug: str,
    before_content: str,
    fix_result: dict[str, Any],
) -> dict[str, Any]:
    """Báo cáo chi tiết thay đổi sau AI fix (popup Auto Update)."""
    fid = str(factor_id or "").strip()
    patch = fix_result.get("patch") or {}
    targeted = fix_result.get("factors_targeted") or []
    factor_row = next((f for f in targeted if str(f.get("id") or "") == fid), None) or {}
    factor_label = str(factor_row.get("label") or fid or "Yếu tố SEO")
    outcomes = fix_result.get("factor_outcomes") or []
    outcome = next((o for o in outcomes if str(o.get("id") or "") == fid), None) or {}

    seo_before = fix_result.get("seo_before") or {}
    seo_after = fix_result.get("seo_after") or {}
    score_before = _score_value(seo_before if isinstance(seo_before, dict) and seo_before.get("groups") else seo_before)
    score_after = _score_value(seo_after)
    if score_before is None and isinstance(seo_before, dict):
        score_before = seo_before.get("score")
    if score_after is None and isinstance(seo_after, dict):
        score_after = seo_after.get("score")

    status = _resolve_fix_status(fid, fix_result)
    reason_parts: list[str] = []
    if fix_result.get("summary"):
        reason_parts.append(str(fix_result.get("summary")))
    if outcome.get("message_after"):
        reason_parts.append(str(outcome.get("message_after")))
    for note in (fix_result.get("notes") or [])[:3]:
        if note:
            reason_parts.append(str(note))
    if fix_result.get("error") and status != "fixed":
        reason_parts.append(str(fix_result.get("error")))
    reason = " ".join(reason_parts).strip() or f"Tối ưu yếu tố «{factor_label}»."

    after_title = str(patch.get("title") if "title" in patch else before_title)
    after_meta = str(patch.get("meta_description") if "meta_description" in patch else before_meta)
    after_slug = str(patch.get("slug") if "slug" in patch else before_slug)
    after_content = str(patch.get("content_html") if "content_html" in patch else before_content)

    change_items: list[dict[str, Any]] = []
    patches = fix_result.get("patches") or []
    patch_fields: set[str] = set()
    for prow in patches:
        if not isinstance(prow, dict):
            continue
        field_key = str(prow.get("field") or "").strip()
        old_v = str(prow.get("old_value") if prow.get("old_value") is not None else "")
        new_v = str(prow.get("new_value") if prow.get("new_value") is not None else "")
        if not field_key or (not old_v.strip() and not new_v.strip()):
            continue
        preview_full = (
            fid == "modal_content_append"
            or bool(prow.get("preview_full_content"))
        )
        if field_key == "content_html" and preview_full:
            change_items.append({
                "field": field_key,
                "location": str(prow.get("position") or _factor_location_label(fid, field_key)),
                "location_key": field_key,
                "status": status,
                "old_text": _strip_html_text(old_v)[:1500] if old_v.strip().startswith("<") else old_v[:1500],
                "new_text": _strip_html_text(new_v)[:1500] if new_v.strip().startswith("<") else new_v[:1500],
                "old_html": "",
                "new_html": "",
                "is_snippet": False,
                "preview_full_content": True,
                "reason": str(prow.get("reason") or ""),
                "confidence": prow.get("confidence"),
                "old_raw_html": old_v[:100_000] if old_v.strip() else "",
                "new_raw_html": new_v[:100_000] if new_v.strip() else "",
            })
            patch_fields.add(field_key)
            continue
        if field_key == "content_html":
            old_txt = _strip_html_text(old_v)[:500] if old_v.strip().startswith("<") else old_v[:500]
            new_txt = _strip_html_text(new_v)[:500] if new_v.strip().startswith("<") else new_v[:500]
        elif field_key == "meta_description":
            old_txt = re.sub(r"\s+", " ", str(old_v or "").replace("<p>", "").replace("</p>", ""))[:500]
            new_txt = re.sub(r"\s+", " ", str(new_v or "").replace("<p>", "").replace("</p>", ""))[:500]
        else:
            old_txt, new_txt = old_v[:500], new_v[:500]
        if old_txt.strip() == new_txt.strip():
            continue
        old_h, new_h = _highlight_inline_diff(old_txt, new_txt)
        change_items.append({
            "field": field_key,
            "location": str(prow.get("position") or _factor_location_label(fid, field_key)),
            "location_key": field_key,
            "status": status,
            "old_text": old_txt,
            "new_text": new_txt,
            "old_html": old_h,
            "new_html": new_h,
            "is_snippet": field_key == "content_html",
            "reason": str(prow.get("reason") or ""),
            "confidence": prow.get("confidence"),
        })
        if field_key == "content_html":
            change_items[-1]["old_raw_html"] = old_v[:8000] if old_v.strip().startswith("<") else ""
            change_items[-1]["new_raw_html"] = new_v[:8000] if new_v.strip().startswith("<") else ""
        patch_fields.add(field_key)

    scalar_fields = (
        ("title", before_title, after_title),
        ("meta_description", before_meta, after_meta),
        ("slug", before_slug, after_slug),
    )
    for field_key, old_val, new_val in scalar_fields:
        if field_key in patch_fields:
            continue
        if str(old_val or "").strip() == str(new_val or "").strip():
            continue
        old_h, new_h = _highlight_inline_diff(str(old_val or ""), str(new_val or ""))
        change_items.append({
            "field": field_key,
            "location": _factor_location_label(fid, field_key),
            "location_key": field_key,
            "status": status,
            "old_text": str(old_val or "")[:500],
            "new_text": str(new_val or "")[:500],
            "old_html": old_h,
            "new_html": new_h,
            "is_snippet": False,
        })

    if "content_html" not in patch_fields and str(before_content or "").strip() != str(after_content or "").strip():
        snippets = _extract_content_change_snippets(before_content, after_content)
        if snippets:
            for sn in snippets:
                change_items.append({
                    "field": "content_html",
                    "location": sn.get("location") or _factor_location_label(fid, "content_html"),
                    "location_key": sn.get("location_key") or "content",
                    "status": status,
                    "old_text": sn.get("old_text") or "",
                    "new_text": sn.get("new_text") or "",
                    "old_html": sn.get("old_html") or "",
                    "new_html": sn.get("new_html") or "",
                    "is_snippet": True,
                    "old_raw_html": before_content[:8000],
                    "new_raw_html": after_content[:8000],
                })
        else:
            old_txt = _strip_html_text(before_content)[:800]
            new_txt = _strip_html_text(after_content)[:800]
            old_h, new_h = _highlight_inline_diff(old_txt, new_txt)
            change_items.append({
                "field": "content_html",
                "location": _factor_location_label(fid, "content_html"),
                "location_key": "content",
                "status": status,
                "old_text": old_txt[:500],
                "new_text": new_txt[:500],
                "old_html": old_h,
                "new_html": new_h,
                "is_snippet": True,
                "old_raw_html": before_content[:8000],
                "new_raw_html": after_content[:8000],
            })

    status_labels = {
        "fixed": "Đã sửa",
        "no_change": "Không cần sửa",
        "failed": "Không sửa được",
    }

    if not change_items and status == "failed":
        factor_msg = str(factor_row.get("message") or "").strip()
        err_msg = str(fix_result.get("error") or "Không sửa được").strip()
        change_items.append({
            "field": "info",
            "location": _factor_location_label(fid),
            "location_key": "info",
            "status": status,
            "old_text": (factor_msg or err_msg)[:500],
            "new_text": err_msg[:500],
            "old_html": _esc_html((factor_msg or err_msg)[:500]),
            "new_html": _esc_html(err_msg[:500]),
            "is_snippet": False,
        })

    if not change_items and status == "no_change":
        display = str(factor_row.get("message") or fix_result.get("summary") or reason).strip()
        change_items.append({
            "field": "info",
            "location": _factor_location_label(fid),
            "location_key": "info",
            "status": status,
            "old_text": display[:500],
            "new_text": "Không cần thay đổi",
            "old_html": _esc_html(display[:500]),
            "new_html": _esc_html("Không cần thay đổi"),
            "is_snippet": False,
        })

    if not change_items and status == "fixed":
        snap_b = fix_result.get("factor_snap_before") if isinstance(fix_result.get("factor_snap_before"), dict) else {}
        snap_a = fix_result.get("factor_snap_after") if isinstance(fix_result.get("factor_snap_after"), dict) else {}
        scalar_before = {
            "title": before_title,
            "meta_description": before_meta,
            "slug": before_slug,
            "content_html": before_content,
        }
        scalar_after = {
            "title": after_title,
            "meta_description": after_meta,
            "slug": after_slug,
            "content_html": after_content,
        }
        pairs = (
            ("title", _factor_location_label(fid, "title")),
            ("meta_description", _factor_location_label(fid, "meta_description")),
            ("slug", _factor_location_label(fid, "slug")),
            ("content_html", _factor_location_label(fid, "content_html")),
        )
        for field_key, location in pairs:
            old_raw = str(snap_b.get(field_key) or scalar_before.get(field_key) or "")
            new_raw = str(snap_a.get(field_key) or patch.get(field_key) or scalar_after.get(field_key) or "")
            if not new_raw.strip() or old_raw.strip() == new_raw.strip():
                continue
            if field_key == "content_html":
                snippets = _extract_content_change_snippets(old_raw, new_raw)
                if snippets:
                    change_items.extend({**sn, "field": field_key, "status": status} for sn in snippets)
                    continue
                old_txt = _strip_html_text(old_raw)[:1200]
                new_txt = _strip_html_text(new_raw)[:1200]
            elif field_key == "meta_description":
                old_txt = re.sub(r"\s+", " ", old_raw.replace("<p>", "").replace("</p>", ""))[:500]
                new_txt = re.sub(r"\s+", " ", new_raw.replace("<p>", "").replace("</p>", ""))[:500]
            else:
                old_txt, new_txt = old_raw[:500], new_raw[:500]
            old_h, new_h = _highlight_inline_diff(old_txt, new_txt)
            change_items.append({
                "field": field_key,
                "location": location,
                "location_key": field_key,
                "status": status,
                "old_text": old_txt,
                "new_text": new_txt,
                "old_html": old_h,
                "new_html": new_h,
                "is_snippet": field_key == "content_html",
                "reason": str(fix_result.get("summary") or ""),
                "old_raw_html": old_raw[:8000] if field_key == "content_html" else "",
                "new_raw_html": new_raw[:8000] if field_key == "content_html" else "",
            })

    snap_before_out = fix_result.get("factor_snap_before") if isinstance(fix_result.get("factor_snap_before"), dict) else {}
    snap_after_out = fix_result.get("factor_snap_after") if isinstance(fix_result.get("factor_snap_after"), dict) else {}

    return {
        "factor_id": fid,
        "factor_label": factor_label,
        "location": _factor_location_label(fid),
        "reason": reason,
        "status": status,
        "status_label": status_labels.get(status, status),
        "score_before": score_before,
        "score_after": score_after,
        "score_delta": (int(score_after) - int(score_before)) if score_before is not None and score_after is not None else fix_result.get("score_delta"),
        "factor_status_before": outcome.get("status_before"),
        "factor_status_after": outcome.get("status_after"),
        "items": change_items,
        "summary": str(fix_result.get("summary") or ""),
        "error": str(fix_result.get("error") or ""),
        "factor_snap_before": snap_before_out,
        "factor_snap_after": snap_after_out,
    }


def run_cau_modal_seo_fix(
    *,
    user_id: int,
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
    post_url: str = "",
    factor_id: str,
    category_name: str = "",
) -> dict[str, Any]:
    """Sửa một yếu tố SEO trong popup Auto Update (fast engine)."""
    from app.services.cau_seo_fix_engine import fix_cau_factor_fast

    return fix_cau_factor_fast(
        user_id=user_id,
        title=title,
        meta_description=meta_description,
        content_html=content_html,
        primary_keyword=primary_keyword,
        slug=slug,
        secondary_keywords=secondary_keywords,
        post_url=post_url,
        category_name=category_name,
        factor_id=factor_id,
        use_cache=True,
        use_system_llm=True,
    )


def run_cau_modal_seo_fix_batch(
    *,
    user_id: int,
    factor_ids: list[str],
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
    post_url: str = "",
    category_name: str = "",
) -> dict[str, Any]:
    """Sửa nhiều yếu tố song song — chấm SEO 1 lần."""
    from app.services.cau_seo_fix_engine import fix_cau_factors_parallel

    return fix_cau_factors_parallel(
        user_id=user_id,
        factor_ids=factor_ids,
        title=title,
        meta_description=meta_description,
        content_html=content_html,
        primary_keyword=primary_keyword,
        slug=slug,
        secondary_keywords=secondary_keywords,
        post_url=post_url,
        category_name=category_name,
        use_system_llm=True,
    )
