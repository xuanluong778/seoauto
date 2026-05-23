"""
SEO Content Brief cho Content AI — rule-based (LLM optional, chưa bật mặc định).
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.services.content_ai_knowledge_context import (
    _classify_outline_type,
    build_outline_context_from_knowledge,
    get_relevant_knowledge_for_keyword,
)
from app.services.content_draft_builder import detect_search_intent

_INTENT_LABELS = {
    "transactional": "Giao dịch / đặt dịch vụ",
    "commercial investigation": "So sánh / tìm hiểu trước mua",
    "informational": "Tìm hiểu / hướng dẫn",
    "navigational": "Điều hướng thương hiệu",
}

_CONTENT_TYPE_MAP = {
    "local_service": "Landing dịch vụ địa phương",
    "service": "Bài dịch vụ / giải pháp",
    "general": "Bài blog chuyên sâu",
    "comparison": "Bài so sánh / review",
    "guide": "Hướng dẫn từng bước",
}


def _split_secondary(raw: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[,;|\n]+", raw or ""):
        p = part.strip()
        if len(p) >= 2 and p not in out:
            out.append(p)
    return out[:20]


def _try_competitor_outline(competitor_url: str) -> tuple[list[str], str | None]:
    raw = (competitor_url or "").strip()
    if not raw:
        return [], None
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return [], "Link đối thủ không hợp lệ."
        url = parsed.geturl()
        resp = requests.get(
            url,
            timeout=14,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
                )
            },
        )
        if resp.status_code >= 400:
            return [], f"Đối thủ HTTP {resp.status_code}."
        enc = (resp.encoding or "").strip().lower()
        if (not enc) or enc in {"iso-8859-1", "latin-1"}:
            try:
                resp.encoding = resp.apparent_encoding or "utf-8"
            except Exception:
                resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text or "", "html.parser")
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        headings: list[str] = []
        for node in soup.select("h1, h2, h3"):
            level = (node.name or "").lower()
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if not text:
                continue
            prefix = {"h1": "#", "h2": "##", "h3": "###"}.get(level, "##")
            line = f"{prefix} {text}"
            if line not in headings:
                headings.append(line)
        if not headings:
            return [], "Không trích xuất được heading từ URL đối thủ."
        return headings[:20], None
    except Exception as exc:
        return [], f"Không crawl được đối thủ: {str(exc)[:120]}"


def _infer_content_type(keyword: str, explicit: str, knowledge: dict[str, Any]) -> str:
    exp = (explicit or "").strip().lower()
    if exp:
        for key, label in _CONTENT_TYPE_MAP.items():
            if key in exp or label.lower() in exp:
                return label
        return explicit.strip()
    ot = str(knowledge.get("outline_type") or _classify_outline_type(keyword))
    intent = detect_search_intent(keyword)
    if intent == "commercial investigation":
        return _CONTENT_TYPE_MAP["comparison"]
    if ot == "local_service":
        return _CONTENT_TYPE_MAP["local_service"]
    if ot == "service":
        return _CONTENT_TYPE_MAP["service"]
    if intent == "informational":
        return _CONTENT_TYPE_MAP["guide"]
    return _CONTENT_TYPE_MAP["general"]


def _target_audience(keyword: str, knowledge: dict[str, Any]) -> str:
    aud = ""
    if knowledge.get("found"):
        sec = (knowledge.get("sections") or {}).get("audience") or ""
        aud = str(sec).strip()[:400]
    if aud:
        return aud
    intent = detect_search_intent(keyword)
    if intent == "transactional":
        return "Khách hàng đang tìm dịch vụ/giải pháp cụ thể, cần thông tin rõ giá, quy trình, uy tín."
    if intent == "commercial investigation":
        return "Người dùng so sánh lựa chọn trước khi quyết định mua/đăng ký."
    return "Độc giả cần hiểu chủ đề, giải pháp và bước hành động tiếp theo."


def _content_goal(intent: str, content_type: str) -> str:
    if intent == "transactional":
        return "Chuyển đổi lead: làm rõ dịch vụ, lợi ích, quy trình, CTA liên hệ/đặt lịch."
    if intent == "commercial investigation":
        return "Hỗ trợ quyết định: so sánh, tiêu chí chọn, ưu/nhược, gợi ý bước tiếp theo."
    if "hướng dẫn" in content_type.lower():
        return "Giáo dục từng bước, tăng trust và thời gian trên trang."
    return "Trả lời đúng search intent, tăng topical authority và internal link."


def _angle(keyword: str, brand: str, intent: str) -> str:
    b = brand or "thương hiệu"
    if intent == "transactional":
        return f"Góc «{b}» — dịch vụ thực chiến cho «{keyword}», nhấn quy trình + case thực tế (không bịa số liệu)."
    if intent == "commercial investigation":
        return f"So sánh khách quan + lý do chọn {b} khi phù hợp nhu cầu «{keyword}»."
    return f"Chuyên sâu, hữ ích (Helpful Content) quanh «{keyword}», có ví dụ và FAQ."


def _suggested_title(keyword: str, title: str, brand: str) -> str:
    if (title or "").strip():
        return title.strip()[:70]
    b = f" | {brand}" if brand else ""
    pk = keyword.strip()
    intent = detect_search_intent(pk)
    if intent == "transactional":
        return f"{pk.title()} — Dịch vụ uy tín, báo giá minh bạch{b}"[:70]
    return f"{pk.title()} — Hướng dẫn chi tiết & FAQ 2025{b}"[:70]


def _suggested_meta(keyword: str, meta: str, brand: str) -> str:
    if (meta or "").strip() and len(meta.strip()) >= 80:
        return meta.strip()[:165]
    pk = keyword.strip()
    b = brand or "chúng tôi"
    base = (
        f"Tìm hiểu {pk} với {b}: quy trình rõ, lợi ích cụ thể, FAQ và liên hệ nhanh. "
        "Nội dung chuẩn SEO, không bịa giá — nhận tư vấn miễn phí."
    )
    return base[:165]


def _build_outline(
    *,
    keyword: str,
    existing_outline: str,
    knowledge: dict[str, Any],
    competitor_headings: list[str],
) -> str:
    if (existing_outline or "").strip():
        return existing_outline.strip()
    lines: list[str] = []
    h1 = keyword.strip().title() or "Bài viết"
    lines.append(f"# {h1}")
    if knowledge.get("found"):
        for h2 in knowledge.get("required_outline_h2") or []:
            lines.append(f"## {h2}")
            lines.append("### Chi tiết triển khai")
            lines.append("### Lưu ý thực tế")
    else:
        intent = detect_search_intent(keyword)
        blocks = [
            ("## Giới thiệu & bối cảnh", ["### Vấn đề người đọc gặp", "### Mục tiêu bài viết"]),
            ("## Giải pháp / nội dung chính", ["### Bước 1", "### Bước 2", "### Bước 3"]),
            ("## Lợi ích & tiêu chí lựa chọn", ["### So sánh nhanh", "### Checklist"]),
            ("## Câu hỏi thường gặp (FAQ)", ["### 3–5 câu hỏi"]),
            ("## Liên hệ / CTA", ["### Cách liên hệ"]),
        ]
        if intent == "transactional":
            blocks.insert(2, ("## Quy trình & báo giá", ["### Các bước", "### Yếu tố ảnh hưởng chi phí"]))
        for h2, h3s in blocks:
            lines.append(h2)
            lines.extend(h3s)
    if competitor_headings:
        lines.append("")
        lines.append("## (Tham khảo cấu trúc đối thủ — không copy y nguyên)")
        for h in competitor_headings[:14]:
            lines.append(h)
    return "\n".join(lines).strip()


def _required_entities(
    keyword: str,
    secondary: list[str],
    knowledge: dict[str, Any],
    tags: str,
) -> list[str]:
    entities: list[str] = [keyword.strip()] if keyword.strip() else []
    entities.extend(secondary[:8])
    if knowledge.get("found"):
        entities.extend((knowledge.get("semantic_keywords") or [])[:10])
    for t in re.split(r"[,;]+", tags or ""):
        t = t.strip()
        if t and t not in entities:
            entities.append(t)
    sec = (knowledge.get("sections") or {}) if knowledge.get("found") else {}
    for key in ("services", "brand_profile", "process"):
        blob = str(sec.get(key) or "")
        for m in re.findall(r"[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[a-zà-ỹ]+){0,3}", blob):
            if len(m) > 4 and m.lower() not in {e.lower() for e in entities}:
                entities.append(m)
                if len(entities) >= 18:
                    break
    return entities[:18]


def _faq_questions(keyword: str, knowledge: dict[str, Any]) -> list[str]:
    items: list[str] = []
    if knowledge.get("found"):
        for faq in knowledge.get("faq_items") or []:
            q = str(faq.get("question") or "").strip()
            if q:
                items.append(q)
    templates = [
        f"{keyword} là gì và ai nên quan tâm?",
        f"Chi phí / báo giá {keyword} phụ thuộc yếu tố nào?",
        f"Quy trình {keyword} gồm những bước nào?",
        f"Mất bao lâu để hoàn thành {keyword}?",
        f"Làm sao chọn đơn vị uy tín cho {keyword}?",
    ]
    for t in templates:
        if t not in items:
            items.append(t)
        if len(items) >= 8:
            break
    return items[:8]


def _internal_link_plan(candidates: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    for i, row in enumerate(candidates or []):
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("link") or "").strip()
        if not url or not url.startswith(("http://", "https://", "/")):
            continue
        anchor = str(
            row.get("anchor_text")
            or row.get("suggested_anchor")
            or row.get("title")
            or ""
        ).strip()[:120]
        title = str(row.get("title") or "").strip()
        plan.append(
            {
                "url": url,
                "anchor_suggestion": anchor or title or "anchor tự nhiên",
                "placement_hint": f"Sau H2 mục {i + 2} (tránh FAQ & đoạn mở đầu)",
                "priority": str(i + 1),
                "source": "internal_link_candidates",
            }
        )
        if len(plan) >= 6:
            break
    return plan


def _external_sources(keyword: str) -> list[str]:
    pk = keyword.strip()
    return [
        f"Wikipedia / tài liệu chuẩn về chủ đề liên quan «{pk}» (không bịa URL).",
        "Trang .gov / .edu hoặc tổ chức uy tín trong ngành (nếu có).",
        "Trang help chính thức của nền tảng/công cụ được nhắc trong bài.",
    ]


def brief_to_llm_context(brief: dict[str, Any], *, max_chars: int = 6000) -> str:
    """Chuỗi CONTENT_BRIEF cho prompt LLM."""
    if not brief:
        return ""
    parts = [
        f"SEARCH_INTENT: {brief.get('search_intent') or ''}",
        f"CONTENT_TYPE: {brief.get('content_type') or ''}",
        f"TARGET_AUDIENCE: {brief.get('target_audience') or ''}",
        f"CONTENT_GOAL: {brief.get('content_goal') or ''}",
        f"ANGLE: {brief.get('angle') or ''}",
        f"RECOMMENDED_WORD_COUNT: {brief.get('recommended_word_count') or ''}",
        f"SUGGESTED_TITLE: {brief.get('suggested_title') or ''}",
        f"SUGGESTED_META: {brief.get('suggested_meta_description') or ''}",
    ]
    if brief.get("outline"):
        parts.append("OUTLINE_FROM_BRIEF:\n" + str(brief["outline"])[:3500])
    if brief.get("required_entities"):
        parts.append("ENTITIES: " + ", ".join(brief["required_entities"][:15]))
    if brief.get("faq_questions"):
        parts.append("FAQ_TO_COVER:\n- " + "\n- ".join(brief["faq_questions"][:6]))
    if brief.get("internal_link_plan"):
        lines = []
        for row in brief["internal_link_plan"][:5]:
            if isinstance(row, dict) and row.get("url"):
                lines.append(f"{row.get('anchor_suggestion','')} → {row['url']}")
        if lines:
            parts.append("INTERNAL_LINK_PLAN (chỉ URL đã liệt kê):\n" + "\n".join(lines))
    if brief.get("eeat_suggestions"):
        parts.append("EEAT:\n- " + "\n- ".join(brief["eeat_suggestions"][:6]))
    if brief.get("cta_suggestions"):
        parts.append("CTA:\n- " + "\n- ".join(brief["cta_suggestions"][:4]))
    if brief.get("writing_notes"):
        parts.append("WRITING_NOTES:\n" + str(brief["writing_notes"])[:1200])
    blob = "\n".join(parts).strip()
    return blob[:max_chars] if len(blob) > max_chars else blob


def generate_content_brief(
    *,
    primary_keyword: str = "",
    secondary_keywords: str = "",
    title: str = "",
    target_website: str = "",
    target_word_count: int | None = None,
    competitor_url: str = "",
    brand_name: str = "",
    content_type: str = "",
    category: str = "",
    tags: str = "",
    existing_outline: str = "",
    internal_link_candidates: list[dict[str, Any]] | None = None,
    user_id: int | None = None,
    use_llm_enhancement: bool = False,
) -> dict[str, Any]:
    _ = use_llm_enhancement
    pk = re.sub(r"\s+", " ", (primary_keyword or "").strip())
    if not pk:
        raise ValueError("Thiếu từ khóa chính (primary_keyword).")

    twc = 1000
    if target_word_count is not None:
        try:
            twc = max(200, min(int(target_word_count), 20000))
        except (TypeError, ValueError):
            twc = 1000

    knowledge = get_relevant_knowledge_for_keyword(
        pk, target_website=target_website, user_id=user_id
    )
    brand = (brand_name or "").strip() or str(knowledge.get("brand_name") or "").strip()
    intent_raw = detect_search_intent(pk)
    intent_label = _INTENT_LABELS.get(intent_raw, intent_raw)
    ctype = _infer_content_type(pk, content_type, knowledge)
    secondary = _split_secondary(secondary_keywords)
    cat = (category or tags or "").strip()

    comp_lines, comp_warn = _try_competitor_outline(competitor_url)
    outline = _build_outline(
        keyword=pk,
        existing_outline=existing_outline,
        knowledge=knowledge,
        competitor_headings=comp_lines,
    )
    link_plan = _internal_link_plan(internal_link_candidates)
    faq = _faq_questions(pk, knowledge)
    entities = _required_entities(pk, secondary, knowledge, tags)

    warnings: list[str] = []
    if not knowledge.get("found"):
        warnings.append("Chưa khớp Knowledge Base — brief dùng mẫu mặc định.")
    if comp_warn:
        warnings.append(comp_warn)
    if not link_plan:
        warnings.append("Chưa có internal_link_candidates — kế hoạch link trống.")
    if not brand:
        warnings.append("Chưa có brand_name — CTA/angle dùng mô tả chung.")

    eeat: list[str] = [
        "Mở bài nêu pain point cụ thể của độc giả.",
        "Có quy trình từng bước hoặc checklist thực hành.",
        "Dùng ví dụ minh họa; số liệu chỉ khi có nguồn/KB.",
    ]
    if knowledge.get("found"):
        trust = str((knowledge.get("sections") or {}).get("trust_factors") or "")[:200]
        if trust:
            eeat.append(f"Trust (KB): {trust}")
    pricing_rule = str(knowledge.get("content_rules") or "")[:180]
    if pricing_rule:
        eeat.append("Tuân thủ quy tắc KB: không bịa giá/cam kết.")

    cta_suggestions: list[str] = []
    kb_cta = str(knowledge.get("cta") or "").strip()
    if kb_cta:
        cta_suggestions.append(kb_cta)
    cta_suggestions.extend(
        [
            "Đoạn kết: liên hệ / hotline / Zalo để nhận tư vấn.",
            "CTA nhẹ trong meta description.",
        ]
    )

    writing_notes_parts: list[str] = [
        f"Intent: {intent_label}. Loại bài: {ctype}.",
        f"Mục tiêu ~{twc} từ (±15%).",
    ]
    if cat:
        writing_notes_parts.append(f"Category/tags: {cat[:120]}")
    kb_ctx = build_outline_context_from_knowledge(knowledge, max_chars=2000)
    if kb_ctx:
        writing_notes_parts.append("Knowledge Base:\n" + kb_ctx)
    if comp_lines:
        writing_notes_parts.append("Đã tham khảo heading đối thủ — viết lại theo giọng thương hiệu.")

    return {
        "search_intent": intent_label,
        "search_intent_raw": intent_raw,
        "content_type": ctype,
        "target_audience": _target_audience(pk, knowledge),
        "content_goal": _content_goal(intent_raw, ctype),
        "angle": _angle(pk, brand, intent_raw),
        "recommended_word_count": twc,
        "suggested_title": _suggested_title(pk, title, brand),
        "suggested_meta_description": _suggested_meta(pk, "", brand),
        "outline": outline,
        "required_entities": entities,
        "faq_questions": faq,
        "internal_link_plan": link_plan,
        "external_source_suggestions": _external_sources(pk),
        "eeat_suggestions": eeat[:8],
        "cta_suggestions": list(dict.fromkeys(cta_suggestions))[:6],
        "writing_notes": "\n\n".join(writing_notes_parts).strip(),
        "warnings": warnings,
        "brief_mode": "rule_based",
        "knowledge_used": bool(knowledge.get("found")),
        "competitor_headings_used": len(comp_lines),
    }
