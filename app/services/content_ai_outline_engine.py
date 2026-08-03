"""
Outline engine for Content AI Single Writer: parse H2/H3, intent/article-type,
similarity guard, word budgets per section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.content_draft_builder import (
    classify_content_intent,
    content_ai_has_local_service_signal,
    detect_search_intent,
)

OUTLINE_SIMILARITY_THRESHOLD = 0.75
MIN_WORDS_PER_H2 = 70
MIN_WORDS_PER_H3 = 35


@dataclass
class OutlineSection:
    h2: str
    h3s: list[str] = field(default_factory=list)
    word_budget: int = 0
    raw_content: list[str] = field(default_factory=list)


def normalize_outline_heading(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"^h[1-6]\s*:?\s*", "", s, flags=re.I)
    return s.lower()


def extract_h1_from_outline(outline: str) -> str:
    for line in str(outline or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^#\s+(.+)$", s)
        if m:
            return m.group(1).strip()
        m2 = re.match(r"^H1\s*:\s*(.+)$", s, re.I)
        if m2:
            return m2.group(1).strip()
        m3 = re.match(r"^<h1[^>]*>(.+?)</h1>\s*$", s, re.I)
        if m3:
            return re.sub(r"<[^>]+>", "", m3.group(1)).strip()
    return ""


def parse_outline_sections(outline: str) -> list[OutlineSection]:
    """Chuẩn hóa outline thành danh sách H2 + H3 con."""
    sections: list[OutlineSection] = []
    current: OutlineSection | None = None

    def _flush() -> None:
        nonlocal current
        if current and current.h2.strip():
            sections.append(current)
        current = None

    for raw in str(outline or "").splitlines():
        line = raw.strip()
        if not line:
            if current is not None:
                current.raw_content.append("")
            continue
        h3_m = re.match(r"^(?:###\s+|H3\s*:\s*|<h3[^>]*>)(.+?)(?:</h3>)?\s*$", line, re.I)
        if h3_m:
            h3 = re.sub(r"<[^>]+>", "", h3_m.group(1)).strip()
            if h3:
                if current is None:
                    current = OutlineSection(h2="")
                current.h3s.append(h3)
                current.raw_content.append(line)
            continue
        h2_m = re.match(r"^(?:##\s+|H2\s*:\s*|<h2[^>]*>)(.+?)(?:</h2>)?\s*$", line, re.I)
        if h2_m:
            _flush()
            h2 = re.sub(r"<[^>]+>", "", h2_m.group(1)).strip()
            if h2:
                current = OutlineSection(h2=h2)
            continue
        if re.match(r"^#\s+", line) or re.match(r"^H1\s*:", line, re.I) or re.match(r"^<h1", line, re.I):
            continue
        if current is not None:
            current.raw_content.append(line)
    _flush()
    return [s for s in sections if s.h2.strip()]


def outline_h2_headings(outline: str) -> list[str]:
    return [s.h2 for s in parse_outline_sections(outline)]


def outline_heading_jaccard(a: str, b: str) -> float:
    """Jaccard similarity trên tập H2 (0..1)."""
    ha = {normalize_outline_heading(x) for x in outline_h2_headings(a) if x.strip()}
    hb = {normalize_outline_heading(x) for x in outline_h2_headings(b) if x.strip()}
    if not ha or not hb:
        return 0.0
    inter = len(ha & hb)
    union = len(ha | hb)
    return inter / union if union else 0.0


def classify_article_type(primary_keyword: str, *, knowledge: dict[str, Any] | None = None) -> str:
    """
    Loại bài cho outline: local_service | howto | comparison | buyer_guide |
    problem_solution | pillar | service
    """
    pk = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    intent = classify_content_intent(pk)
    canonical = detect_search_intent(pk)
    s = pk.lower()
    if content_ai_has_local_service_signal(pk):
        return "local_service"
    if intent == "howto" or any(x in s for x in ("cách ", "huong dan", "hướng dẫn", "là gì", "la gi")):
        return "howto"
    if any(x in s for x in ("so sánh", "so sanh", "vs ", " hay ", " tốt nhất", " tot nhat", "top ")):
        return "comparison"
    if any(x in s for x in ("nên mua", "nen mua", "nên chọn", "nen chon", "buyer", "mua gì", "mua gi")):
        return "buyer_guide"
    if any(x in s for x in ("lỗi", "loi", "sự cố", "su co", "khắc phục", "khac phuc", "triệu chứng", "trieu chung")):
        return "problem_solution"
    if any(x in s for x in ("toàn diện", "toan dien", "tổng hợp", "tong hop", "pillar", "hub")):
        return "pillar"
    if intent == "service" or canonical == "transactional":
        return "service"
    ot = str((knowledge or {}).get("outline_type") or "").strip()
    if ot == "local_service":
        return "local_service"
    if ot == "service":
        return "service"
    return "howto" if intent == "info" else "service"


_ARTICLE_TYPE_PATTERNS: dict[str, list[tuple[str, list[str]]]] = {
    "local_service": [
        ("A", ["{kw} tại {geo} — ai cần dịch vụ này?", "Triệu chứng/lỗi thường gặp khi {kw}", "Quy trình {kw} tại nhà", "Bảng giá và yếu tố ảnh hưởng chi phí {kw}", "Vì sao chọn {brand} cho {kw}?", "Khu vực phục vụ {geo}", "FAQ về {kw}", "Liên hệ đặt lịch {kw}"]),
        ("B", ["Nhu cầu {kw} ở {geo}", "Dịch vụ {kw} gồm những gì?", "Thời gian và quy trình xử lý", "Chi phí {kw} — minh bạch từng hạng mục", "Cam kết & bảo hành {brand}", "Câu hỏi thường gặp", "Gọi kỹ thuật {kw} ngay"]),
    ],
    "howto": [
        ("A", ["Chuẩn bị trước khi {kw}", "Các bước thực hiện {kw} chi tiết", "Lỗi hay gặp khi {kw}", "Mẹo tối ưu kết quả {kw}", "FAQ thực hành {kw}"]),
        ("B", ["{kw} là gì — tóm tắt nhanh", "Hướng dẫn {kw} từng bước", "Checklist {kw}", "Khi nào nên nhờ chuyên gia?", "Câu hỏi thường gặp về {kw}"]),
    ],
    "comparison": [
        ("A", ["Tiêu chí so sánh {kw}", "Phương án A vs B cho {kw}", "Bảng so sánh chi tiết {kw}", "Kết luận: nên chọn phương án nào?", "FAQ so sánh {kw}"]),
        ("B", ["Bối cảnh cần {kw}", "Ưu/nhược từng lựa chọn", "Ma trận quyết định {kw}", "Khuyến nghị theo nhu cầu", "FAQ {kw}"]),
    ],
    "buyer_guide": [
        ("A", ["Ai nên quan tâm {kw}?", "Checklist chọn {kw}", "Mức giá và ngân sách {kw}", "Red flags khi mua {kw}", "FAQ mua {kw}"]),
    ],
    "problem_solution": [
        ("A", ["Dấu hiệu cần {kw}", "Nguyên nhân gốc rễ", "Quy trình xử lý {kw}", "Phòng tránh tái phát", "FAQ sự cố {kw}"]),
    ],
    "pillar": [
        ("A", ["Tổng quan {kw}", "Thành phần/lĩnh vực con của {kw}", "Quy trình triển khai {kw}", "Case thực tế {kw}", "FAQ toàn diện {kw}", "Bước tiếp theo"]),
    ],
    "service": [
        ("A", ["{kw} phù hợp với ai?", "Hạng mục {kw} chi tiết", "Lợi ích khi dùng {kw}", "Quy trình {kw}", "Giá và báo giá {kw}", "Lý do chọn {brand}", "FAQ {kw}", "CTA liên hệ"]),
        ("B", ["Pain point khi cần {kw}", "Giải pháp {brand} cho {kw}", "Quy trình minh bạch", "Bảng giá tham khảo {kw}", "Cam kết dịch vụ", "FAQ & liên hệ"]),
    ],
}


def outline_structure_hint(
    article_type: str,
    *,
    primary_keyword: str,
    brand: str = "",
    variant: str = "A",
) -> str:
    """Gợi ý cấu trúc H2 — không copy y nguyên, heading phải gắn keyword."""
    pk = re.sub(r"\s+", " ", str(primary_keyword or "").strip()) or "dịch vụ"
    brand = str(brand or "đơn vị").strip() or "đơn vị"
    geo = ""
    from app.services.content_draft_builder import content_ai_extract_geo_tail

    geo = content_ai_extract_geo_tail(pk) or "khu vực"
    patterns = _ARTICLE_TYPE_PATTERNS.get(article_type) or _ARTICLE_TYPE_PATTERNS["service"]
    chosen = patterns[0]
    for tag, items in patterns:
        if tag == variant:
            chosen = (tag, items)
            break
    lines = [f"=== GỢI Ý CẤU TRÚC ({article_type}, variant {chosen[0]}) ==="]
    for item in chosen[1]:
        lines.append(f"- H2: {item.format(kw=pk, brand=brand, geo=geo)}")
        lines.append("  · 2–4 H3 cụ thể (không heading chung chung)")
    return "\n".join(lines)


def _headings_h2_in_html(html: str) -> set[str]:
    raw = str(html or "").strip()
    if not raw:
        return set()
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        return {
            normalize_outline_heading(tag.get_text(" ", strip=True))
            for tag in soup.find_all("h2")
            if normalize_outline_heading(tag.get_text(" ", strip=True))
        }
    except Exception:
        return set()


def outline_h2_coverage(outline: str, html: str) -> dict[str, Any]:
    """Đối chiếu HTML với danh sách H2 từ outline (chỉ so khớp thẻ <h2>)."""
    sections = parse_outline_sections(outline)
    expected = [normalize_outline_heading(s.h2) for s in sections if s.h2.strip()]
    if not expected:
        return {"total": 0, "covered": 0, "ratio": 1.0, "missing_headings": [], "missing_sections": []}
    found = _headings_h2_in_html(html)
    missing_raw: list[str] = []
    covered = 0
    for sec in sections:
        norm = normalize_outline_heading(sec.h2)
        matched = norm in found or any(
            norm == f or (len(norm) >= 12 and (norm in f or f in norm)) for f in found
        )
        if matched:
            covered += 1
        else:
            missing_raw.append(sec.h2)
    total = len(expected)
    ratio = covered / total if total else 1.0
    return {
        "total": total,
        "covered": covered,
        "ratio": ratio,
        "missing_headings": [normalize_outline_heading(x) for x in missing_raw],
        "missing_sections": missing_raw,
    }


def pick_outline_variant(article_type: str, *, avoid_variant: str = "") -> str:
    patterns = _ARTICLE_TYPE_PATTERNS.get(article_type) or _ARTICLE_TYPE_PATTERNS["service"]
    tags = [t for t, _ in patterns]
    for t in tags:
        if t != avoid_variant:
            return t
    return tags[0] if tags else "A"


def allocate_section_word_budgets(total_wc: int, sections: list[OutlineSection]) -> list[OutlineSection]:
    """Chia số từ theo section; intro/H1 ~12%, còn lại chia đều H2 (+ bonus H3)."""
    total = max(200, int(total_wc or 1000))
    n = len(sections)
    if n <= 0:
        return sections
    intro = max(80, int(total * 0.12))
    pool = max(total - intro, n * MIN_WORDS_PER_H2)
    weights = []
    for sec in sections:
        w = 1.0 + len(sec.h3s) * 0.35
        weights.append(w)
    wsum = sum(weights) or 1.0
    out: list[OutlineSection] = []
    for sec, w in zip(sections, weights):
        budget = max(MIN_WORDS_PER_H2, int(pool * w / wsum))
        if sec.h3s:
            budget = max(budget, len(sec.h3s) * MIN_WORDS_PER_H3 + 40)
        out.append(
            OutlineSection(
                h2=sec.h2,
                h3s=list(sec.h3s),
                word_budget=budget,
                raw_content=list(sec.raw_content),
            )
        )
    return out


def intro_word_budget(total_wc: int) -> int:
    return max(80, int(max(200, int(total_wc or 1000)) * 0.12))


def list_recent_outlines_for_user(
    user_id: int,
    *,
    target_website: str = "",
    limit: int = 8,
) -> list[str]:
    """Lấy outline gần đây của user (cùng website nếu có) để so similarity."""
    try:
        from app.services.content_ai_project_store import list_content_ai_projects
        from app.services.content_ai_knowledge_context import _norm_site
    except Exception:
        return []
    host = _norm_site(target_website)
    rows = list_content_ai_projects(user_id=int(user_id), limit=max(limit, 20))
    out: list[str] = []
    for row in rows:
        ol = str(row.get("outline_content") or "").strip()
        if not ol or len(ol) < 40:
            continue
        if host:
            rh = _norm_site(str(row.get("target_website") or ""))
            if rh and rh != host and host not in rh and rh not in host:
                continue
        out.append(ol)
        if len(out) >= limit:
            break
    return out


def outline_too_similar_to_recent(
    outline: str,
    recent: list[str],
    *,
    threshold: float = OUTLINE_SIMILARITY_THRESHOLD,
) -> tuple[bool, float, str]:
    """True nếu outline mới quá giống một outline gần đây."""
    best = 0.0
    for old in recent:
        sim = outline_heading_jaccard(outline, old)
        if sim > best:
            best = sim
    return best >= threshold, best, f"jaccard_h2={best:.2f}"


def build_outline_diversity_instruction(
    *,
    article_type: str,
    primary_keyword: str,
    brand: str = "",
    variant: str = "A",
    similarity_note: str = "",
) -> str:
    hint = outline_structure_hint(
        article_type,
        primary_keyword=primary_keyword,
        brand=brand,
        variant=variant,
    )
    extra = ""
    if similarity_note:
        extra = (
            f"\n- Outline TRƯỚC ĐÓ quá giống ({similarity_note}) — BẮT BUỘC đổi cấu trúc H2, "
            "thứ tự section và góc tiếp cận; heading phải chứa keyword/dịch vụ cụ thể.\n"
        )
    return (
        f"\n=== OUTLINE ENGINE (loại bài: {article_type}) ===\n"
        "- Mỗi H2 phải cụ thể theo PRIMARY_KEYWORD; KHÔNG dùng heading chung chung kiểu "
        "«Lợi ích», «Kết luận», «Giới thiệu» nếu không gắn keyword/dịch vụ.\n"
        "- Mỗi H2 có 2–5 H3; không copy y nguyên mẫu — diễn đạt tự nhiên theo SOURCE/KB.\n"
        "- Bám search intent và loại bài; không dùng một khung outline cố định cho mọi keyword.\n"
        + extra
        + hint
        + "\n"
    )
