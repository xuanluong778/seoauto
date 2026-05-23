"""
Content Gap — phân tích thiếu sót nội dung (read-only, không sửa HTML).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.content_ai_score import (
    _CTA_RE,
    _FAQ_HEADING_RE,
    _count_internal_external,
    _kw_in_text,
    _parse_html_safe,
    _word_count,
)

_KW_TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.I)
_GENERIC_H2_RE = re.compile(
    r"^(kết luận|tổng kết|kết thúc|tóm lại|mở đầu|giới thiệu|overview|summary)$",
    re.I,
)
_THIN_SECTION_WORDS = 55


def _normalize_heading(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    t = re.sub(r"^#+\s*", "", t)
    t = re.sub(r"[^\wà-ỹ\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_outline_headings(outline: str) -> list[str]:
    headings: list[str] = []
    for line in (outline or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            if level >= 2:
                headings.append(_normalize_heading(m.group(2)))
        elif re.match(r"^<h[2-6][^>]*>", line, re.I):
            text = re.sub(r"<[^>]+>", "", line).strip()
            if text:
                headings.append(_normalize_heading(text))
    return headings


def _section_word_counts(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Words per H2 section (until next H2)."""
    h2s = soup.find_all("h2")
    if not h2s:
        return []
    sections: list[dict[str, Any]] = []
    for i, h2 in enumerate(h2s):
        title = h2.get_text(" ", strip=True)
        words = 0
        for sib in h2.find_next_siblings():
            if sib.name == "h2":
                break
            if getattr(sib, "name", None) in {"script", "style"}:
                continue
            words += len(re.findall(r"[\wà-ỹ]+", sib.get_text(" ", strip=True), re.I))
        sections.append({"title": title, "words": words, "normalized": _normalize_heading(title)})
    return sections


def _url_in_html(url: str, html_lower: str, soup: BeautifulSoup) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    if u.lower() in html_lower:
        return True
    try:
        p = urlparse(u if "://" in u else f"https://{u}")
        path = (p.path or "").strip("/")
        if path and path.lower() in html_lower:
            return True
    except Exception:
        pass
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if href == u or u in href or href in u:
            return True
    return False


def _heading_covered(expected: str, article_headings: set[str], body_text: str) -> bool:
    exp = _normalize_heading(expected)
    if not exp or len(exp) < 3:
        return True
    if exp in article_headings:
        return True
    for ah in article_headings:
        if exp in ah or ah in exp:
            return True
        exp_tokens = set(_KW_TOKEN_RE.findall(exp))
        ah_tokens = set(_KW_TOKEN_RE.findall(ah))
        if exp_tokens and len(exp_tokens & ah_tokens) >= max(2, len(exp_tokens) * 0.6):
            return True
    if _kw_in_text(body_text, exp):
        return True
    return False


def evaluate_content_gap(
    *,
    title: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    html_content: str = "",
    target_word_count: int | None = None,
    content_brief: dict[str, Any] | None = None,
    competitor_outline: str = "",
    internal_links: list[dict[str, Any]] | None = None,
    target_website: str = "",
) -> dict[str, Any]:
    brief = content_brief if isinstance(content_brief, dict) else {}
    raw_html = str(html_content or "").strip()

    missing_sections: list[str] = []
    missing_entities: list[str] = []
    missing_faq: list[str] = []
    missing_internal_links: list[str] = []
    missing_cta: list[str] = []
    thin_sections: list[str] = []
    generic_sections: list[str] = []
    improvement_suggestions: list[str] = []
    suggested_outline_additions: list[str] = []
    suggested_content_blocks: list[str] = []

    if not raw_html:
        return {
            "gap_score": 12,
            "severity": "poor",
            "missing_sections": ["Toàn bộ nội dung HTML — chưa có bài viết."],
            "missing_entities": [],
            "missing_faq": ["Section FAQ chưa có."],
            "missing_internal_links": [],
            "missing_cta": ["Chưa có CTA / lời kêu gọi hành động."],
            "thin_sections": [],
            "generic_sections": [],
            "improvement_suggestions": [
                "Viết hoặc dán nội dung vào editor trước khi phân tích gap.",
            ],
            "suggested_outline_additions": [],
            "suggested_content_blocks": ["Đoạn mở bài + H1 + ít nhất 4 mục H2."],
            "word_count": 0,
            "analysis_mode": "rule_based",
        }

    soup = _parse_html_safe(raw_html)
    body_text = soup.get_text(" ", strip=True)
    html_lower = raw_html.lower()
    word_n = _word_count(BeautifulSoup(str(soup), "html.parser"))

    h2_nodes = soup.find_all("h2")
    article_h2_set = {_normalize_heading(h.get_text(" ", strip=True)) for h in h2_nodes}
    section_stats = _section_word_counts(soup)

    target = 1000
    if target_word_count is not None:
        try:
            target = max(200, min(int(target_word_count), 20000))
        except (TypeError, ValueError):
            target = 1000
    brief_wc = brief.get("recommended_word_count")
    if brief_wc:
        try:
            target = max(target, int(brief_wc))
        except (TypeError, ValueError):
            pass

    # --- Brief comparison ---
    brief_outline = str(brief.get("outline") or "")
    if brief_outline:
        for h in _parse_outline_headings(brief_outline):
            if h.startswith("tham khảo") or "đối thủ" in h:
                continue
            if not _heading_covered(h, article_h2_set, body_text):
                missing_sections.append(f"Mục outline Brief chưa có trong bài: «{h}».")
                suggested_outline_additions.append(f"## {h.title() if h.islower() else h}")

    for ent in brief.get("required_entities") or []:
        e = str(ent).strip()
        if len(e) < 3:
            continue
        if not _kw_in_text(body_text, e):
            missing_entities.append(e)

    for q in brief.get("faq_questions") or []:
        qs = str(q).strip()
        if len(qs) < 8:
            continue
        if not _kw_in_text(body_text, qs):
            missing_faq.append(qs)

    for row in brief.get("internal_link_plan") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if url and not _url_in_html(url, html_lower, soup):
            anchor = str(row.get("anchor_suggestion") or "").strip()
            missing_internal_links.append(
                f"{anchor + ' → ' if anchor else ''}{url}"
            )

    # --- Competitor outline (optional) ---
    comp_outline = str(competitor_outline or "").strip()
    if comp_outline:
        try:
            comp_heads = _parse_outline_headings(comp_outline)
            for h in comp_heads[:12]:
                if len(h) < 4 or "tham khảo" in h:
                    continue
                if not _heading_covered(h, article_h2_set, body_text):
                    label = f"Đối thủ có mục «{h}» — bài chưa cover."
                    if label not in missing_sections:
                        missing_sections.append(label)
                    add = f"## {h.title() if h.islower() else h} (tham khảo SERP)"
                    if add not in suggested_outline_additions:
                        suggested_outline_additions.append(add)
        except Exception:
            pass

    # --- Rule-based structure ---
    if not soup.find("h1"):
        missing_sections.append("Thiếu thẻ H1.")
    if len(h2_nodes) < 2:
        missing_sections.append("Cần ít nhất 2 mục H2.")
    has_faq_section = any(
        _FAQ_HEADING_RE.search(h.get_text(" ", strip=True)) for h in h2_nodes
    )
    if not has_faq_section and not missing_faq:
        missing_faq.append("Chưa có section FAQ (H2 Câu hỏi thường gặp).")

    for sec in section_stats:
        if sec["words"] < _THIN_SECTION_WORDS:
            thin_sections.append(f"«{sec['title']}» (~{sec['words']} từ — nên ≥{_THIN_SECTION_WORDS}).")
        if _GENERIC_H2_RE.match(_normalize_heading(sec["title"])):
            generic_sections.append(f"«{sec['title']}» — tiêu đề chung chung, nên cụ thể hơn.")

    internal_n, _, _ = _count_internal_external(soup, target_website)
    planned_urls: list[str] = []
    for row in internal_links or []:
        if isinstance(row, dict):
            u = str(row.get("url") or row.get("link") or "").strip()
            if u:
                planned_urls.append(u)
    for row in brief.get("internal_link_plan") or []:
        if isinstance(row, dict):
            u = str(row.get("url") or "").strip()
            if u and u not in planned_urls:
                planned_urls.append(u)

    if internal_n < 1 and planned_urls:
        for u in planned_urls[:4]:
            if not _url_in_html(u, html_lower, soup):
                if u not in [x.split("→")[-1].strip() for x in missing_internal_links]:
                    missing_internal_links.append(u)
    elif internal_n < 2:
        improvement_suggestions.append("Thêm 2–4 internal link ngữ cảnh (không gom cuối bài).")

    tail = body_text[-1500:].lower() if len(body_text) > 1500 else body_text.lower()
    if not _CTA_RE.search(tail) and not _CTA_RE.search(body_text):
        missing_cta.append("Chưa có CTA rõ (liên hệ, báo giá, đăng ký, hotline…).")
    elif not _CTA_RE.search(tail):
        missing_cta.append("Có CTA nhưng chưa đặt rõ ở đoạn kết bài.")

    pk = (primary_keyword or "").strip()
    if pk and not _kw_in_text(body_text, pk):
        missing_entities.append(pk)
    for part in re.split(r"[,;|\n]+", secondary_keywords or ""):
        ph = part.strip()
        if len(ph) >= 4 and not _kw_in_text(body_text, ph):
            missing_entities.append(ph)

    if word_n < int(target * 0.55):
        improvement_suggestions.append(
            f"Độ dài ~{word_n} từ — thấp hơn mục tiêu ~{target} từ."
        )
    if not soup.find_all(["ul", "ol"]):
        suggested_content_blocks.append("Danh sách checklist / bullet (ul/ol).")
    if not soup.find("table"):
        suggested_content_blocks.append("Bảng so sánh hoặc tóm tắt (table).")
    if "ví dụ" not in body_text.lower() and "case" not in body_text.lower():
        suggested_content_blocks.append("Ít nhất 1 block «Ví dụ thực tế» dưới H2 chính.")
    if not re.search(r"(bước\s*\d|quy trình|lộ trình)", body_text, re.I):
        suggested_content_blocks.append("Quy trình từng bước (numbered list).")

    # Dedupe
    def _dedupe(lst: list[str], cap: int = 20) -> list[str]:
        return list(dict.fromkeys(lst))[:cap]

    missing_sections = _dedupe(missing_sections)
    missing_entities = _dedupe(missing_entities)
    missing_faq = _dedupe(missing_faq)
    missing_internal_links = _dedupe(missing_internal_links)
    missing_cta = _dedupe(missing_cta)
    thin_sections = _dedupe(thin_sections)
    generic_sections = _dedupe(generic_sections)
    suggested_outline_additions = _dedupe(suggested_outline_additions, 12)
    suggested_content_blocks = _dedupe(suggested_content_blocks, 10)

    # gap_score: 100 minus penalties
    score = 100
    score -= min(35, len(missing_sections) * 8)
    score -= min(25, len(missing_entities) * 5)
    score -= min(15, len(missing_faq) * 6)
    score -= min(20, len(missing_internal_links) * 7)
    score -= min(15, len(missing_cta) * 10)
    score -= min(20, len(thin_sections) * 4)
    score -= min(10, len(generic_sections) * 3)
    if word_n < 200:
        score -= 25
    elif word_n < target * 0.6:
        score -= 12
    gap_score = max(0, min(100, int(score)))

    if gap_score >= 75:
        severity = "good"
    elif gap_score >= 50:
        severity = "warning"
    else:
        severity = "poor"

    if not improvement_suggestions:
        if severity == "good":
            improvement_suggestions.append("Coverage tốt — có thể tinh chỉnh EEAT/số liệu nếu cần.")
        else:
            improvement_suggestions.append("Ưu tiên bổ sung section/entity/FAQ còn thiếu trước khi publish.")

    if missing_sections and "Bổ sung các mục H2" not in improvement_suggestions:
        improvement_suggestions.insert(0, "Bổ sung các mục H2/outline còn thiếu so với Brief/đối thủ.")
    if missing_entities:
        improvement_suggestions.append("Rải entity/từ khóa phụ tự nhiên trong 2–3 section giữa bài.")
    if missing_faq:
        improvement_suggestions.append("Thêm H2 FAQ với 3–5 câu hỏi trả lời ngắn gọn.")
    if missing_cta:
        improvement_suggestions.append("Kết bài bằng đoạn CTA rõ (liên hệ / báo giá).")

    improvement_suggestions = _dedupe(improvement_suggestions, 15)

    return {
        "gap_score": gap_score,
        "severity": severity,
        "missing_sections": missing_sections,
        "missing_entities": missing_entities,
        "missing_faq": missing_faq,
        "missing_internal_links": missing_internal_links,
        "missing_cta": missing_cta,
        "thin_sections": thin_sections,
        "generic_sections": generic_sections,
        "improvement_suggestions": improvement_suggestions,
        "suggested_outline_additions": suggested_outline_additions,
        "suggested_content_blocks": suggested_content_blocks,
        "word_count": word_n,
        "analysis_mode": "rule_based",
        "brief_used": bool(brief_outline or brief.get("required_entities")),
    }
