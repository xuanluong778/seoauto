"""
Publish Quality Gate — kiểm tra chất lượng trước publish (soft gate, không chặn cứng server-side).
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.content_ai_score import (
    _CTA_RE,
    _FAQ_HEADING_RE,
    _kw_in_text,
    _parse_html_safe,
    evaluate_content_score,
)

_PUBLISH_TARGETS = frozenset({"wordpress", "haravan"})


def _check_schema_issues(soup: BeautifulSoup) -> list[str]:
    issues: list[str] = []
    if not soup:
        return issues
    for script in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(f"JSON-LD không parse được: {exc.msg[:80]}")
            continue

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                t = str(node.get("@type") or "").lower()
                if t == "faqpage":
                    ent = node.get("mainEntity")
                    if not ent:
                        issues.append("FAQPage schema thiếu mainEntity.")
                    elif isinstance(ent, list) and len(ent) < 1:
                        issues.append("FAQPage schema mainEntity rỗng.")
                if t in {"article", "blogposting"}:
                    if not str(node.get("headline") or "").strip():
                        issues.append("Article schema thiếu headline.")
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(data)
    return issues


def _internal_link_count(soup: BeautifulSoup, target_website: str) -> int:
    from app.services.content_ai_score import _count_internal_external

    internal, _, _ = _count_internal_external(soup, target_website)
    return internal


def _has_cta(body_text: str) -> bool:
    low = (body_text or "").lower()
    tail = low[-1200:] if len(low) > 1200 else low
    return bool(_CTA_RE.search(tail) or _CTA_RE.search(low))


def _image_alt_issues(soup: BeautifulSoup) -> list[str]:
    from app.services.content_ai_score import _GENERIC_ALT_RE

    issues: list[str] = []
    for img in soup.find_all("img"):
        alt = str(img.get("alt") or "").strip()
        if len(alt) < 8 or _GENERIC_ALT_RE.match(alt):
            issues.append("Ảnh thiếu alt hoặc alt chung chung.")
            break
    return issues


def evaluate_publish_gate(
    *,
    title: str = "",
    slug: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    html_content: str = "",
    target_word_count: int | None = None,
    target_website: str = "",
    internal_links: list[dict[str, Any]] | None = None,
    publish_target: str = "wordpress",
    featured_image_url: str = "",
) -> dict[str, Any]:
    """
    Soft publish gate: ``can_publish`` = True chỉ khi ``severity`` là ``pass`` (UI vẫn cho «Vẫn publish»).
    """
    target = (publish_target or "wordpress").strip().lower()
    if target not in _PUBLISH_TARGETS:
        target = "wordpress"

    score_data = evaluate_content_score(
        title=title,
        slug=slug,
        meta_description=meta_description,
        primary_keyword=primary_keyword,
        secondary_keywords=secondary_keywords,
        html_content=html_content,
        target_word_count=target_word_count,
        target_website=target_website,
        internal_links=internal_links,
    )
    total_score = int(score_data.get("total_score") or 0)
    grade = str(score_data.get("grade") or "F")
    details: dict[str, Any] = score_data.get("detail_scores") or {}

    blockers: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = list(score_data.get("suggestions") or [])
    required_fixes: list[str] = []
    optional_fixes: list[str] = []

    title_s = (title or "").strip()
    meta_s = (meta_description or "").strip()
    slug_s = (slug or "").strip().strip("/")
    html_s = (html_content or "").strip()
    pk = (primary_keyword or "").strip()

    if not title_s:
        blockers.append("Thiếu title — bắt buộc trước khi publish.")
        required_fixes.append("Nhập tiêu đề bài viết (title).")
    if not meta_s:
        blockers.append("Thiếu meta description.")
        required_fixes.append("Nhập meta description (~140–160 ký tự).")
    if not slug_s:
        blockers.append("Thiếu slug URL.")
        required_fixes.append("Nhập slug (URL thân thiện).")
    if not html_s:
        blockers.append("Thiếu html_content — chưa có nội dung bài.")
        required_fixes.append("Thêm nội dung vào editor hoặc tạo content.")
    if not pk:
        blockers.append("Thiếu primary_keyword (từ khóa chính).")
        required_fixes.append("Nhập từ khóa chính ở form.")

    soup = _parse_html_safe(html_s) if html_s else BeautifulSoup("", "html.parser")
    body_text = soup.get_text(" ", strip=True) if html_s else ""
    text_len = len(body_text)

    if html_s and text_len < 80:
        blockers.append("HTML rỗng hoặc quá ít văn bản — không đủ để publish.")
        required_fixes.append("Mở rộng nội dung bài (tối thiểu vài trăm từ).")
    elif html_s and "<" in html_s and text_len < 40:
        blockers.append("HTML có thể không parse được — không đọc được nội dung.")
        required_fixes.append("Kiểm tra lại HTML trong editor (Visual/Code).")

    if pk and html_s and text_len >= 40:
        if not _kw_in_text(title_s, pk):
            required_fixes.append("Đưa từ khóa chính vào title.")
        if not _kw_in_text(meta_s, pk):
            optional_fixes.append("Thêm từ khóa chính vào meta description.")
        h1 = soup.find("h1")
        h1_text = h1.get_text(" ", strip=True) if h1 else ""
        if not h1_text:
            required_fixes.append("Thêm một thẻ H1 chứa từ khóa chính.")
        elif not _kw_in_text(h1_text, pk):
            required_fixes.append("Từ khóa chính cần có trong H1.")
        first_words = " ".join(body_text.split()[:120])
        if not _kw_in_text(first_words, pk):
            required_fixes.append("Từ khóa chính cần xuất hiện trong ~100 từ đầu bài.")

    h2s = soup.find_all("h2") if html_s else []
    if html_s and len(h2s) < 2:
        warnings.append("Cấu trúc heading: cần ít nhất 2 mục H2.")
        optional_fixes.append("Chia bài thành các section H2 rõ ràng.")
    if html_s and not any(_FAQ_HEADING_RE.search(h.get_text(" ", strip=True)) for h in h2s):
        optional_fixes.append("Nên có mục FAQ (H2) trước khi publish.")

    hs = details.get("heading_structure") or {}
    if int(hs.get("score") or 0) < 50:
        warnings.append("Điểm cấu trúc heading thấp — kiểm tra H1/H2/H3.")

    if html_s:
        internal_n = _internal_link_count(soup, target_website)
        if internal_n < 1:
            warnings.append("Chưa có internal link trong bài.")
            optional_fixes.append("Thêm 2–4 internal link (Tìm bài liên quan → Đi link).")
        elif internal_n < 2:
            optional_fixes.append("Nên có ít nhất 2 internal link trước publish.")

        if not _has_cta(body_text):
            warnings.append("Chưa có CTA rõ ở cuối bài (liên hệ, báo giá, đăng ký…).")
            optional_fixes.append("Thêm đoạn kêu gọi hành động ở cuối bài.")

        for alt_issue in _image_alt_issues(soup):
            warnings.append(alt_issue)
            optional_fixes.append("Bổ sung alt mô tả cho từng ảnh (8–12 từ).")

        for schema_err in _check_schema_issues(soup):
            warnings.append(schema_err)
            optional_fixes.append("Sửa JSON-LD Article/FAQ ở cuối bài.")

    if not (featured_image_url or "").strip():
        optional_fixes.append("Nên có ảnh đại diện (featured image) trước khi publish.")

    if target == "haravan" and not (target_website or "").strip():
        optional_fixes.append("Haravan: xác nhận URL cửa hàng / token đã cấu hình trong Settings.")

    if total_score >= 75 and not blockers:
        pass  # đạt ngưỡng điểm — không thêm warning điểm số
    elif total_score >= 60:
        warnings.append(
            f"Điểm SEO {total_score}/100 (hạng {grade}) — nên tối ưu thêm (ngưỡng khuyến nghị ≥75)."
        )
    else:
        warnings.append(
            f"Điểm SEO thấp {total_score}/100 (hạng {grade}) — cảnh báo mạnh trước publish."
        )

    for item in score_data.get("missing_items") or []:
        s = str(item).strip()
        if s and s not in warnings and s not in blockers:
            optional_fixes.append(s[:200])

    dedupe_warnings = list(dict.fromkeys(warnings))[:25]
    dedupe_blockers = list(dict.fromkeys(blockers))[:15]
    dedupe_required = list(dict.fromkeys(required_fixes))[:15]
    dedupe_optional = list(dict.fromkeys(optional_fixes))[:20]
    dedupe_suggestions = list(dict.fromkeys(suggestions))[:20]

    if dedupe_blockers:
        severity = "blocker"
        can_publish = False
    elif total_score >= 75 and not dedupe_required and not dedupe_warnings:
        severity = "pass"
        can_publish = True
    else:
        severity = "warning"
        can_publish = False

    return {
        "can_publish": can_publish,
        "severity": severity,
        "total_score": total_score,
        "grade": grade,
        "blockers": dedupe_blockers,
        "warnings": dedupe_warnings,
        "suggestions": dedupe_suggestions,
        "required_fixes": dedupe_required,
        "optional_fixes": dedupe_optional,
        "publish_target": target,
        "detail_scores": details,
        "word_count": score_data.get("word_count"),
    }
