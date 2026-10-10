"""
RAG context from AI Knowledge Base / Sơ đồ tri thức for Content AI (outline + content + bulk).
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

_LOG = logging.getLogger(__name__)

from app.services.ai_knowledge_docs import _document_full_text, _parse_knowledge_sections, _read_store
from app.services.ai_knowledge_store import get_default_base, list_bases
from app.services.content_draft_builder import content_ai_has_local_service_signal

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "brand_profile": ("brand profile", "hồ sơ thương hiệu", "thương hiệu", "thông tin công ty", "giới thiệu"),
    "services": ("core services", "dịch vụ chính", "dịch vụ"),
    "audience": ("target audience", "đối tượng khách"),
    "search_intent": ("search intent", "ý định tìm kiếm"),
    "pain_points": ("pain points", "nỗi đau"),
    "trust_factors": ("trust factors", "yếu tố tạo niềm tin", "niềm tin"),
    "process": ("service process", "quy trình dịch vụ", "quy trình"),
    "pricing": (
        "pricing knowledge",
        "kiến thức về giá",
        "bảng giá",
        "chi phí",
        "giá dịch vụ",
        "báo giá",
        "mức giá",
        "giá tham khảo",
    ),
    "local_seo": ("local seo", "khu vực phục vụ", "local"),
    "semantic_keywords": ("seo keyword", "cụm từ khóa", "semantic"),
    "topic_graph": ("topic graph", "sơ đồ chủ đề"),
    "outline_pattern": ("outline pattern", "mẫu outline"),
    "faq": ("faq knowledge", "câu hỏi thường gặp"),
    "content_rules": ("content rules", "quy tắc viết content"),
    "image_context": ("image context", "tri thức tạo ảnh"),
    "cta": ("cta", "liên hệ", "hotline", "zalo", "sđt", "sdt", "điện thoại", "phone", "contact"),
    "general": ("tổng quan", "overview", "general", "thông tin chung"),
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


_SNIPPET_CHARS = 2000
_MAX_CHUNK_HITS = 40


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9àáạảãâầấậẫăằắặẵèéẹẻẽêềếệểìíịỉĩòóọỏõôồốộổơờớợỡùúụủũưừứựừừửữđ]+", str(text or "").lower())
    tokens = {w for w in words if len(w) >= 2 and w not in _STOP}
    phrase = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if phrase:
        tokens.add(phrase)
    return tokens


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


def _user_has_content_project_on_website(user_id: int | None, host: str) -> bool:
    """User có project Content AI trỏ tới website (legacy KB orphan)."""
    if not host or user_id is None:
        return False
    try:
        from app.services.content_ai_project_store import list_content_ai_projects
    except Exception:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    for row in list_content_ai_projects(user_id=uid, limit=80):
        rh = _norm_site(str(row.get("target_website") or ""))
        if not rh:
            continue
        if rh == host or host in rh or rh in host:
            return True
    return False


def _kb_owner_user_id(kb_row: dict[str, Any]) -> int:
    try:
        return int(kb_row.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def _resolve_kb_by_website_fallback(
    host: str,
    *,
    user_id: int | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """
    Khớp KB theo website_url chuẩn hóa.
    Không trả KB thuộc user khác (trừ legacy orphan + user có project cùng website).
    """
    if not host:
        return None, "no_target_website"
    try:
        from app.services.ai_knowledge_store import _normalize, _read_all
        from app.services.user_scope import belongs_to_user, is_legacy_orphan
    except Exception:
        return None, "kb_store_unavailable"
    uid = _resolve_user_id(user_id)
    ranked: list[tuple[int, dict[str, Any], str]] = []
    for raw in _read_all():
        row = _normalize(raw)
        if not row.get("enabled", True) or str(row.get("scope") or "") != "user":
            continue
        bh = _norm_site(row.get("website_url") or "")
        if not bh:
            continue
        if bh != host and host not in bh and bh not in host:
            continue
        owner = _kb_owner_user_id(row)
        orphan = is_legacy_orphan(raw) or bool(row.get("legacy_orphan"))
        if uid is not None:
            if owner > 0 and owner != uid and not orphan:
                continue
            if orphan and owner <= 0 and not _user_has_content_project_on_website(uid, host):
                continue
            if owner > 0 and owner == uid:
                pass
            elif not belongs_to_user(raw, uid) and not (orphan and _user_has_content_project_on_website(uid, host)):
                continue
        score = 0
        if bh == host:
            score += 10
        if uid is not None and belongs_to_user(raw, uid):
            score += 100
        if row.get("is_default"):
            score += 5
        if not orphan:
            score += 20
        reason = "website_match_owned" if belongs_to_user(raw, uid or 0) else "website_match_legacy_project"
        ranked.append((score, row, reason))
    if not ranked:
        return None, f"no_kb_for_host:{host}"
    ranked.sort(key=lambda x: (-x[0], str(x[1].get("name") or "").lower()))
    best = ranked[0]
    return best[1], best[2]


def resolve_kb_for_target(
    target_website: str = "",
    *,
    user_id: int | None = None,
) -> dict[str, Any] | None:
    """Ưu tiên KB riêng của user; không dùng KB global kế thừa làm KB chính."""
    uid = _resolve_user_id(user_id)
    if uid is None:
        return None
    host = _norm_site(target_website)
    bases = [
        b
        for b in list_bases(user_id=uid)
        if b.get("enabled", True) and b.get("scope") == "user" and not b.get("is_inherited")
    ]
    if host and bases:
        for b in bases:
            if _norm_site(b.get("website_url") or "") == host:
                _LOG.info(
                    "content_ai_kb_resolved kb_id=%s reason=website_exact user_id=%s host=%s",
                    b.get("id"),
                    uid,
                    host,
                )
                return b
        for b in bases:
            bh = _norm_site(b.get("website_url") or "")
            if bh and (host in bh or bh in host):
                _LOG.info(
                    "content_ai_kb_resolved kb_id=%s reason=website_partial user_id=%s host=%s",
                    b.get("id"),
                    uid,
                    host,
                )
                return b
    default = get_default_base(user_id=uid) if bases else None
    if default and not host:
        _LOG.info("content_ai_kb_resolved kb_id=%s reason=user_default user_id=%s", default.get("id"), uid)
        return default
    fallback, fb_reason = _resolve_kb_by_website_fallback(host, user_id=uid)
    if fallback:
        _LOG.info(
            "content_ai_kb_resolved kb_id=%s reason=%s user_id=%s host=%s",
            fallback.get("id"),
            fb_reason,
            uid,
            host,
        )
        return fallback
    if not host:
        _LOG.info("content_ai_kb_not_found user_id=%s reason=no_host_no_match", uid)
    elif not bases:
        _LOG.info("content_ai_kb_not_found user_id=%s host=%s reason=no_user_bases", uid, host)
    else:
        _LOG.info("content_ai_kb_not_found user_id=%s host=%s reason=website_no_match", uid, host)
    return default


def _parse_content_ai_knowledge_sections(text: str) -> list[dict[str, str]]:
    """
    Parse sơ đồ tri thức Content AI: hỗ trợ cả «=== title ===» và banner
    «====\\nTITLE\\n====» (định dạng phổ biến trong file import KB).
    """
    sections: list[dict[str, str]] = []
    lines = str(text or "").splitlines()
    banner_re = re.compile(r"^=+\s*$")
    single_re = re.compile(r"^=+\s*(.+?\S.+?)\s*=+$|^===+\s*(.+?\S.+?)\s*===+$")
    title = "Tổng quan"
    body_lines: list[str] = []
    i = 0

    def _flush() -> None:
        nonlocal title, body_lines
        body = "\n".join(body_lines).strip()
        if body or sections:
            sections.append({"title": title, "body": body})
        body_lines = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if banner_re.match(stripped):
            if i + 2 < len(lines):
                mid = lines[i + 1].strip()
                if mid and banner_re.match(lines[i + 2].strip()):
                    _flush()
                    title = mid
                    i += 3
                    continue
            i += 1
            continue
        m = single_re.match(stripped)
        if m:
            label = (m.group(1) or m.group(2) or "").strip()
            if label:
                _flush()
                title = label
                i += 1
                continue
        body_lines.append(line)
        i += 1
    _flush()
    return [s for s in sections if s.get("body") or len(sections) == 1]


_PRICE_NUMBER_RE = re.compile(r"\d[\d.,\s]*(?:đ|vnđ|vnd)\b", re.I)


def _kb_text_has_price_numbers(text: str) -> bool:
    return bool(_PRICE_NUMBER_RE.search(str(text or "")))


def _is_pricing_document(doc: dict[str, Any], full_text: str) -> bool:
    label = " ".join(
        str(doc.get(key) or "").lower() for key in ("title", "filename")
    )
    if any(x in label for x in ("bảng giá", "bang-gia", "bang gia", "báo giá", "pricing")):
        return True
    body = str(full_text or "")
    return bool(re.search(r"\|\s*giá", body, re.I)) and _kb_text_has_price_numbers(body)


def _score_chunk(text: str, query_tokens: set[str], keyword: str) -> int:
    body = str(text or "").lower()
    kw = str(keyword or "").lower()
    if not body.strip():
        return 0
    score = 0
    for tok in query_tokens:
        if tok and tok in body:
            score += body.count(tok) if len(tok) < 80 else 8
    if kw and kw in body:
        score += 10
    if "faq" in kw and "faq" in body:
        score += 3
    return score


def _search_kb_chunks(kb_id: str, keyword: str, *, limit: int = 20) -> list[dict[str, Any]]:
    docs = _read_store(kb_id).get("documents") or []
    q_tokens = _tokenize(keyword)
    hits: list[dict[str, Any]] = []
    matched_docs: set[str] = set()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        if doc.get("is_active") is False:
            continue
        title = str(doc.get("title") or doc.get("filename") or "")
        doc_id = str(doc.get("id") or "")
        for ch in doc.get("chunks") or []:
            if not isinstance(ch, dict):
                continue
            text = str(ch.get("text") or "")
            if not text.strip():
                continue
            sc = _score_chunk(text, q_tokens, keyword)
            if sc <= 0 and not q_tokens.intersection(_tokenize(title)):
                continue
            matched_docs.add(doc_id)
            hits.append(
                {
                    "document_id": doc.get("id"),
                    "document_title": title,
                    "chunk_index": ch.get("index"),
                    "snippet": text[:_SNIPPET_CHARS],
                    "score": sc,
                    "section_key": _match_section_key(text[:120]),
                    "kb_id": kb_id,
                }
            )
        full = _document_full_text(doc)
        doc_score = _score_chunk(full, q_tokens, keyword)
        if doc_score > 0 and doc_id not in matched_docs:
            matched_docs.add(doc_id)
            hits.append(
                {
                    "document_id": doc.get("id"),
                    "document_title": title,
                    "chunk_index": 0,
                    "snippet": full[:_SNIPPET_CHARS],
                    "score": doc_score,
                    "section_key": _match_section_key(title) or "general",
                    "kb_id": kb_id,
                }
            )
    hits.sort(key=lambda x: (-int(x.get("score") or 0), x.get("document_title") or ""))
    return hits[: max(1, min(limit, _MAX_CHUNK_HITS))]


def _fallback_all_kb_chunks(kb_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Khi từ khóa không khớp chunk — vẫn lấy ngữ cảnh KB theo website."""
    hits: list[dict[str, Any]] = []
    for doc in _read_store(kb_id).get("documents") or []:
        if not isinstance(doc, dict):
            continue
        if doc.get("is_active") is False:
            continue
        title = str(doc.get("title") or doc.get("filename") or "")
        full = _document_full_text(doc)
        if full.strip():
            hits.append(
                {
                    "document_id": doc.get("id"),
                    "document_title": title,
                    "chunk_index": 0,
                    "snippet": full[:_SNIPPET_CHARS],
                    "score": 1,
                    "section_key": _match_section_key(title) or "general",
                    "kb_id": kb_id,
                }
            )
            continue
        for ch in doc.get("chunks") or []:
            if not isinstance(ch, dict):
                continue
            text = str(ch.get("text") or "").strip()
            if not text:
                continue
            hits.append(
                {
                    "document_id": doc.get("id"),
                    "document_title": title,
                    "chunk_index": ch.get("index"),
                    "snippet": text[:_SNIPPET_CHARS],
                    "score": 1,
                    "section_key": _match_section_key(text[:120]) or "general",
                    "kb_id": kb_id,
                }
            )
    return hits[: max(1, min(limit, _MAX_CHUNK_HITS))]


def _merge_sections_from_kb_ids(kb_ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    seen_ids: set[str] = set()
    for kid in kb_ids:
        if not kid or kid in seen_ids:
            continue
        seen_ids.add(kid)
        sec = _merge_sections_from_docs(kid)
        for key, body in sec.items():
            body = str(body or "").strip()
            if not body:
                continue
            if key in out:
                if body not in out[key]:
                    out[key] = (out[key] + "\n\n" + body).strip()
            else:
                out[key] = body
    return out


def _merge_sections_from_docs(kb_id: str) -> dict[str, str]:
    out: dict[str, str] = {}
    pricing_docs: list[str] = []
    for doc in _read_store(kb_id).get("documents") or []:
        if not isinstance(doc, dict):
            continue
        if doc.get("is_active") is False:
            continue
        if str(doc.get("node_type") or "node") == "group":
            continue
        full = _document_full_text(doc)
        if not full.strip():
            continue
        if _is_pricing_document(doc, full):
            pricing_docs.append(full.strip())
        parsed = _parse_content_ai_knowledge_sections(full)
        if not parsed:
            parsed = _parse_knowledge_sections(full)
        for sec in parsed:
            key = _match_section_key(sec.get("title") or "")
            body = str(sec.get("body") or "").strip()
            if not body:
                continue
            if not key:
                key = "general"
            if key in out:
                out[key] = (out[key] + "\n\n" + body).strip()
            else:
                out[key] = body
        if full.strip() and not parsed:
            out["general"] = (out.get("general", "") + "\n\n" + full.strip()).strip()
    for pd in pricing_docs:
        label = "=== BẢNG GIÁ CHÍNH THỨC (tài liệu KB) ==="
        block = f"{label}\n{pd}"
        if "pricing" in out:
            if pd not in out["pricing"]:
                out["pricing"] = (out["pricing"] + "\n\n" + block).strip()
        else:
            out["pricing"] = block
    if not out:
        joined: list[str] = []
        for doc in _read_store(kb_id).get("documents") or []:
            if not isinstance(doc, dict):
                continue
            if doc.get("is_active") is False:
                continue
            full = _document_full_text(doc)
            if full.strip():
                joined.append(full.strip())
        if joined:
            out["general"] = _truncate("\n\n".join(joined), 24000)
    elif out.get("pricing") and _kb_text_has_price_numbers(out["pricing"]):
        # Ghi đè hướng dẫn «không bịa giá» khi KB đã có bảng giá số thật.
        out["pricing"] = (
            "BẮT BUỘC dùng giá cụ thể từ bảng giá bên dưới trong HTML (<table>); "
            "KHÔNG ghi «Cần bổ sung dữ liệu» cho dịch vụ đã có giá.\n\n"
            + out["pricing"]
        ).strip()
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
    uid = _resolve_user_id(user_id)
    host = _norm_site(target_website)
    kb = resolve_kb_for_target(target_website, user_id=uid)
    from app.services.shared_knowledge import list_consumer_kb_groups

    own_ids: list[str] = []
    inherited_ids: list[str] = []
    if uid is not None:
        own_ids, inherited_ids = list_consumer_kb_groups(uid)
    if not kb and own_ids:
        from app.services.ai_knowledge_store import get_base

        kb = get_base(own_ids[0], user_id=uid) or get_default_base(user_id=uid)
    if not kb and not own_ids and not inherited_ids:
        reason = "no_kb_match"
        if not uid:
            reason = "missing_user_id"
        elif not host:
            reason = "missing_target_website"
        _LOG.info(
            "content_ai_kb_miss keyword=%s user_id=%s host=%s reason=%s",
            pk[:80],
            uid,
            host,
            reason,
        )
        empty["kb_resolve_reason"] = reason
        return empty

    kb_id = str((kb or {}).get("id") or (own_ids[0] if own_ids else (inherited_ids[0] if inherited_ids else "")))
    ordered_ids: list[str] = []
    if kb_id:
        ordered_ids.append(kb_id)
    for kid in own_ids + inherited_ids:
        if kid and kid not in ordered_ids:
            ordered_ids.append(kid)
    inherited_set = set(inherited_ids)
    hit_limit = max(8, min(int(limit_hits or 14), _MAX_CHUNK_HITS))
    hits: list[dict[str, Any]] = []
    seen_hits: set[tuple[Any, Any, str]] = set()
    for kid in ordered_ids:
        extra = _search_kb_chunks(kid, pk, limit=hit_limit) if pk else []
        for gh in extra:
            key = (gh.get("document_id"), gh.get("chunk_index"), kid)
            if key in seen_hits:
                continue
            seen_hits.add(key)
            row = dict(gh)
            if kid in inherited_set:
                row["score"] = int(row.get("score") or 0) // 2
                row["source"] = "inherited"
            hits.append(row)
    hits.sort(key=lambda x: (-int(x.get("score") or 0), x.get("document_title") or ""))
    hits = hits[:hit_limit]
    if not hits:
        for kid in ordered_ids:
            for gh in _fallback_all_kb_chunks(kid, limit=hit_limit):
                key = (gh.get("document_id"), gh.get("chunk_index"), kid)
                if key in seen_hits:
                    continue
                seen_hits.add(key)
                hits.append(gh)
            if len(hits) >= hit_limit:
                break
        hits = hits[:hit_limit]
    sections = _merge_sections_from_kb_ids(ordered_ids)
    if not hits and not sections:
        _LOG.warning(
            "content_ai_kb_empty_docs kb_id=%s keyword=%s user_id=%s",
            kb_id,
            pk[:80],
            uid,
        )
        empty["kb_resolve_reason"] = "kb_has_no_documents"
        return empty

    brand = str((kb or {}).get("brand_name") or (kb or {}).get("name") or "").strip()
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

    used_sections = [k for k, v in sections.items() if str(v or "").strip()]
    _LOG.info(
        "content_ai_kb_hit kb_id=%s kb_name=%s user_id=%s host=%s sections=%s",
        kb_id,
        kb.get("name") if kb else "",
        uid,
        host,
        used_sections,
    )

    return {
        "found": True,
        "keyword": pk,
        "kb_id": kb_id,
        "kb_name": str((kb or {}).get("name") or ""),
        "brand_name": brand,
        "website_url": str((kb or {}).get("website_url") or ""),
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
        "no_invented_pricing": not _kb_text_has_price_numbers(sections.get("pricing") or "")
        and (
            "không tự bịa" in (sections.get("pricing") or "").lower()
            or "không tự bịa" in (sections.get("content_rules") or "").lower()
        ),
        "has_pricing_numbers": _kb_text_has_price_numbers(sections.get("pricing") or ""),
        "kb_sections_used": used_sections,
        "kb_resolve_reason": "matched",
    }


def build_outline_context_from_knowledge(knowledge: dict[str, Any], *, max_chars: int = 18000) -> str:
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
        "general",
    )
    for key in order:
        body = str(sec.get(key) or "").strip()
        if not body:
            continue
        label = key.replace("_", " ").upper()
        cap = 8000 if key == "pricing" else 4500
        parts.append(f"=== {label} ===\n{_truncate(body, cap)}")
    if knowledge.get("semantic_keywords"):
        parts.append("=== SEMANTIC KEYWORDS (gợi ý) ===\n" + ", ".join(knowledge["semantic_keywords"][:25]))
    blob = "\n\n".join(parts).strip()
    cap = max(max_chars, 20000) if sec.get("pricing") else max_chars
    return _truncate(blob, cap)


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
        f"- Thương hiệu: {brand}. BẮT BUỘC dùng thông tin có trong KNOWLEDGE_BASE SOURCE (giá, SĐT/hotline, quy trình, FAQ, CTA).\n"
        "- KHÔNG tự bịa giá cố định, thời gian bảo hành, % cam kết, case study, số liệu nếu KB không có.\n"
        "- KHÔNG ghi «Cần bổ sung dữ liệu» nếu thông tin đã có trong KNOWLEDGE_BASE/SOURCE (bảng giá, liên hệ, hồ sơ thương hiệu…).\n"
        "- Chỉ ghi «Cần bổ sung dữ liệu» khi một chi tiết cụ thể hoàn toàn không có trong toàn bộ SOURCE.\n"
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
        pricing_blob = str((knowledge.get("sections") or {}).get("pricing") or "")
        pricing_hint = ""
        if _kb_text_has_price_numbers(pricing_blob):
            pricing_hint = (
                "\n- Bảng giá trong SOURCE (=== PRICING ===): BẮT BUỘC chép giá VNĐ vào <table> HTML;"
                " không placeholder «Cần bổ sung dữ liệu» cho dòng đã có giá trong KB.\n"
            )
        return (
            common
            + f"- Viết đúng dịch vụ/khu vực/CTA của {brand}; giọng chuyên nghiệp, rõ ràng.\n"
            "- Mở bài nêu đúng pain point; có quy trình, yếu tố chi phí, trust, FAQ, CTA.\n"
            "- Khi có OUTLINE_SOURCE: phủ 100% H2/H3; mỗi H2 đủ nội dung; ưu tiên giá/hotline/FAQ từ KB.\n"
            + pricing_hint
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


CONTENT_AI_LLM_UNAVAILABLE_CODE = "CONTENT_AI_LLM_UNAVAILABLE"
CONTENT_AI_LLM_UNAVAILABLE_MESSAGE = (
    "Hệ thống đang nâng cấp tính năng, mong bạn thông cảm chúng tôi sẽ quay trở lại sớm nhất !"
)


class ContentAiLlmUnavailableError(Exception):
    """LLM không khả dụng hoặc thiếu dữ liệu nguồn thật (website/KB) cho tab Viết bài SEO."""

    code = CONTENT_AI_LLM_UNAVAILABLE_CODE

    def __init__(self, internal_reason: str = "") -> None:
        self.internal_reason = str(internal_reason or "").strip()
        super().__init__(CONTENT_AI_LLM_UNAVAILABLE_MESSAGE)


def gather_single_writer_source_context(
    *,
    primary_keyword: str,
    target_website: str = "",
    content: str = "",
    outline_content: str = "",
    title: str = "",
    user_id: int | None = None,
) -> dict[str, Any]:
    """Thu thập KB + text website (cache trong request khi có)."""
    from app.services.content_ai_request_cache import cache_get_or_set

    pk = str(primary_keyword or "").strip()
    site = str(target_website or "").strip()
    knowledge: dict[str, Any] | None = None
    kb_found = False
    if pk:
        try:
            knowledge = cache_get_or_set(
                f"kb:validate:{pk.lower()}:{site.lower()}",
                lambda: get_relevant_knowledge_for_keyword(
                    pk,
                    target_website=site,
                    user_id=user_id,
                ),
            )
            kb_found = bool(knowledge and knowledge.get("found"))
        except Exception:
            knowledge = None
            kb_found = False

    website_text = ""
    # Không crawl website ở bước validate — tránh chặn trước khi gọi LLM (crawl trong generate khi cần).
    has_website_data = bool(site)

    notes = str(content or "").strip()
    outline = str(outline_content or "").strip()
    brief_title = str(title or "").strip()
    return {
        "knowledge": knowledge,
        "kb_found": kb_found,
        "website_text": website_text,
        "website_text_len": len(website_text),
        "has_website_data": has_website_data,
        "has_user_brief": len(notes) >= 30 or len(outline) >= 30 or len(brief_title) >= 8,
    }


def assert_single_writer_source_ready(
    *,
    primary_keyword: str,
    target_website: str = "",
    content: str = "",
    outline_content: str = "",
    title: str = "",
    field: str = "",
    user_id: int | None = None,
) -> dict[str, Any]:
    """
  Tab Viết bài SEO: bắt buộc có dữ liệu thật từ website crawl và/hoặc KB trước khi gọi LLM.
  """
    f = str(field or "").strip().lower()
    pk = str(primary_keyword or "").strip()
    # Gợi ý brief (title/meta/tags…): chỉ cần từ khóa — bỏ lookup KB để phản hồi nhanh.
    if f in {
        "title",
        "meta_description",
        "slug",
        "tags",
        "primary_keyword",
        "secondary_keywords",
    } and pk:
        site = str(target_website or "").strip()
        notes = str(content or "").strip()
        outline = str(outline_content or "").strip()
        brief_title = str(title or "").strip()
        return {
            "knowledge": None,
            "kb_found": False,
            "website_text": "",
            "website_text_len": 0,
            "has_website_data": bool(site),
            "has_user_brief": len(notes) >= 30 or len(outline) >= 30 or len(brief_title) >= 8,
        }

    ctx = gather_single_writer_source_context(
        primary_keyword=primary_keyword,
        target_website=target_website,
        content=content,
        outline_content=outline_content,
        title=title,
        user_id=user_id,
    )
    site = str(target_website or "").strip()
    if f in {"target_website"}:
        return ctx
    if ctx["kb_found"] or ctx["has_website_data"]:
        return ctx
    # Đã nhập URL website — không chặn chờ crawl validate (LLM tự lấy context khi cần).
    if site and f in {"content", "outline_content"}:
        return ctx
    if f in {"content", "outline_content"}:
        raise ContentAiLlmUnavailableError("content_requires_kb_or_website")
    # Tiêu đề, meta, slug… chỉ cần từ khóa chính — không bắt buộc crawl website/KB.
    if f in {
        "title",
        "meta_description",
        "slug",
        "tags",
        "primary_keyword",
        "secondary_keywords",
    } and pk:
        return ctx
    if ctx["has_user_brief"]:
        return ctx
    raise ContentAiLlmUnavailableError("no_kb_no_website")


# Aliases (API naming parity with product docs)
getRelevantKnowledgeForKeyword = get_relevant_knowledge_for_keyword
buildOutlineContextFromKnowledge = build_outline_context_from_knowledge
buildContentPromptWithKnowledge = build_content_prompt_with_knowledge
