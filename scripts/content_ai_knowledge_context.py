"""
RAG context from AI Knowledge Base / Sơ đồ tri thức for Content AI (outline + content + bulk).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.services.ai_knowledge_docs import _document_full_text, _parse_knowledge_sections, _read_store
from app.services.ai_knowledge_store import get_default_base, list_bases
from app.services.content_draft_builder import content_ai_has_local_service_signal

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "brand_profile": ("brand profile", "hồ sơ thương hiệu", "thương hiệu"),
    "services": ("core services", "dịch vụ chính", "dịch vụ"),
    "audience": ("target audience", "đối tượng khách"),
    "search_intent": ("search intent", "ý định tìm kiếm"),
    "pain_points": ("pain points", "nỗi đau"),
    "trust_factors": ("trust factors", "yếu tố tạo niềm tin", "niềm tin"),
    "process": ("service process", "quy trình dịch vụ", "quy trình"),
    "pricing": ("pricing knowledge", "kiến thức về giá", "bảng giá", "chi phí"),
    "local_seo": ("local seo", "khu vực phục vụ", "local"),
    "semantic_keywords": ("seo keyword", "cụm từ khóa", "semantic"),
    "topic_graph": ("topic graph", "sơ đồ chủ đề"),
    "outline_pattern": ("outline pattern", "mẫu outline"),
    "faq": ("faq knowledge", "câu hỏi thường gặp"),
    "content_rules": ("content rules", "quy tắc viết content"),
    "image_context": ("image context", "tri thức tạo ảnh"),
    "cta": ("cta", "liên hệ", "hotline", "zalo"),
}

_LOCAL_REQUIRED_H2 = [
    "Dịch vụ {kw} phù hợp với ai?",
    "Các lỗi thường gặp / triệu chứng cần hỗ trợ",
    "Quy trình {kw}",
    "Bảng giá / các yếu tố ảnh hưởng chi phí",
    "Vì sao nên chọn {brand}?",
    "Khu vực phục vụ",
    "Lưu ý trước khi gọi dịch vụ",
    "Câu hỏi thường gặp (FAQ)",
    "Liên hệ / CTA",
]

_SERVICE_REQUIRED_H2 = [
    "Ai nên dùng {kw}?",
    "{kw} gồm những gì?",
    "Lợi ích khi dùng dịch vụ",
    "Quy trình thực hiện",
    "Giá / báo giá / yếu tố ảnh hưởng chi phí",
    "Lý do chọn {brand}",
    "Câu hỏi thường gặp (FAQ)",
    "CTA liên hệ",
]

_STOP = {
    "và",
    "của",
    "cho",
    "với",
    "là",
    "các",
    "như",
    "tại",
    "trên",
    "để",
    "khi",
    "có",
    "không",
    "the",
    "một",
    "bài",
    "việc",
    "dịch",
    "vụ",
}


def _norm_site(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (p.netloc or p.path or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host.rstrip("/")
    except Exception:
        return raw.lower().rstrip("/")


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9àáạảãâầấậẫăằắặẵèéẹẻẽêềếệểìíịỉĩòóọỏõôồốộổơờớợỡùúụủũưừứựừừửữđ]+", str(text or "").lower())
    return {w for w in words if len(w) >= 2 and w not in _STOP}


def _match_section_key(title: str) -> str:
    t = str(title or "").lower()
    for key, aliases in _SECTION_ALIASES.items():
        if any(a in t for a in aliases):
            return key
    return ""


def _resolve_user_id(user_id: int | None) -> int | None:
    if user_id is not None:
        return int(user_id)
    try:
        from app.core.user_context import get_request_user_id

        uid = get_request_user_id()
        return int(uid) if uid is not None else None
    except Exception:
        return None


def resolve_kb_for_target(target_website: str = "", *, user_id: int | None = None) -> dict[str, Any] | None:
    """Ưu tiên KB riêng của user; không dùng KB global kế thừa làm KB chính."""
    uid = _resolve_user_id(user_id)
    if uid is None:
        return None
    bases = [
        b
        for b in list_bases(user_id=uid)
        if b.get("enabled", True) and b.get("scope") == "user" and not b.get("is_inherited")
    ]
    if not bases:
        return None
    host = _norm_site(target_website)
    if host:
        for b in bases:
            if _norm_site(b.get("website_url") or "") == host:
                return b
        for b in bases:
            bh = _norm_site(b.get("website_url") or "")
            if bh and (host in bh or bh in host):
                return b
    return get_default_base(user_id=uid)


def _score_chunk(text: str, query_tokens: set[str], keyword: str) -> int:
    if not query_tokens:
        return 0
    body = str(text or "").lower()
    kw = str(keyword or "").lower()
    score = 0
    for tok in query_tokens:
        if tok in body:
            score += body.count(tok)
    if kw and kw in body:
        score += 10
    if "faq" in kw and "faq" in body:
        score += 3
    return score


def _search_kb_chunks(kb_id: str, keyword: str, *, limit: int = 16) -> list[dict[str, Any]]:
    docs = _read_store(kb_id).get("documents") or []
    q_tokens = _tokenize(keyword)
    hits: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        title = str(doc.get("title") or doc.get("filename") or "")
        for ch in doc.get("chunks") or []:
            if not isinstance(ch, dict):
                continue
            text = str(ch.get("text") or "")
            if not text.strip():
                continue
            sc = _score_chunk(text, q_tokens, keyword)
            if sc <= 0 and not q_tokens.intersection(_tokenize(title)):
                continue
            hits.append(
                {
                    "document_id": doc.get("id"),
                    "document_title": title,
                    "chunk_index": ch.get("index"),
                    "snippet": text[:480],
                    "score": sc,
                    "section_key": _match_section_key(text[:120]),
                }
            )
    hits.sort(key=lambda x: (-int(x.get("score") or 0), x.get("document_title") or ""))
    return hits[: max(1, min(limit, 24))]


def _merge_sections_from_docs(kb_id: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for doc in _read_store(kb_id).get("documents") or []:
        if not isinstance(doc, dict):
            continue
        full = _document_full_text(doc)
        for sec in _parse_knowledge_sections(full):
            key = _match_section_key(sec.get("title") or "")
            body = str(sec.get("body") or "").strip()
            if not key or not body:
                continue
            if key in out:
                out[key] = (out[key] + "\n\n" + body).strip()
            else:
                out[key] = body
    return out


def _extract_semantic_keywords(sections: dict[str, str], hits: list[dict[str, Any]]) -> list[str]:
    raw = sections.get("semantic_keywords") or ""
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-•").strip()
        if line and not line.lower().startswith("cụm"):
            lines.append(line)
    for h in hits:
        if h.get("section_key") == "semantic_keywords":
            for line in str(h.get("snippet") or "").splitlines():
                line = line.strip().lstrip("-•").strip()
                if line and line not in lines:
                    lines.append(line)
    return lines[:40]


def _extract_faq_items(sections: dict[str, str]) -> list[dict[str, str]]:
    raw = sections.get("faq") or ""
    items: list[dict[str, str]] = []
    blocks = re.split(r"(?i)faq\s*\d+\s*:", raw)
    if len(blocks) > 1:
        for block in blocks[1:]:
            block = block.strip()
            if not block:
                continue
            parts = re.split(r"\nanswer\s*:\s*", block, maxsplit=1, flags=re.I)
            q = parts[0].strip()
            a = parts[1].strip() if len(parts) > 1 else ""
            if q:
                items.append({"question": q, "answer": a})
    else:
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("?"):
                items.append({"question": line.lstrip("?").strip(), "answer": ""})
    return items[:12]


def _classify_outline_type(keyword: str) -> str:
    if content_ai_has_local_service_signal(keyword):
        return "local_service"
    k = str(keyword or "").lower()
    service_markers = (
        "dịch vụ",
        "sửa",
        "cài",
        "cứu",
        "thuê",
        "bảo trì",
        "lắp đặt",
        "vệ sinh",
        "khôi phục",
        "seo",
        "marketing",
    )
    if any(m in k for m in service_markers):
        return "service"
    return "general"


def _required_outline_h2(keyword: str, outline_type: str, brand: str) -> list[str]:
    brand = brand or "đơn vị"
    kw = keyword or "dịch vụ"
    tpl = _LOCAL_REQUIRED_H2 if outline_type == "local_service" else _SERVICE_REQUIRED_H2
    if outline_type == "general":
        tpl = _SERVICE_REQUIRED_H2
    return [t.format(kw=kw, brand=brand) for t in tpl]


def get_relevant_knowledge_for_keyword(
    keyword: str,
    *,
    target_website: str = "",
    limit_hits: int = 14,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Retrieve structured knowledge for a primary keyword.
    Safe fallback: returns {"found": False} when no KB / no match.
    """
    pk = re.sub(r"\s+", " ", str(keyword or "").strip())
    empty: dict[str, Any] = {
        "found": False,
        "keyword": pk,
        "kb_id": "",
        "kb_name": "",
        "outline_type": _classify_outline_type(pk),
    }
    if not pk:
        return empty

    uid = _resolve_user_id(user_id)
    kb = resolve_kb_for_target(target_website, user_id=uid)
    if not kb:
        return empty

    kb_id = str(kb.get("id") or "")
    hits = _search_kb_chunks(kb_id, pk, limit=limit_hits)
    sections = _merge_sections_from_docs(kb_id)
    # Bổ sung ngữ cảnh từ KB global kế thừa (ưu tiên thấp hơn KB riêng).
    if uid is not None:
        for gb in list_bases(user_id=uid):
            if not gb.get("enabled", True) or not gb.get("is_inherited"):
                continue
            gid = str(gb.get("id") or "")
            if not gid or gid == kb_id:
                continue
            for gh in _search_kb_chunks(gid, pk, limit=max(4, limit_hits // 2)):
                hits.append({**gh, "score": int(gh.get("score") or 0) // 2, "source": "inherited"})
            gsec = _merge_sections_from_docs(gid)
            for key, body in gsec.items():
                if key not in sections:
                    sections[key] = body
    if not hits and not sections:
        return empty

    brand = str(kb.get("brand_name") or kb.get("name") or "").strip()
    outline_type = _classify_outline_type(pk)
    if hits and not sections:
        for h in hits:
            sk = str(h.get("section_key") or "").strip()
            snip = str(h.get("snippet") or "").strip()
            if sk and snip:
                sections[sk] = (sections.get(sk, "") + "\n" + snip).strip()
    elif hits:
        for h in hits:
            sk = str(h.get("section_key") or "").strip()
            snip = str(h.get("snippet") or "").strip()
            if sk and snip and sk not in sections:
                sections[sk] = snip

    faq_items = _extract_faq_items(sections)
    semantic = _extract_semantic_keywords(sections, hits)

    cta = ""
    for key in ("cta", "brand_profile"):
        blob = sections.get(key) or ""
        m = re.search(r"(?i)(cta|hotline|zalo|liên hệ)[^\n]*", blob)
        if m:
            cta = m.group(0).strip()
            break

    return {
        "found": True,
        "keyword": pk,
        "kb_id": kb_id,
        "kb_name": str(kb.get("name") or ""),
        "brand_name": brand,
        "website_url": str(kb.get("website_url") or ""),
        "outline_type": outline_type,
        "sections": sections,
        "hits": hits,
        "semantic_keywords": semantic,
        "faq_items": faq_items,
        "cta": cta,
        "required_outline_h2": _required_outline_h2(pk, outline_type, brand),
        "content_rules": sections.get("content_rules") or "",
        "outline_pattern": sections.get("outline_pattern") or "",
        "image_context": sections.get("image_context") or "",
        "no_invented_pricing": "không tự bịa" in (sections.get("pricing") or "").lower()
        or "không tự bịa" in (sections.get("content_rules") or "").lower(),
    }


def build_outline_context_from_knowledge(knowledge: dict[str, Any], *, max_chars: int = 9000) -> str:
    """Compact SOURCE block for outline / content LLM."""
    if not knowledge or not knowledge.get("found"):
        return ""
    parts: list[str] = []
    parts.append(f"KB: {knowledge.get('kb_name') or ''} | Brand: {knowledge.get('brand_name') or ''}")
    parts.append(f"Outline type: {knowledge.get('outline_type') or 'general'}")
    if knowledge.get("required_outline_h2"):
        parts.append(
            "BẮT BUỘC có các H2 (có thể đặt tên tự nhiên, giữ đúng ý):\n- "
            + "\n- ".join(knowledge.get("required_outline_h2") or [])
        )
    sec = knowledge.get("sections") or {}
    order = (
        "brand_profile",
        "services",
        "audience",
        "pain_points",
        "trust_factors",
        "process",
        "pricing",
        "local_seo",
        "semantic_keywords",
        "outline_pattern",
        "faq",
        "content_rules",
        "cta",
        "image_context",
    )
    for key in order:
        body = str(sec.get(key) or "").strip()
        if not body:
            continue
        label = key.replace("_", " ").upper()
        parts.append(f"=== {label} ===\n{_truncate(body, 2200)}")
    if knowledge.get("semantic_keywords"):
        parts.append("=== SEMANTIC KEYWORDS (gợi ý) ===\n" + ", ".join(knowledge["semantic_keywords"][:25]))
    blob = "\n\n".join(parts).strip()
    return _truncate(blob, max_chars)


def build_content_prompt_with_knowledge(
    knowledge: dict[str, Any],
    *,
    field: str,
    primary_keyword: str = "",
) -> str:
    """Extra instruction block appended to field prompts."""
    if not knowledge or not knowledge.get("found"):
        return ""
    f = (field or "").strip().lower()
    pk = str(primary_keyword or knowledge.get("keyword") or "").strip()
    brand = str(knowledge.get("brand_name") or "thương hiệu").strip()
    rules = str(knowledge.get("content_rules") or "").strip()
    outline_type = knowledge.get("outline_type") or "general"

    common = (
        "\n\n=== KNOWLEDGE BASE (bắt buộc ưu tiên, không bịa) ===\n"
        f"- Thương hiệu: {brand}. Chỉ dùng thông tin có trong KNOWLEDGE_BASE SOURCE.\n"
        "- KHÔNG tự bịa giá cố định, thời gian bảo hành, % cam kết, case study, số liệu nếu KB không có.\n"
        "- Thiếu số liệu → ghi «Cần bổ sung dữ liệu» (ngắn), không placeholder.\n"
        "- Không outline/bài sơ sài chỉ «định nghĩa / lợi ích / tiêu chí lựa chọn».\n"
    )
    if rules:
        common += f"- Quy tắc từ KB:\n{_truncate(rules, 1200)}\n"

    if f == "outline_content":
        pat = str(knowledge.get("outline_pattern") or "").strip()
        extra = (
            common
            + f"- Keyword: {pk}. Intent/outline: {outline_type}.\n"
            "- Dàn ý phải SÂU: mỗi H2 có 2–5 H3 cụ thể, có FAQ, CTA, quy trình, khu vực (nếu local).\n"
            "- Bám mẫu OUTLINE PATTERN trong SOURCE nếu có; không copy y nguyên nhưng giữ cấu trúc.\n"
        )
        if pat:
            extra += f"\nMẪU OUTLINE (tham khảo từ KB):\n{_truncate(pat, 3500)}\n"
        return extra

    if f == "content":
        faq = knowledge.get("faq_items") or []
        faq_hint = ""
        if faq:
            faq_hint = "\n".join(
                f"Q: {x.get('question','')}\nA: {_truncate(x.get('answer',''), 280)}"
                for x in faq[:6]
            )
        return (
            common
            + f"- Viết đúng dịch vụ/khu vực/CTA của {brand}; giọng chuyên nghiệp, rõ ràng.\n"
            "- Mở bài nêu đúng pain point; có quy trình, yếu tố chi phí (không bịa giá), trust, FAQ, CTA.\n"
            + (f"\nFAQ từ KB (tham khảo):\n{faq_hint}\n" if faq_hint else "")
        )

    if f in {"title", "meta_description"}:
        return (
            common
            + f"- Title/meta phản ánh đúng dịch vụ và {brand}; có lợi ích/CTA nhẹ.\n"
        )
    return common


def _truncate(text: str, max_chars: int) -> str:
    t = str(text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 3].rstrip() + "..."


def build_outline_from_knowledge_rule(knowledge: dict[str, Any], *, title: str = "") -> str:
    """Rule-based outline when LLM off — uses KB outline pattern + required H2."""
    if not knowledge or not knowledge.get("found"):
        return ""
    pk = str(knowledge.get("keyword") or "").strip()
    brand = str(knowledge.get("brand_name") or "").strip()
    h1 = title or pk
    lines = [f"<h1>{h1}</h1>"]
    pat = str(knowledge.get("outline_pattern") or "")
    if pat:
        for raw in pat.splitlines():
            line = raw.strip()
            if not line or line.startswith("="):
                continue
            if re.match(r"^H1\s*:", line, re.I):
                lines.append(f"<h1>{line.split(':', 1)[-1].strip()}</h1>")
            elif re.match(r"^H2\s*:", line, re.I):
                lines.append(f"<h2>{line.split(':', 1)[-1].strip()}</h2>")
            elif re.match(r"^H3\s*:", line, re.I):
                lines.append(f"<h3>{line.split(':', 1)[-1].strip()}</h3>")
    else:
        for h2 in knowledge.get("required_outline_h2") or []:
            lines.append(f"<h2>{h2}</h2>")
            lines.append("<h3>Chi tiết triển khai</h3>")
            lines.append("<h3>Lưu ý thực tế</h3>")
    if brand and not any("chọn" in x.lower() for x in lines):
        lines.append(f"<h2>Vì sao nên chọn {brand}?</h2>")
    return "\n".join(lines)


# Aliases (API naming parity with product docs)
getRelevantKnowledgeForKeyword = get_relevant_knowledge_for_keyword
buildOutlineContextFromKnowledge = build_outline_context_from_knowledge
buildContentPromptWithKnowledge = build_content_prompt_with_knowledge
