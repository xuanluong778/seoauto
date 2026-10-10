"""Chatbot CSKH — unified knowledge retrieval + public phone resolution."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotBot
from app.services import shared_knowledge
from app.services.chatbot_cskh_lead_detect import extract_phone
from app.services.chatbot_kb_service import search_kb_nodes

_MAX_KB_CHUNKS = 16
_MAX_SOURCE_CHUNKS = 8
_MIN_MERGE_SCORE = 1

_PHONE_DISPLAY_RE = re.compile(
    r"(?:\+?84|0)[\s.\-]*(?:3|5|7|8|9)[\s.\-]*(?:\d[\s.\-]*){8}",
    re.I,
)


def _format_phone_display(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return f"{digits[:4]}.{digits[4:7]}.{digits[7:]}"
    return str(phone or "").strip()


def _phone_from_text(text: str) -> str:
    raw = str(text or "")
    m = _PHONE_DISPLAY_RE.search(raw)
    if m:
        normalized = extract_phone(m.group(0))
        if normalized:
            return _format_phone_display(normalized)
    normalized = extract_phone(raw)
    return _format_phone_display(normalized) if normalized else ""


def resolve_public_phone(
    bot: ChatbotBot,
    *,
    kb_chunks: list[dict[str, Any]] | None = None,
    source_chunks: list[dict[str, Any]] | None = None,
    profile_text: str = "",
) -> str:
    """Pick the best public phone from bot config, profile, KB and crawled sources."""
    if bot.hotline and str(bot.hotline).strip():
        phone = _phone_from_text(str(bot.hotline))
        if phone:
            return phone

    for text in (profile_text, bot.main_services or "", bot.website_url or ""):
        phone = _phone_from_text(text)
        if phone:
            return phone

    for ch in (kb_chunks or []) + (source_chunks or []):
        for field in ("content", "title"):
            phone = _phone_from_text(str(ch.get(field) or ""))
            if phone:
                return phone

    return ""


def _merge_chunk_lists(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _key(ch: dict[str, Any]) -> str:
        nid = str(ch.get("node_id") or ch.get("id") or "")
        idx = ch.get("chunk_index")
        if idx is not None:
            return f"{nid}:c{idx}"
        sid = ch.get("source_id")
        if sid is not None:
            return f"src:{sid}"
        return f"{nid}:{str(ch.get('title') or '')[:40]}"

    for ch in primary + secondary:
        k = _key(ch)
        score = int(ch.get("score") or 0)
        prev = merged.get(k)
        if prev is None or score > int(prev.get("score") or 0):
            merged[k] = ch
        if k not in order:
            order.append(k)

    rows = [merged[k] for k in order if k in merged]
    rows.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("title") or "")))
    return rows[:limit]


def retrieve_chatbot_knowledge(
    db: Session,
    *,
    bot_id: int,
    user_id: int,
    query: str,
    kb_limit: int = _MAX_KB_CHUNKS,
    source_limit: int = _MAX_SOURCE_CHUNKS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Retrieve KB + website/FAQ sources with chunk-level and semantic search."""
    from app.services.chatbot_cskh_ai_service import search_knowledge_chunks

    shared_knowledge.migrate_legacy_chatbot_kb(db, user_id)

    doc_hits = search_kb_nodes(
        db, bot_id=bot_id, user_id=user_id, query=query, limit=kb_limit
    )
    chunk_hits = shared_knowledge.search_user_knowledge_chunks(
        user_id, query, limit=kb_limit, semantic=True
    )
    # Normalize chunk hits to kb_map shape
    normalized_chunks: list[dict[str, Any]] = []
    for h in chunk_hits:
        normalized_chunks.append(
            {
                "node_id": h.get("node_id") or h.get("id"),
                "title": h.get("title"),
                "content": h.get("content") or "",
                "tags": h.get("tags") or [],
                "score": h.get("score") or 0,
                "source": h.get("source") or "kb_chunk",
            }
        )

    kb_chunks = _merge_chunk_lists(doc_hits, normalized_chunks, limit=kb_limit)

    source_chunks = search_knowledge_chunks(
        db,
        bot_id=bot_id,
        user_id=user_id,
        query=query,
        limit=source_limit,
        include_unmatched_fallback=not kb_chunks,
    )

    # Boost when chunk search found strong service matches but doc search did not.
    if kb_chunks and _max_score(kb_chunks) < _MIN_MERGE_SCORE and normalized_chunks:
        kb_chunks = normalized_chunks[:kb_limit]

    return kb_chunks, source_chunks


def _max_score(chunks: list[dict[str, Any]]) -> int:
    if not chunks:
        return 0
    return max(int(c.get("score") or 0) for c in chunks)
