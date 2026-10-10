"""Shared chatbot KB service — single source of truth (DB, per user_id + bot_id)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotBot, ChatbotKnowledgeSource
from app.models.chatbot_cskh_kb import ChatbotKbEdge, ChatbotKbMap, ChatbotKbNode
from app.services.chatbot_kb_cache import (
    get_bot_kb_version,
    get_cached_search,
    invalidate_bot_kb_cache,
    make_search_key,
    set_cached_search,
)
from app.services import shared_knowledge as shared_kb

MAP_STATUSES = frozenset({"draft", "active", "disabled"})
NODE_TYPES = frozenset({"group", "node"})
RELATION_TYPES = frozenset({"child", "related", "see_also"})
KB_TAGS = frozenset({"dịch vụ", "bảng giá", "chính sách", "faq", "bảo hành", "liên hệ"})

_SOURCE_TAG_MAP = {
    "faq": "faq",
    "business": "dịch vụ",
    "website": "dịch vụ",
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _tokenize(query: str) -> list[str]:
    return [t for t in re.split(r"\s+", str(query or "").strip().lower()) if len(t) >= 2]


def _parse_tags(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = [str(x).strip().lower() for x in parsed if str(x).strip()]
                else:
                    items = [text.lower()]
            except json.JSONDecodeError:
                items = [p.strip().lower() for p in re.split(r"[,;|]", text) if p.strip()]
        else:
            items = [p.strip().lower() for p in re.split(r"[,;|]", text) if p.strip()]
    return [t for t in items if t]


def _tags_to_storage(tags: list[str]) -> str:
    clean = [t for t in tags if t]
    return json.dumps(clean, ensure_ascii=False) if clean else ""


def _get_user_bot(db: Session, user_id: int, bot_id: int) -> ChatbotBot:
    row = db.execute(
        select(ChatbotBot).where(ChatbotBot.id == int(bot_id), ChatbotBot.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chatbot.")
    return row


def _get_user_map_for_bot(db: Session, user_id: int, bot_id: int) -> ChatbotKbMap | None:
    return db.execute(
        select(ChatbotKbMap)
        .where(ChatbotKbMap.user_id == int(user_id), ChatbotKbMap.bot_id == int(bot_id))
        .order_by(ChatbotKbMap.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_or_create_map(db: Session, user_id: int, bot_id: int, *, title: str = "") -> ChatbotKbMap:
    _get_user_bot(db, user_id, bot_id)
    row = _get_user_map_for_bot(db, user_id, bot_id)
    if row is not None:
        return row
    row = ChatbotKbMap(
        user_id=int(user_id),
        bot_id=int(bot_id),
        title=(title or "Sơ đồ tri thức").strip()[:160],
        status="draft",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_user_node(db: Session, user_id: int, node_id: int) -> ChatbotKbNode:
    row = db.execute(
        select(ChatbotKbNode)
        .join(ChatbotKbMap, ChatbotKbMap.id == ChatbotKbNode.map_id)
        .where(ChatbotKbNode.id == int(node_id), ChatbotKbMap.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy node kiến thức.")
    return row


def _node_to_dict(row: ChatbotKbNode) -> dict[str, Any]:
    tags = _parse_tags(row.tags)
    return {
        "id": row.id,
        "map_id": row.map_id,
        "parent_id": row.parent_id,
        "node_type": row.node_type,
        "title": row.title,
        "content": row.content or "",
        "tags": tags,
        "priority": int(row.priority or 0),
        "is_active": bool(row.is_active),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at or row.created_at),
    }


def _edge_to_dict(row: ChatbotKbEdge) -> dict[str, Any]:
    return {
        "id": row.id,
        "map_id": row.map_id,
        "source_node_id": row.source_node_id,
        "target_node_id": row.target_node_id,
        "relation_type": row.relation_type,
    }


def _map_to_dict(row: ChatbotKbMap, *, nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    return {
        "id": row.id,
        "bot_id": row.bot_id,
        "title": row.title,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at or row.created_at),
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "active_node_count": sum(1 for n in nodes if n.get("is_active")),
    }


def _sync_meta(
    kb_map: ChatbotKbMap | None,
    nodes: list[dict[str, Any]],
    *,
    bot_id: int,
    error: bool = False,
) -> dict[str, Any]:
    if error:
        status = "error"
    elif not nodes or not any(n.get("is_active") for n in nodes if n.get("node_type") != "group"):
        status = "empty"
    elif kb_map is not None and str(kb_map.status or "").lower() == "disabled":
        status = "empty"
    else:
        status = "synced"
    return {
        "sync_status": status,
        "synced_at": _iso(kb_map.updated_at if kb_map else None),
        "cache_version": get_bot_kb_version(bot_id),
    }


def _touch_kb_cache(bot_id: int) -> None:
    if int(bot_id or 0) <= 0:
        from app.services.chatbot_kb_cache import _bot_versions, _lock, _search_cache

        with _lock:
            _search_cache.clear()
            for k in list(_bot_versions):
                _bot_versions[k] = int(_bot_versions.get(k, 0)) + 1
        return
    invalidate_bot_kb_cache(int(bot_id))


def get_kb_for_bot(db: Session, user_id: int, bot_id: int) -> dict[str, Any]:
    _get_user_bot(db, user_id, bot_id)
    shared_kb.migrate_legacy_chatbot_kb(db, user_id)
    return shared_kb.get_shared_kb_payload(user_id, int(bot_id))


def _ensure_parent_in_map(db: Session, map_id: int, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = db.execute(
        select(ChatbotKbNode).where(
            ChatbotKbNode.id == int(parent_id),
            ChatbotKbNode.map_id == int(map_id),
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Node cha không thuộc sơ đồ này.")


def _sync_parent_edge(db: Session, kb_map: ChatbotKbMap, node: ChatbotKbNode) -> None:
    existing = db.execute(
        select(ChatbotKbEdge).where(
            ChatbotKbEdge.map_id == kb_map.id,
            ChatbotKbEdge.target_node_id == node.id,
            ChatbotKbEdge.relation_type == "child",
        )
    ).scalar_one_or_none()
    if node.parent_id:
        if existing:
            if existing.source_node_id != node.parent_id:
                existing.source_node_id = node.parent_id
        else:
            db.add(
                ChatbotKbEdge(
                    map_id=kb_map.id,
                    source_node_id=int(node.parent_id),
                    target_node_id=node.id,
                    relation_type="child",
                )
            )
    elif existing:
        db.delete(existing)


def _refresh_map_status(db: Session, kb_map: ChatbotKbMap) -> None:
    active_count = db.execute(
        select(ChatbotKbNode).where(
            ChatbotKbNode.map_id == kb_map.id,
            ChatbotKbNode.is_active.is_(True),
            ChatbotKbNode.node_type == "node",
        )
    ).scalars().all()
    if active_count:
        if kb_map.status == "draft":
            kb_map.status = "active"
    else:
        if kb_map.status == "active":
            kb_map.status = "draft"


def create_kb_node(
    db: Session,
    user_id: int,
    bot_id: int,
    *,
    title: str,
    content: str = "",
    node_type: str = "node",
    parent_id: int | str | None = None,
    tags: list[str] | None = None,
    priority: int = 0,
    is_active: bool = True,
    target_node_id: int | str | None = None,
    relation_type: str = "child",
) -> dict[str, Any]:
    _get_user_bot(db, user_id, bot_id)
    shared_kb.migrate_legacy_chatbot_kb(db, user_id)
    try:
        node = shared_kb.create_node(
            user_id,
            title=title,
            content=content,
            node_type=node_type,
            parent_id=parent_id,
            tags=tags,
            priority=priority,
            is_active=is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _touch_kb_cache(int(bot_id))
    return node


def update_kb_node(
    db: Session,
    user_id: int,
    node_id: int | str,
    *,
    title: str | None = None,
    content: str | None = None,
    node_type: str | None = None,
    parent_id: int | str | None = None,
    parent_id_set: bool = False,
    tags: list[str] | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    try:
        node = shared_kb.update_node(
            user_id,
            node_id,
            title=title,
            content=content,
            node_type=node_type,
            parent_id=parent_id,
            parent_id_set=parent_id_set,
            tags=tags,
            priority=priority,
            is_active=is_active,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _touch_kb_cache(0)
    return node


def delete_kb_node(db: Session, user_id: int, node_id: int | str) -> None:
    try:
        shared_kb.delete_node(user_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _touch_kb_cache(0)


def toggle_kb_node(db: Session, user_id: int, node_id: int | str) -> dict[str, Any]:
    try:
        node = shared_kb.toggle_node(user_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _touch_kb_cache(0)
    return node


def import_kb_from_sources(
    db: Session,
    user_id: int,
    bot_id: int,
    *,
    source_ids: list[int] | None = None,
    parent_id: int | None = None,
) -> dict[str, Any]:
    _get_user_bot(db, user_id, bot_id)
    q = select(ChatbotKnowledgeSource).where(
        ChatbotKnowledgeSource.user_id == int(user_id),
        ChatbotKnowledgeSource.bot_id == int(bot_id),
        ChatbotKnowledgeSource.status.in_(("ready", "active")),
    )
    if source_ids:
        q = q.where(ChatbotKnowledgeSource.id.in_([int(x) for x in source_ids]))
    sources = db.execute(q.order_by(ChatbotKnowledgeSource.id.asc())).scalars().all()
    items: list[dict[str, Any]] = []
    for src in sources:
        content = (src.content or "").strip()
        title = (src.title or "Nguồn dữ liệu").strip()
        if not content:
            continue
        tag = _SOURCE_TAG_MAP.get(str(src.source_type or "").lower(), "faq")
        items.append(
            {
                "title": title[:200],
                "content": content[:100_000],
                "tags": [tag],
                "source_key": f"cskh_src:{int(user_id)}:{int(src.id)}",
            }
        )
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không có nguồn dữ liệu hợp lệ để import.",
        )
    return import_kb_items(
        db,
        user_id,
        bot_id,
        items=items,
        parent_id=parent_id,
        on_duplicate="update",
    )


def list_import_sources(db: Session, user_id: int, bot_id: int) -> list[dict[str, Any]]:
    _get_user_bot(db, user_id, bot_id)
    shared_kb.migrate_legacy_chatbot_kb(db, user_id)
    nodes = shared_kb.list_user_nodes(user_id)
    existing_titles = {n["title"].strip().lower() for n in nodes if n.get("title")}
    existing_keys = {str(n.get("source_key") or "") for n in nodes}
    rows = db.execute(
        select(ChatbotKnowledgeSource)
        .where(
            ChatbotKnowledgeSource.user_id == int(user_id),
            ChatbotKnowledgeSource.bot_id == int(bot_id),
            ChatbotKnowledgeSource.status.in_(("ready", "active")),
        )
        .order_by(ChatbotKnowledgeSource.updated_at.desc(), ChatbotKnowledgeSource.id.desc())
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        content = (row.content or "").strip()
        title_key = (row.title or "").strip().lower()
        src_key = f"cskh_src:{int(user_id)}:{int(row.id)}"
        out.append(
            {
                "source_id": row.id,
                "title": row.title,
                "source_type": row.source_type,
                "content_preview": content[:200],
                "has_content": bool(content),
                "already_imported": src_key in existing_keys or (title_key in existing_titles if title_key else False),
            }
        )
    return out


def _parse_csv_rows(text: str) -> list[dict[str, Any]]:
    import csv
    import io

    raw = str(text or "").strip()
    if not raw:
        return []
    reader = csv.DictReader(io.StringIO(raw))
    items: list[dict[str, Any]] = []
    for row in reader:
        title = str(row.get("title") or row.get("tiêu đề") or row.get("tieu_de") or "").strip()
        content = str(row.get("content") or row.get("nội dung") or row.get("noi_dung") or "").strip()
        tags_raw = str(row.get("tags") or row.get("tag") or "").strip()
        tags = _parse_tags(tags_raw) if tags_raw else []
        if title and content:
            items.append({"title": title, "content": content, "tags": tags})
    return items


def _title_from_filename(filename: str) -> str:
    name = str(filename or "").strip()
    if not name:
        return ""
    # Drop path and extension.
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    base = re.sub(r"[_\-]+", " ", base).strip()
    return base[:200]


def _parse_bulk_text(text: str, *, default_title: str = "") -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    blocks = [b.strip() for b in re.split(r"\n-{3,}\n", raw) if b.strip()]
    if len(blocks) <= 1:
        title = str(default_title or "").strip() or "Nội dung import"
        return [{"title": title[:200], "content": raw[:100_000], "tags": []}]
    items: list[dict[str, Any]] = []
    for block in blocks:
        lines = block.splitlines()
        title = lines[0].strip().lstrip("#").strip() if lines else "Node import"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else block
        if not body:
            body = block
        items.append({"title": title[:200], "content": body[:100_000], "tags": []})
    return items


_MD_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")


def _parse_markdown_sections(text: str, *, default_title: str = "") -> list[dict[str, Any]]:
    """Split markdown/text by # headings into KB nodes. Fallback to one node."""
    raw = str(text or "").strip()
    if not raw:
        return []
    # Prefer --- blocks when present.
    if re.search(r"\n-{3,}\n", raw):
        return _parse_bulk_text(raw, default_title=default_title)

    matches = list(_MD_HEADING_RE.finditer(raw))
    if not matches:
        title = str(default_title or "").strip() or "Nội dung import"
        return [{"title": title[:200], "content": raw[:100_000], "tags": []}]

    items: list[dict[str, Any]] = []
    # Preamble before first heading.
    first_start = matches[0].start()
    preamble = raw[:first_start].strip()
    if preamble and len(preamble) >= 20:
        items.append(
            {
                "title": (str(default_title or "").strip() or "Giới thiệu")[:200],
                "content": preamble[:100_000],
                "tags": [],
            }
        )

    for i, m in enumerate(matches):
        title = (m.group(2) or "").strip()
        if not title:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[start:end].strip()
        if not body:
            # Keep heading-only sections with title as content hint.
            body = title
        items.append({"title": title[:200], "content": body[:100_000], "tags": []})
    return items


def import_kb_items(
    db: Session,
    user_id: int,
    bot_id: int,
    *,
    items: list[dict[str, Any]],
    parent_id: int | str | None = None,
    on_duplicate: str = "update",
) -> dict[str, Any]:
    """
    Import KB nodes into the shared AI Knowledge Base.
    on_duplicate: update | skip | rename
    """
    _get_user_bot(db, user_id, bot_id)
    shared_kb.migrate_legacy_chatbot_kb(db, user_id)
    try:
        result = shared_kb.import_items(
            user_id,
            items=items,
            parent_id=parent_id,
            on_duplicate=on_duplicate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _touch_kb_cache(int(bot_id))
    return result


def import_kb_text(
    db: Session,
    user_id: int,
    bot_id: int,
    *,
    title: str = "",
    content: str = "",
    tags: list[str] | None = None,
    format: str = "plain",
    parent_id: int | None = None,
    filename: str = "",
    on_duplicate: str = "update",
) -> dict[str, Any]:
    fmt = str(format or "plain").strip().lower()
    text = str(content or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nội dung import trống.")
    default_tags = [str(t).strip().lower() for t in (tags or []) if str(t).strip()]
    file_title = _title_from_filename(filename)
    default_title = str(title or "").strip() or file_title or "Nội dung import"

    if fmt == "csv":
        items = _parse_csv_rows(text)
        if default_tags:
            for item in items:
                if not item.get("tags"):
                    item["tags"] = list(default_tags)
    elif fmt == "bulk":
        items = _parse_bulk_text(text, default_title=default_title)
        if default_tags:
            for item in items:
                item["tags"] = list(default_tags)
    elif fmt in ("markdown", "md", "auto"):
        items = _parse_markdown_sections(text, default_title=default_title)
        if default_tags:
            for item in items:
                if not item.get("tags"):
                    item["tags"] = list(default_tags)
    else:
        # plain: still try markdown headings when present (common for .txt/.md uploads)
        if _MD_HEADING_RE.search(text) or re.search(r"\n-{3,}\n", text):
            items = _parse_markdown_sections(text, default_title=default_title)
            if default_tags:
                for item in items:
                    if not item.get("tags"):
                        item["tags"] = list(default_tags)
        else:
            items = [{"title": default_title[:200], "content": text, "tags": default_tags}]

    if not items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không đọc được dữ liệu import.")
    result = import_kb_items(
        db,
        user_id,
        bot_id,
        items=items,
        parent_id=parent_id,
        on_duplicate=on_duplicate,
    )
    if result.get("imported", 0) == 0 and result.get("updated", 0) == 0:
        if result.get("skipped_duplicate", 0) > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Không import được: toàn bộ node bị trùng tiêu đề. "
                    "Hãy đổi tiêu đề hoặc xoá node cũ rồi import lại."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không import được: nội dung trống hoặc không hợp lệ.",
        )
    return result


def _parse_xlsx_rows(raw: bytes, *, default_tags: list[str] | None = None) -> list[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server chưa hỗ trợ Excel (thiếu openpyxl).",
        ) from exc
    from io import BytesIO

    try:
        wb = openpyxl.load_workbook(filename=BytesIO(raw), data_only=True, read_only=True)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File Excel không hợp lệ: {exc}") from exc

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []

    def _cell(v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    header = [_cell(c).lower() for c in rows[0]]
    has_header = any(h in ("title", "tiêu đề", "tieu_de", "content", "nội dung", "noi_dung", "tags", "tag") for h in header)
    items: list[dict[str, Any]] = []
    start = 1 if has_header else 0
    title_idx, content_idx, tags_idx = 0, 1, 2
    if has_header:
        for i, h in enumerate(header):
            if h in ("title", "tiêu đề", "tieu_de", "tieu de"):
                title_idx = i
            elif h in ("content", "nội dung", "noi_dung", "noi dung"):
                content_idx = i
            elif h in ("tags", "tag"):
                tags_idx = i

    defaults = [str(t).strip().lower() for t in (default_tags or []) if str(t).strip()]
    for row in rows[start:]:
        if not row:
            continue
        cells = list(row)
        title = _cell(cells[title_idx] if title_idx < len(cells) else "")
        content = _cell(cells[content_idx] if content_idx < len(cells) else "")
        tags_raw = _cell(cells[tags_idx] if tags_idx < len(cells) else "")
        tags = _parse_tags(tags_raw) if tags_raw else list(defaults)
        if title and content:
            items.append({"title": title[:200], "content": content[:100_000], "tags": tags})
    return items


def import_kb_xlsx(
    db: Session,
    user_id: int,
    bot_id: int,
    *,
    raw: bytes,
    tags: list[str] | None = None,
    parent_id: int | None = None,
    on_duplicate: str = "update",
) -> dict[str, Any]:
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File Excel trống.")
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File Excel quá lớn (tối đa 5MB).")
    items = _parse_xlsx_rows(raw, default_tags=tags)
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không đọc được dòng hợp lệ. Cần cột tiêu đề + nội dung.",
        )
    result = import_kb_items(
        db, user_id, bot_id, items=items, parent_id=parent_id, on_duplicate=on_duplicate
    )
    if result.get("imported", 0) == 0 and result.get("updated", 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không import được từ Excel: nội dung trống hoặc toàn bộ bị bỏ qua.",
        )
    return result


def _search_kb_nodes_db(
    db: Session,
    *,
    bot_id: int,
    user_id: int,
    query: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    shared_kb.migrate_legacy_chatbot_kb(db, user_id)
    hits = shared_kb.search_user_knowledge(user_id, query, limit=limit)
    out: list[dict[str, Any]] = []
    for h in hits:
        out.append(
            {
                "node_id": h.get("id"),
                "title": h.get("title"),
                "content": h.get("content") or "",
                "tags": h.get("tags") or [],
                "score": h.get("score") or 0,
                "source": "kb_map",
            }
        )
    return out


def search_kb_nodes(
    db: Session,
    *,
    bot_id: int,
    user_id: int,
    query: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    bid = int(bot_id)
    key = make_search_key(user_id=int(user_id), query=query, limit=limit)
    cached = get_cached_search(bid, key)
    if cached is not None:
        return cached
    result = _search_kb_nodes_db(db, bot_id=bid, user_id=int(user_id), query=query, limit=limit)
    set_cached_search(bid, key, result)
    return result
