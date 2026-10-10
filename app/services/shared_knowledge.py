"""Single user/org Knowledge Base used by Settings, Content AI, Chatbot CSKH.

Canonical store: JSON AI Knowledge Base (ai_knowledge_store + knowledge_docs).
Legacy ChatbotKbNode / ChatbotKnowledgeSource rows are migrated in once (idempotent)
and left in place so nothing is destroyed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.ai_knowledge_docs import (
    MAX_DOCS_PER_KB,
    _document_full_text,
    _read_store,
    delete_document,
    find_document_by_source_key,
    import_text,
    update_document,
)
from app.services.ai_knowledge_store import create_base, get_default_base, list_bases

log = logging.getLogger(__name__)

NODE_TYPES = frozenset({"group", "node"})
DEFAULT_KB_NAME = "Knowledge Base"

_WORD_RE = re.compile(
    r"[a-z0-9àáạảãâầấậẫăằắặẵèéẹẻẽêềếệểìíịỉĩòóọỏõôồốộổơờớợỡùúụủũưừứựừừửữđ]+",
    re.I,
)
_MAX_HIT_CONTENT = 12_000
_MAX_SEARCH_LIMIT = 24


def _tokenize(query: str) -> list[str]:
    q = str(query or "").strip().lower()
    return [t for t in _WORD_RE.findall(q) if len(t) >= 2]


def _norm_parent(parent_id: Any) -> str | None:
    if parent_id is None:
        return None
    s = str(parent_id).strip()
    if not s or s in ("0", "null", "None"):
        return None
    return s


def _doc_tags(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("tags")
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    if isinstance(raw, str) and raw.strip():
        return [t.strip() for t in re.split(r"[,;|]", raw) if t.strip()]
    return []


def ensure_user_knowledge_base(user_id: int, *, role: str = "user") -> dict[str, Any]:
    uid = int(user_id)
    existing = get_default_base(user_id=uid, role=role)
    if existing and str(existing.get("scope") or "user") == "user":
        return existing
    return create_base(
        {
            "name": DEFAULT_KB_NAME,
            "scope": "user",
            "is_default": True,
            "enabled": True,
            "language": "vi",
            "tone": "professional",
        },
        user_id=uid,
        role=role,
    )


def user_kb_id(user_id: int, *, role: str = "user") -> str:
    return str(ensure_user_knowledge_base(user_id, role=role).get("id") or "")


def list_consumer_kb_groups(user_id: int, *, role: str = "user") -> tuple[list[str], list[str]]:
    """KB ids Chatbot + Content AI may read: own enabled user KBs, then inherited global."""
    uid = int(user_id)
    own: list[str] = []
    inherited: list[str] = []
    for b in list_bases(user_id=uid, role=role):
        if not b.get("enabled", True):
            continue
        kid = str(b.get("id") or "").strip()
        if not kid:
            continue
        scope = str(b.get("scope") or "user")
        if b.get("is_inherited") or scope == "global":
            inherited.append(kid)
            continue
        if scope != "user":
            continue
        owner = b.get("owner_user_id")
        if owner is not None:
            try:
                if int(owner) != uid:
                    continue
            except (TypeError, ValueError):
                pass
        own.append(kid)
    return list(dict.fromkeys(own)), list(dict.fromkeys(inherited))


def list_consumer_kb_ids(user_id: int, *, role: str = "user") -> list[str]:
    own, inherited = list_consumer_kb_groups(user_id, role=role)
    return list(dict.fromkeys(own + inherited))


def _all_docs(kb_id: str) -> list[dict[str, Any]]:
    docs = _read_store(kb_id).get("documents") or []
    return [d for d in docs if isinstance(d, dict)]


def get_raw_document(kb_id: str, doc_id: str) -> dict[str, Any] | None:
    want = str(doc_id or "").strip()
    if not want:
        return None
    for d in _all_docs(kb_id):
        if str(d.get("id") or "") == want:
            return d
    return None


def resolve_node_document(kb_id: str, user_id: int, node_id: Any) -> dict[str, Any] | None:
    nid = str(node_id or "").strip()
    if not nid:
        return None
    found = get_raw_document(kb_id, nid)
    if found:
        return found
    for key in (
        f"cskh_node:{int(user_id)}:{nid}",
        f"cskh_src:{int(user_id)}:{nid}",
    ):
        found = find_document_by_source_key(kb_id, key)
        if found:
            return found
    return None


def document_to_node(doc: dict[str, Any]) -> dict[str, Any]:
    full = _document_full_text(doc)
    node_type = str(doc.get("node_type") or "node").strip().lower()
    if node_type not in NODE_TYPES:
        node_type = "node"
    is_active = doc.get("is_active")
    if is_active is None:
        is_active = True
    return {
        "id": str(doc.get("id") or ""),
        "map_id": str(doc.get("kb_id") or ""),
        "parent_id": _norm_parent(doc.get("parent_id")),
        "node_type": node_type,
        "title": str(doc.get("title") or doc.get("filename") or "Tài liệu"),
        "content": full,
        "tags": _doc_tags(doc),
        "priority": int(doc.get("priority") or 0),
        "is_active": bool(is_active),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at") or doc.get("created_at"),
        "source_key": str(doc.get("source_key") or ""),
    }


def list_user_nodes(user_id: int, *, role: str = "user") -> list[dict[str, Any]]:
    kid = user_kb_id(user_id, role=role)
    nodes = [document_to_node(d) for d in _all_docs(kid)]
    nodes.sort(key=lambda n: (-int(n.get("priority") or 0), str(n.get("title") or "").lower()))
    return nodes


def _edges_from_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for n in nodes:
        pid = _norm_parent(n.get("parent_id"))
        nid = str(n.get("id") or "")
        if not pid or not nid:
            continue
        edges.append(
            {
                "id": f"{pid}:{nid}",
                "source_node_id": pid,
                "target_node_id": nid,
                "relation_type": "child",
            }
        )
    return edges


def _sync_meta(nodes: list[dict[str, Any]], *, bot_id: int, kb_id: str) -> dict[str, Any]:
    active = [n for n in nodes if n.get("is_active") and n.get("node_type") != "group"]
    status = "synced" if active else "empty"
    latest = ""
    for n in nodes:
        ts = str(n.get("updated_at") or "")
        if ts > latest:
            latest = ts
    return {
        "sync_status": status,
        "synced_at": latest or None,
        "cache_version": latest or kb_id,
        "kb_id": kb_id,
        "bot_id": int(bot_id),
    }


def get_shared_kb_payload(user_id: int, bot_id: int, *, role: str = "user") -> dict[str, Any]:
    kb = ensure_user_knowledge_base(user_id, role=role)
    kid = str(kb.get("id") or "")
    nodes = list_user_nodes(user_id, role=role)
    edges = _edges_from_nodes(nodes)
    meta = _sync_meta(nodes, bot_id=int(bot_id), kb_id=kid)
    kb_map = {
        "id": kid,
        "bot_id": int(bot_id),
        "title": str(kb.get("name") or DEFAULT_KB_NAME),
        "status": "active" if nodes else "draft",
        "created_at": kb.get("created_at"),
        "updated_at": kb.get("updated_at"),
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "active_node_count": sum(1 for n in nodes if n.get("is_active")),
    }
    return {
        "map": kb_map,
        "bot_id": int(bot_id),
        "kb_id": kid,
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "active_node_count": kb_map["active_node_count"],
        **meta,
    }


def upsert_document(
    user_id: int,
    *,
    title: str,
    content: str,
    source_key: str | None = None,
    doc_id: str | None = None,
    node_type: str = "node",
    parent_id: Any = None,
    tags: list[str] | None = None,
    priority: int = 0,
    is_active: bool = True,
    role: str = "user",
) -> dict[str, Any]:
    kid = user_kb_id(user_id, role=role)
    title_clean = str(title or "").strip()[:200]
    if not title_clean:
        raise ValueError("Tiêu đề node bắt buộc.")
    body = str(content or "").strip()[:100_000]
    if not body:
        body = title_clean
    nt = str(node_type or "node").strip().lower()
    if nt not in NODE_TYPES:
        nt = "node"
    parent = _norm_parent(parent_id)
    extra = {
        "source_key": str(source_key or "").strip(),
        "node_type": nt,
        "parent_id": parent,
        "tags": [str(t).strip().lower() for t in (tags or []) if str(t).strip()],
        "priority": int(priority or 0),
        "is_active": bool(is_active),
        "owner_user_id": int(user_id),
    }
    existing = None
    if doc_id:
        existing = get_raw_document(kid, str(doc_id))
    if existing is None and extra["source_key"]:
        existing = find_document_by_source_key(kid, extra["source_key"])
    if existing:
        updated = update_document(
            kid,
            str(existing.get("id")),
            title=title_clean,
            content=body,
            extra=extra,
            embed=True,
        )
        if updated is None:
            raise ValueError("Không cập nhật được tài liệu Knowledge Base.")
        return document_to_node(updated)

    docs = _all_docs(kid)
    if len(docs) >= MAX_DOCS_PER_KB:
        raise ValueError(f"Tối đa {MAX_DOCS_PER_KB} tài liệu mỗi knowledge base.")
    added = import_text(kid, title_clean, body, embed=True, extra=extra)
    doc = added.get("document") if isinstance(added, dict) else None
    if not isinstance(doc, dict):
        raise ValueError("Không tạo được tài liệu Knowledge Base.")
    return document_to_node(doc)


def create_node(
    user_id: int,
    *,
    title: str,
    content: str = "",
    node_type: str = "node",
    parent_id: Any = None,
    tags: list[str] | None = None,
    priority: int = 0,
    is_active: bool = True,
    role: str = "user",
) -> dict[str, Any]:
    kid = user_kb_id(user_id, role=role)
    parent = _norm_parent(parent_id)
    if parent and not get_raw_document(kid, parent):
        raise ValueError("Node cha không thuộc sơ đồ này.")
    return upsert_document(
        user_id,
        title=title,
        content=content,
        node_type=node_type,
        parent_id=parent,
        tags=tags,
        priority=priority,
        is_active=is_active,
        role=role,
    )


def update_node(
    user_id: int,
    node_id: Any,
    *,
    title: str | None = None,
    content: str | None = None,
    node_type: str | None = None,
    parent_id: Any = None,
    parent_id_set: bool = False,
    tags: list[str] | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
    role: str = "user",
) -> dict[str, Any]:
    kid = user_kb_id(user_id, role=role)
    doc = resolve_node_document(kid, user_id, node_id)
    if doc is None:
        raise KeyError("Không tìm thấy node kiến thức.")
    extra: dict[str, Any] = {}
    if node_type is not None:
        nt = str(node_type).strip().lower()
        if nt not in NODE_TYPES:
            raise ValueError("node_type không hợp lệ.")
        extra["node_type"] = nt
    if parent_id_set:
        parent = _norm_parent(parent_id)
        if parent and parent == str(doc.get("id")):
            raise ValueError("Node không thể là cha của chính nó.")
        if parent and not get_raw_document(kid, parent):
            raise ValueError("Node cha không thuộc sơ đồ này.")
        extra["parent_id"] = parent
    if tags is not None:
        extra["tags"] = [str(t).strip().lower() for t in tags if str(t).strip()]
    if priority is not None:
        extra["priority"] = int(priority)
    if is_active is not None:
        extra["is_active"] = bool(is_active)
    updated = update_document(
        kid,
        str(doc.get("id")),
        title=title,
        content=content,
        extra=extra or None,
        embed=content is not None,
    )
    if updated is None:
        raise KeyError("Không tìm thấy node kiến thức.")
    return document_to_node(updated)


def delete_node(user_id: int, node_id: Any, *, role: str = "user") -> None:
    kid = user_kb_id(user_id, role=role)
    doc = resolve_node_document(kid, user_id, node_id)
    if doc is None:
        raise KeyError("Không tìm thấy node kiến thức.")
    victim = str(doc.get("id") or "")
    parent = _norm_parent(doc.get("parent_id"))
    for child in _all_docs(kid):
        if _norm_parent(child.get("parent_id")) == victim:
            update_document(
                kid,
                str(child.get("id")),
                extra={"parent_id": parent},
                embed=False,
            )
    delete_document(kid, victim)


def toggle_node(user_id: int, node_id: Any, *, role: str = "user") -> dict[str, Any]:
    kid = user_kb_id(user_id, role=role)
    doc = resolve_node_document(kid, user_id, node_id)
    if doc is None:
        raise KeyError("Không tìm thấy node kiến thức.")
    nxt = not bool(doc.get("is_active", True))
    updated = update_document(kid, str(doc.get("id")), extra={"is_active": nxt}, embed=False)
    if updated is None:
        raise KeyError("Không tìm thấy node kiến thức.")
    return document_to_node(updated)


def import_items(
    user_id: int,
    *,
    items: list[dict[str, Any]],
    parent_id: Any = None,
    on_duplicate: str = "update",
    role: str = "user",
) -> dict[str, Any]:
    kid = user_kb_id(user_id, role=role)
    mode = str(on_duplicate or "update").strip().lower()
    if mode not in ("update", "skip", "rename"):
        mode = "update"
    existing_by_title: dict[str, dict[str, Any]] = {}
    for d in _all_docs(kid):
        key = str(d.get("title") or "").strip().lower()
        if key and key not in existing_by_title:
            existing_by_title[key] = d
    seen: set[str] = set()
    imported = updated = skipped = skipped_empty = skipped_dup = 0
    parent = _norm_parent(parent_id)

    for item in items:
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not title or not content or len(content) < 2:
            skipped += 1
            skipped_empty += 1
            continue
        title_key = title.lower()
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,;|]", tags) if t.strip()]
        source_key = str(item.get("source_key") or "").strip() or None
        existing = None
        if source_key:
            existing = find_document_by_source_key(kid, source_key)
        if existing is None:
            existing = existing_by_title.get(title_key)
        if existing is not None or title_key in seen:
            if mode == "skip":
                skipped += 1
                skipped_dup += 1
                continue
            if mode == "rename":
                n = 2
                new_title = f"{title} ({n})"
                while new_title.lower() in existing_by_title or new_title.lower() in seen:
                    n += 1
                    new_title = f"{title} ({n})"
                title = new_title
                title_key = title.lower()
                existing = None
            elif existing is not None:
                upsert_document(
                    user_id,
                    title=title,
                    content=content,
                    source_key=source_key or str(existing.get("source_key") or "") or None,
                    doc_id=str(existing.get("id") or "") or None,
                    node_type=str(item.get("node_type") or existing.get("node_type") or "node"),
                    parent_id=parent if parent is not None else existing.get("parent_id"),
                    tags=list(tags) if tags else _doc_tags(existing),
                    priority=int(item.get("priority") or existing.get("priority") or 0),
                    is_active=bool(item.get("is_active", existing.get("is_active", True))),
                    role=role,
                )
                updated += 1
                seen.add(title_key)
                continue
            else:
                skipped += 1
                skipped_dup += 1
                continue
        node = upsert_document(
            user_id,
            title=title,
            content=content,
            source_key=source_key,
            node_type=str(item.get("node_type") or "node"),
            parent_id=parent,
            tags=list(tags) if tags else None,
            priority=int(item.get("priority") or 0),
            is_active=bool(item.get("is_active", True)),
            role=role,
        )
        existing_by_title[title_key] = {"title": node.get("title"), "id": node.get("id")}
        seen.add(title_key)
        imported += 1

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "skipped_empty": skipped_empty,
        "skipped_duplicate": skipped_dup,
        "map_id": kid,
        "kb_id": kid,
    }


_QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "đào": ("tạo", "học", "khóa"),
    "tạo": ("đào", "học", "khóa"),
    "học": ("đào", "tạo", "khóa"),
    "khóa": ("đào", "tạo", "học", "khoa"),
    "khoa": ("khóa",),
    "seo": ("search", "tối ưu"),
    "dịch": ("vụ", "service"),
    "vụ": ("dịch", "service"),
}


def _expand_query_tokens(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    seen = set(tokens)
    for t in tokens:
        for alt in _QUERY_SYNONYMS.get(t, ()):
            if alt not in seen:
                expanded.append(alt)
                seen.add(alt)
    return expanded


def _query_phrases(tokens: list[str]) -> list[str]:
    phrases: list[str] = []
    for n in (2, 3):
        for i in range(len(tokens) - n + 1):
            phrases.append(" ".join(tokens[i : i + n]))
    return phrases


def _score_text_block(title: str, text: str, query: str, tokens: list[str]) -> int:
    hay = f"{title}\n{text}".lower()
    q = str(query or "").strip().lower()
    if not hay.strip():
        return 0
    score = 0
    if q and q in hay:
        score += 8 + min(12, hay.count(q))
    title_l = (title or "").lower()
    expanded = _expand_query_tokens(tokens)
    for t in expanded:
        if t in hay:
            score += 1 + min(4, hay.count(t))
        if t and t in title_l:
            score += 2
    for phrase in _query_phrases(tokens):
        if phrase in hay:
            score += 3 + min(6, hay.count(phrase))
    # Service-intent bonus for multi-word service queries.
    service_hints = ("đào tạo", "khóa học", "dịch vụ", "khoa hoc", "dao tao")
    if any(h in q for h in service_hints):
        for hint in service_hints:
            if hint in hay:
                score += 4
    return score


def _score_document(title: str, full: str, query: str, tokens: list[str]) -> int:
    return _score_text_block(title, full, query, tokens)


def _content_for_hit(full: str, query: str, *, max_chars: int = _MAX_HIT_CONTENT) -> str:
    text = str(full or "")
    if len(text) <= max_chars:
        return text
    q = str(query or "").strip()
    if q:
        idx = text.lower().find(q.lower())
        if idx >= 0:
            start = max(0, idx - max_chars // 4)
            return text[start : start + max_chars]
    return text[:max_chars]


def search_user_knowledge(
    user_id: int,
    query: str,
    *,
    limit: int = 12,
    role: str = "user",
    include_unmatched_fallback: bool = True,
) -> list[dict[str, Any]]:
    tokens = _tokenize(query)
    q = str(query or "").strip().lower()
    if not q and not tokens:
        return []
    own_ids, _inherited_ids = list_consumer_kb_groups(user_id, role=role)
    kb_ids = list(own_ids)
    if not kb_ids:
        kid = user_kb_id(user_id, role=role)
        kb_ids = [kid] if kid else []
    seen: set[str] = set()
    hits: list[dict[str, Any]] = []
    fallback: list[tuple[int, dict[str, Any]]] = []
    for kid in kb_ids:
        for doc in _all_docs(kid):
            if doc.get("is_active") is False:
                continue
            if str(doc.get("node_type") or "node") == "group":
                continue
            did = str(doc.get("id") or "")
            skey = str(doc.get("source_key") or "").strip()
            uniq = skey or f"{kid}:{did}"
            if uniq in seen:
                continue
            seen.add(uniq)
            title = str(doc.get("title") or doc.get("filename") or "")
            full = _document_full_text(doc)
            if not f"{title}\n{full}".strip():
                continue
            score = _score_document(title, full, q, tokens)
            item = {
                "id": did,
                "title": title,
                "content": _content_for_hit(full, q),
                "score": score,
                "source": "ai_kb",
                "tags": _doc_tags(doc),
                "source_type": "knowledge",
                "kb_id": kid,
            }
            if score > 0:
                hits.append(item)
            else:
                fallback.append((int(doc.get("priority") or 0), item))
    if not hits and include_unmatched_fallback and fallback:
        fallback.sort(key=lambda x: -x[0])
        cap = max(1, min(int(limit or 12), 8))
        hits = [row for _, row in fallback[:cap]]
    hits.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("title") or "")))
    return hits[: max(1, min(int(limit or 12), _MAX_SEARCH_LIMIT))]


def _semantic_rerank_chunks(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int = 12,
) -> list[dict[str, Any]]:
    """Rerank lexical chunk hits with dense embeddings when available."""
    if not candidates or not str(query or "").strip():
        return candidates
    try:
        import numpy as np

        from app.services.semantic_embedding import embed_keywords

        texts = [str(query or "").strip()]
        for c in candidates[:40]:
            texts.append(str(c.get("content") or "")[:2000])
        emb = embed_keywords(texts, use_cache=True)
        qv = emb.get(str(query or "").strip())
        if qv is None:
            return candidates
        scored: list[tuple[float, dict[str, Any]]] = []
        for i, c in enumerate(candidates[:40]):
            text = texts[i + 1]
            cv = emb.get(text)
            sem = float(np.dot(qv, cv)) if cv is not None else 0.0
            lex = int(c.get("score") or 0)
            combined = lex + sem * 12.0
            row = dict(c)
            row["score"] = int(combined)
            row["semantic_score"] = round(sem, 4)
            scored.append((combined, row))
        scored.sort(key=lambda x: -x[0])
        return [row for _, row in scored[:top_k]]
    except Exception as exc:
        log.debug("KB semantic rerank skipped: %s", exc)
        return candidates


def search_user_knowledge_chunks(
    user_id: int,
    query: str,
    *,
    limit: int = 12,
    role: str = "user",
    semantic: bool = True,
) -> list[dict[str, Any]]:
    """Chunk-level KB search — better for long website/KB documents."""
    tokens = _tokenize(query)
    q = str(query or "").strip().lower()
    if not q and not tokens:
        return []
    own_ids, _inherited_ids = list_consumer_kb_groups(user_id, role=role)
    kb_ids = list(own_ids)
    if not kb_ids:
        kid = user_kb_id(user_id, role=role)
        kb_ids = [kid] if kid else []
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kid in kb_ids:
        for doc in _all_docs(kid):
            if doc.get("is_active") is False:
                continue
            if str(doc.get("node_type") or "node") == "group":
                continue
            did = str(doc.get("id") or "")
            title = str(doc.get("title") or doc.get("filename") or "")
            chunks = doc.get("chunks") or []
            if chunks:
                for ch in chunks:
                    if not isinstance(ch, dict):
                        continue
                    text = str(ch.get("text") or "").strip()
                    if not text:
                        continue
                    score = _score_text_block(title, text, q, tokens)
                    if score <= 0:
                        continue
                    key = f"{did}:{ch.get('index', 0)}"
                    if key in seen:
                        continue
                    seen.add(key)
                    hits.append(
                        {
                            "id": did,
                            "node_id": did,
                            "title": title,
                            "content": _content_for_hit(text, q),
                            "score": score,
                            "source": "ai_kb_chunk",
                            "tags": _doc_tags(doc),
                            "source_type": "knowledge",
                            "kb_id": kid,
                            "chunk_index": ch.get("index"),
                        }
                    )
            else:
                full = _document_full_text(doc)
                score = _score_document(title, full, q, tokens)
                if score <= 0:
                    continue
                key = f"{did}:doc"
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    {
                        "id": did,
                        "node_id": did,
                        "title": title,
                        "content": _content_for_hit(full, q),
                        "score": score,
                        "source": "ai_kb",
                        "tags": _doc_tags(doc),
                        "source_type": "knowledge",
                        "kb_id": kid,
                    }
                )
    hits.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("title") or "")))
    top = hits[: max(1, min(int(limit or 12) * 2, _MAX_SEARCH_LIMIT))]
    if semantic and top:
        top = _semantic_rerank_chunks(q, top, top_k=max(1, int(limit or 12)))
    return top[: max(1, min(int(limit or 12), _MAX_SEARCH_LIMIT))]


def sync_source_to_kb(
    user_id: int,
    *,
    source_id: int,
    title: str,
    content: str,
    source_type: str = "faq",
    role: str = "user",
) -> dict[str, Any] | None:
    body = str(content or "").strip()
    if len(body) < 2:
        return None
    tag = {"faq": "faq", "business": "dịch vụ", "website": "dịch vụ"}.get(
        str(source_type or "").lower(), "faq"
    )
    return upsert_document(
        user_id,
        title=str(title or "Nguồn dữ liệu").strip()[:200] or "Nguồn dữ liệu",
        content=body,
        source_key=f"cskh_src:{int(user_id)}:{int(source_id)}",
        node_type="node",
        tags=[tag],
        is_active=True,
        role=role,
    )


def _legacy_node_key(user_id: int, node_id: int) -> str:
    return f"cskh_node:{int(user_id)}:{int(node_id)}"


def migrate_legacy_chatbot_kb(db: Session, user_id: int, *, role: str = "user") -> dict[str, int]:
    """Copy ChatbotKbNode + ChatbotKnowledgeSource into the shared AI KB.

    Idempotent: existing source_key rows are skipped. SQL rows are not deleted.
    """
    from app.models.chatbot_cskh import ChatbotKnowledgeSource
    from app.models.chatbot_cskh_kb import ChatbotKbMap, ChatbotKbNode

    uid = int(user_id)
    kid = user_kb_id(uid, role=role)
    existing_keys = {str(d.get("source_key") or "") for d in _all_docs(kid) if d.get("source_key")}
    existing_titles = {
        str(d.get("title") or "").strip().lower()
        for d in _all_docs(kid)
        if str(d.get("title") or "").strip()
    }
    nodes_in = 0
    sources_in = 0
    skipped = 0

    maps = db.execute(
        select(ChatbotKbMap).where(ChatbotKbMap.user_id == uid)
    ).scalars().all()
    map_ids = [m.id for m in maps]
    old_to_new: dict[int, str] = {}
    pending_parent: list[tuple[str, int | None]] = []

    if map_ids:
        rows = db.execute(
            select(ChatbotKbNode)
            .where(ChatbotKbNode.map_id.in_(map_ids))
            .order_by(ChatbotKbNode.id.asc())
        ).scalars().all()
        for row in rows:
            key = _legacy_node_key(uid, int(row.id))
            found = find_document_by_source_key(kid, key)
            if found:
                old_to_new[int(row.id)] = str(found.get("id"))
                skipped += 1
                continue
            title = str(row.title or "").strip()
            content = str(row.content or "").strip()
            if not title:
                skipped += 1
                continue
            title_key = title.lower()
            if title_key in existing_titles and not content:
                skipped += 1
                continue
            if len(_all_docs(kid)) >= MAX_DOCS_PER_KB:
                log.warning("shared_kb migrate skipped remaining nodes: KB full user=%s", uid)
                break
            tags_raw = row.tags
            tags: list[str] = []
            if isinstance(tags_raw, str) and tags_raw.strip():
                try:
                    import json

                    parsed = json.loads(tags_raw)
                    if isinstance(parsed, list):
                        tags = [str(x).strip() for x in parsed if str(x).strip()]
                except Exception:
                    tags = [t.strip() for t in re.split(r"[,;|]", tags_raw) if t.strip()]
            node = upsert_document(
                uid,
                title=title,
                content=content or title,
                source_key=key,
                node_type=str(row.node_type or "node"),
                parent_id=None,
                tags=tags,
                priority=int(row.priority or 0),
                is_active=bool(row.is_active),
                role=role,
            )
            old_to_new[int(row.id)] = str(node.get("id"))
            pending_parent.append((str(node.get("id")), int(row.parent_id) if row.parent_id else None))
            existing_titles.add(title_key)
            existing_keys.add(key)
            nodes_in += 1

        for doc_id, old_parent in pending_parent:
            if not old_parent:
                continue
            new_parent = old_to_new.get(int(old_parent))
            if not new_parent:
                continue
            update_document(kid, doc_id, extra={"parent_id": new_parent}, embed=False)

    sources = db.execute(
        select(ChatbotKnowledgeSource).where(
            ChatbotKnowledgeSource.user_id == uid,
            ChatbotKnowledgeSource.status.in_(("ready", "active")),
        )
    ).scalars().all()
    for src in sources:
        key = f"cskh_src:{uid}:{int(src.id)}"
        if key in existing_keys or find_document_by_source_key(kid, key):
            skipped += 1
            continue
        title = str(src.title or "").strip()
        content = str(src.content or "").strip()
        if not title or not content:
            skipped += 1
            continue
        if title.lower() in existing_titles:
            skipped += 1
            continue
        if len(_all_docs(kid)) >= MAX_DOCS_PER_KB:
            log.warning("shared_kb migrate skipped remaining sources: KB full user=%s", uid)
            break
        try:
            sync_source_to_kb(
                uid,
                source_id=int(src.id),
                title=title,
                content=content,
                source_type=str(src.source_type or "faq"),
                role=role,
            )
            existing_titles.add(title.lower())
            existing_keys.add(key)
            sources_in += 1
        except ValueError:
            skipped += 1

    if nodes_in or sources_in:
        log.info(
            "shared_kb migrate user=%s nodes=%s sources=%s skipped=%s",
            uid,
            nodes_in,
            sources_in,
            skipped,
        )
    return {"nodes": nodes_in, "sources": sources_in, "skipped": skipped}
