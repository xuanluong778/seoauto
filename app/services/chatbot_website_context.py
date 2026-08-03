"""Website context for Chatbot Viết bài SEO — crawl, ngành, kiểm tra lệch nội dung."""

from __future__ import annotations

import re
from typing import Any

AMBIGUOUS_KEYWORD_PREFIX = "AMBIGUOUS_KEYWORD:"

INDUSTRY_VERTICALS: dict[str, str] = {
    "seo_entity": "SEO / Entity / Marketing",
    "it_repair": "Sửa máy tính / IT",
    "web_design": "Thiết kế web / Phần mềm",
    "healthcare": "Y tế / Sức khỏe",
    "education": "Giáo dục / Đào tạo",
    "real_estate": "Bất động sản",
    "legal": "Pháp lý / Tư vấn",
    "other": "Khác",
}

_INDUSTRY_SIGNATURE: dict[str, list[str]] = {
    "seo_entity": [
        "entity",
        "seo",
        "google",
        "knowledge graph",
        "schema",
        "e-e-a-t",
        "topical authority",
        "search engine",
    ],
    "it_repair": [
        "sửa máy tính",
        "laptop",
        "pc",
        "cứu dữ liệu",
        "format máy",
        "máy tính",
        "kỹ thuật viên",
    ],
    "web_design": ["thiết kế web", "website", "wordpress", "landing page", "ui/ux"],
    "healthcare": ["bệnh viện", "phòng khám", "sức khỏe", "bác sĩ", "y tế"],
    "education": ["đào tạo", "khóa học", "giảng viên", "học viên", "giáo dục"],
    "real_estate": ["bất động sản", "căn hộ", "nhà đất", "môi giới"],
    "legal": ["luật sư", "pháp lý", "tư vấn pháp", "hợp đồng"],
}

_INDUSTRY_WRONG_TERMS: dict[str, list[str]] = {
    "seo_entity": [
        "sửa máy tính",
        "sửa laptop",
        "cứu dữ liệu",
        "format máy",
        "thay màn hình laptop",
        "vệ sinh máy tính",
    ],
    "it_repair": ["entity seo", "knowledge graph", "schema markup entity", "topical map seo"],
    "web_design": ["sửa máy tính", "phòng khám", "bất động sản"],
}


def normalize_website_url(raw: str | None) -> str:
    url = str(raw or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    return url[:500]


def resolve_website_url(params: dict[str, Any] | None) -> str:
    p = dict(params or {})
    return normalize_website_url(p.get("website_url") or p.get("target_website"))


def is_ambiguous_keyword(keyword: str) -> bool:
    kw = re.sub(r"\s+", " ", str(keyword or "").strip().lower())
    if len(kw) < 3:
        return True
    ambiguous_fragments = (
        "entity",
        "dịch vụ",
        "dich vu",
        "giải pháp",
        "giai phap",
        "solution",
        "service",
        "consulting",
        "tư vấn",
        "tu van",
    )
    if any(frag in kw for frag in ambiguous_fragments) and len(kw.split()) <= 4:
        return True
    if re.match(r"^(dịch vụ|dich vu|service)\s+\w+$", kw):
        return True
    return False


def _score_industry(text_l: str) -> tuple[str, list[str]]:
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for key, terms in _INDUSTRY_SIGNATURE.items():
        found = [t for t in terms if t in text_l]
        scores[key] = len(found)
        hits[key] = found
    if not scores or max(scores.values()) <= 0:
        return "general", []
    best = max(scores, key=lambda k: scores[k])
    return best, hits.get(best, [])[:8]


def fetch_website_profile(url: str) -> dict[str, Any]:
    from app.services.llm_content_writer import _fetch_source_text

    final_url, text = _fetch_source_text(url)
    text = re.sub(r"\n{2,}", "\n", str(text or "")).strip()
    text_l = text.lower()
    industry_key, signature_terms = _score_industry(text_l)
    title_line = ""
    for line in text.split("\n")[:12]:
        line = line.strip()
        if len(line) >= 8:
            title_line = line[:200]
            break
    region = ""
    for m in re.finditer(r"(quận|huyện|tp\.?\s*hồ chí minh|hà nội|đà nẵng|bình dương)\s*[\w\s]{0,20}", text_l):
        region = m.group(0).strip()[:80]
        break
    services = ", ".join(signature_terms[:6]) if signature_terms else title_line[:120]
    return {
        "url": final_url or url,
        "title": title_line,
        "industry_key": industry_key,
        "industry_label": INDUSTRY_VERTICALS.get(industry_key, industry_key),
        "services": services,
        "region": region,
        "signature_terms": signature_terms,
        "summary": text[:2500],
        "text": text[:12000],
    }


def build_vertical_context(vertical: str) -> dict[str, Any]:
    key = str(vertical or "").strip().lower()
    label = INDUSTRY_VERTICALS.get(key, vertical or "Khác")
    terms = _INDUSTRY_SIGNATURE.get(key, [])
    return {
        "url": "",
        "title": label,
        "industry_key": key or "other",
        "industry_label": label,
        "services": ", ".join(terms[:6]),
        "region": "",
        "signature_terms": terms,
        "summary": f"Ngành đã chọn: {label}.",
        "text": "",
        "source": "business_vertical",
    }


def format_website_context_block(ctx: dict[str, Any] | None) -> str:
    if not ctx:
        return ""
    parts = [
        f"NGÀNH/DỊCH VỤ: {ctx.get('industry_label') or ctx.get('industry_key') or ''}",
        f"DỊCH VỤ CHÍNH: {ctx.get('services') or ''}",
    ]
    if ctx.get("region"):
        parts.append(f"KHU VỰC: {ctx.get('region')}")
    if ctx.get("url"):
        parts.append(f"WEBSITE: {ctx.get('url')}")
    if ctx.get("summary"):
        parts.append("TÓM TẮT WEBSITE:\n" + str(ctx.get("summary") or "")[:1800])
    return "\n".join(p for p in parts if p.strip())


def prepare_write_params_with_website_context(params: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hóa params + crawl website / kiểm tra từ khóa mơ hồ."""
    out = dict(params or {})
    pk = str(out.get("primary_keyword") or out.get("keyword") or "").strip()
    website_url = resolve_website_url(out)
    vertical = str(out.get("business_vertical") or "").strip().lower()

    ambiguous = is_ambiguous_keyword(pk)
    out["keyword_ambiguous"] = ambiguous

    if ambiguous and not website_url and not vertical:
        raise ValueError(
            f"{AMBIGUOUS_KEYWORD_PREFIX} Từ khóa quá mơ hồ. "
            "Vui lòng nhập Website/URL dịch vụ hoặc chọn ngành kinh doanh trước khi tạo outline."
        )

    website_context: dict[str, Any] | None = None
    if website_url:
        out["website_url"] = website_url
        out["target_website"] = website_url
        website_context = fetch_website_profile(website_url)
        if not str(website_context.get("text") or "").strip():
            raise ValueError("Không đọc được nội dung website. Kiểm tra URL và thử lại.")
        out["website_context"] = website_context
    elif vertical:
        website_context = build_vertical_context(vertical)
        out["website_context"] = website_context

    if website_context and ambiguous:
        sig = website_context.get("signature_terms") or []
        out["resolved_industry"] = website_context.get("industry_key")
        out["planning_guard"] = (
            "Từ khóa mơ hồ — bắt buộc bám ngành/dịch vụ từ website hoặc ngành đã chọn. "
            f"Ngành xác định: {website_context.get('industry_label')}. "
            f"Dấu hiệu: {', '.join(sig[:5]) if sig else website_context.get('services', '')}."
        )

    return out


def validate_content_alignment(
    content_html: str,
    *,
    website_context: dict[str, Any] | None,
    primary_keyword: str,
) -> tuple[bool, str | None]:
    if not website_context:
        return True, None
    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(str(content_html or ""), "html.parser").get_text(" ", strip=True).lower()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", str(content_html or "")).lower()
    industry_key = str(website_context.get("industry_key") or "general")
    wrong = _INDUSTRY_WRONG_TERMS.get(industry_key, [])
    for term in wrong:
        if term in text:
            return False, f"Nội dung lệch ngành so với website (phát hiện «{term}»)."

    if len(text) < 80:
        return True, None

    signature = [str(t).lower() for t in (website_context.get("signature_terms") or []) if t]
    pk_parts = [p for p in re.split(r"\s+", primary_keyword.lower()) if len(p) >= 3]
    has_signal = any(t in text for t in signature[:6])
    has_kw = any(p in text for p in pk_parts[:3])
    if signature and not has_signal and not has_kw:
        return False, "Nội dung không phản ánh đúng ngành/dịch vụ của website."
    return True, None


def rewrite_content_for_website_alignment(
    *,
    content_html: str,
    primary_keyword: str,
    title: str,
    outline: str,
    target_website: str,
    website_context: dict[str, Any],
    target_word_count: int,
) -> str:
    from app.services.llm_content_writer import generate_content_ai_suggestion

    guard = format_website_context_block(website_context)
    notes = (
        "VIẾT LẠI — nội dung trước đó LỆCH NGÀNH so với website. "
        "Chỉ viết đúng ngành/dịch vụ website; không suy diễn sang ngành khác.\n\n"
        + guard
    )
    new_html = generate_content_ai_suggestion(
        field="content",
        primary_keyword=primary_keyword,
        title=title,
        outline_content=outline,
        target_website=target_website,
        content=notes + "\n\nBÀI CŨ (sai ngành, tham khảo tránh lặp lỗi):\n" + content_html[:4000],
        target_word_count=target_word_count,
    )
    return str(new_html or content_html).strip() or content_html
