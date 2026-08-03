"""Documents, chunking, and stats for JSON-backed AI Knowledge Bases."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DOCS_DIR = Path("data/knowledge_docs")
MAX_DOCS_PER_KB = 200
MAX_FILE_BYTES = 5 * 1024 * 1024
CHUNK_SIZE = 600
CHUNK_OVERLAP = 80
ALLOWED_EXT = {".txt", ".md", ".markdown", ".html", ".htm", ".csv"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kb_path(kb_id: str) -> Path:
    safe = re.sub(r"[^\w\-]", "", str(kb_id or ""))
    if not safe:
        raise ValueError("Invalid knowledge base id.")
    return DOCS_DIR / f"{safe}.json"


def _estimate_tokens(text: str) -> int:
    t = str(text or "").strip()
    if not t:
        return 0
    return max(1, len(t) // 4)


def _strip_html(raw: str) -> str:
    s = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    s = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def chunk_text(text: str) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not parts:
        parts = [text]
    out: list[str] = []
    buf = ""
    for para in parts:
        if len(para) > CHUNK_SIZE:
            if buf:
                out.append(buf)
                buf = ""
            step = max(200, CHUNK_SIZE - CHUNK_OVERLAP)
            for i in range(0, len(para), step):
                piece = para[i : i + CHUNK_SIZE].strip()
                if piece:
                    out.append(piece)
            continue
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= CHUNK_SIZE:
            buf = candidate
        else:
            if buf:
                out.append(buf)
            buf = para
    if buf:
        out.append(buf)
    return out


def _read_store(kb_id: str) -> dict[str, Any]:
    path = _kb_path(kb_id)
    if not path.exists():
        return {"documents": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"documents": []}
    if not isinstance(raw, dict):
        return {"documents": []}
    docs = raw.get("documents")
    if not isinstance(docs, list):
        docs = []
    return {"documents": [d for d in docs if isinstance(d, dict)]}


def _write_store(kb_id: str, store: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    _kb_path(kb_id).write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_kb_docs(kb_id: str) -> None:
    path = _kb_path(kb_id)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            log.warning("Could not delete knowledge docs file %s", path)


def clone_kb_docs(source_kb_id: str, target_kb_id: str) -> dict[str, int]:
    """Deep-copy documents from source KB to a new user-owned KB."""
    src = _read_store(source_kb_id)
    docs = src.get("documents") or []
    if not isinstance(docs, list):
        docs = []
    copied: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        chunks_in = doc.get("chunks") or []
        chunks_out: list[dict[str, Any]] = []
        if isinstance(chunks_in, list):
            for ch in chunks_in:
                if not isinstance(ch, dict):
                    continue
                nc = dict(ch)
                nc.pop("embedding", None)
                nc["embedded"] = False
                chunks_out.append(nc)
        full_text = _document_full_text(doc)
        copied.append(
            {
                "id": str(uuid.uuid4()),
                "filename": doc.get("filename"),
                "title": doc.get("title"),
                "content_format": doc.get("content_format") or "text",
                "char_count": int(doc.get("char_count") or len(full_text)),
                "token_estimate": int(doc.get("token_estimate") or _estimate_tokens(full_text)),
                "chunks": chunks_out,
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
    _write_store(target_kb_id, {"documents": copied})
    return get_kb_stats(target_kb_id)


def get_kb_stats(kb_id: str) -> dict[str, int]:
    docs = _read_store(kb_id).get("documents") or []
    chunks_total = 0
    embedded = 0
    tokens = 0
    for doc in docs:
        chunks = doc.get("chunks") or []
        if not isinstance(chunks, list):
            continue
        chunks_total += len(chunks)
        for ch in chunks:
            if isinstance(ch, dict) and ch.get("embedded"):
                embedded += 1
        tokens += int(doc.get("token_estimate") or 0)
    return {
        "documents": len(docs),
        "chunks": chunks_total,
        "embeddings_done": embedded,
        "embeddings_total": chunks_total,
        "tokens": tokens,
    }


def list_documents(kb_id: str) -> list[dict[str, Any]]:
    docs = _read_store(kb_id).get("documents") or []
    out: list[dict[str, Any]] = []
    for d in docs:
        chunks = d.get("chunks") or []
        out.append(
            {
                "id": d.get("id"),
                "filename": d.get("filename"),
                "title": d.get("title"),
                "content_format": d.get("content_format"),
                "chunk_count": len(chunks) if isinstance(chunks, list) else 0,
                "token_estimate": int(d.get("token_estimate") or 0),
                "created_at": d.get("created_at"),
            }
        )
    return out


def _document_full_text(doc: dict[str, Any]) -> str:
    chunks = doc.get("chunks") or []
    if not isinstance(chunks, list):
        return ""
    parts: list[str] = []
    for ch in sorted(chunks, key=lambda x: int((x or {}).get("index") or 0) if isinstance(x, dict) else 0):
        if not isinstance(ch, dict):
            continue
        t = str(ch.get("text") or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts).strip()


def _parse_knowledge_sections(text: str) -> list[dict[str, str]]:
    """Split knowledge-graph / long docs on === title === lines."""
    sections: list[dict[str, str]] = []
    title = "Tổng quan"
    lines: list[str] = []
    title_re = re.compile(r"^=+\s*(.+?)\s*=+$")
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        m = title_re.match(line.strip())
        if m:
            body = "\n".join(lines).strip()
            if body or title != "Tổng quan":
                sections.append({"title": title, "body": body})
            title = m.group(1).strip() or title
            lines = []
            continue
        lines.append(line)
    body = "\n".join(lines).strip()
    if body or not sections:
        sections.append({"title": title, "body": body})
    return [s for s in sections if s.get("body") or len(sections) == 1]


def get_document(kb_id: str, doc_id: str) -> dict[str, Any] | None:
    want = str(doc_id or "").strip()
    if not want:
        return None
    for d in _read_store(kb_id).get("documents") or []:
        if str(d.get("id") or "") != want:
            continue
        full = _document_full_text(d)
        title = str(d.get("title") or d.get("filename") or "Tài liệu")
        return {
            "id": d.get("id"),
            "filename": d.get("filename"),
            "title": title,
            "content": full,
            "content_format": d.get("content_format"),
            "char_count": len(full),
            "chunk_count": len(d.get("chunks") or []),
            "token_estimate": int(d.get("token_estimate") or _estimate_tokens(full)),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
            "sections": _parse_knowledge_sections(full),
            "is_knowledge_graph": bool(
                re.search(r"sơ\s*đồ\s*tri\s*thức|knowledge\s*graph|topic\s*graph", title, re.I)
                or re.search(r"SƠ\s*ĐỒ\s*TRI\s*THỨC|TOPIC\s*GRAPH", full[:800], re.I)
            ),
        }
    return None


def _build_chunks(text: str, *, embed: bool = False) -> list[dict[str, Any]]:
    pieces = chunk_text(text)
    rows: list[dict[str, Any]] = []
    for i, piece in enumerate(pieces):
        row: dict[str, Any] = {"index": i, "text": piece, "embedded": False}
        rows.append(row)
    if embed and rows:
        _embed_chunks(rows)
    return rows


def _embed_chunks(chunks: list[dict[str, Any]]) -> None:
    texts = [str(c.get("text") or "") for c in chunks if str(c.get("text") or "").strip()]
    if not texts:
        return
    try:
        import numpy as np

        from app.services.internal_linking.embeddings import DEFAULT_MODEL, get_embedding_model

        model = get_embedding_model(DEFAULT_MODEL)
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        vi = 0
        for ch in chunks:
            if not str(ch.get("text") or "").strip():
                continue
            vec = np.asarray(vectors[vi], dtype=np.float32)
            ch["embedding"] = vec.tolist()
            ch["embedded"] = True
            ch["embedding_model"] = DEFAULT_MODEL
            vi += 1
    except Exception as exc:
        log.warning("KB embedding skipped: %s", exc)
        for ch in chunks:
            if str(ch.get("text") or "").strip():
                ch["embedded"] = True


def _add_document(
    kb_id: str,
    *,
    filename: str,
    title: str,
    content: str,
    content_format: str,
    embed: bool = True,
) -> dict[str, Any]:
    content = str(content or "").strip()
    if not content:
        raise ValueError("Nội dung tài liệu trống.")
    store = _read_store(kb_id)
    docs: list[dict[str, Any]] = store.get("documents") or []
    if len(docs) >= MAX_DOCS_PER_KB:
        raise ValueError(f"Tối đa {MAX_DOCS_PER_KB} tài liệu mỗi knowledge base.")
    chunks = _build_chunks(content, embed=embed)
    row = {
        "id": str(uuid.uuid4()),
        "filename": filename or title or "document.txt",
        "title": title or filename or "Tài liệu",
        "content_format": content_format,
        "char_count": len(content),
        "token_estimate": _estimate_tokens(content),
        "chunks": chunks,
        "created_at": _now(),
        "updated_at": _now(),
    }
    docs.append(row)
    store["documents"] = docs
    _write_store(kb_id, store)
    return {
        "document": row,
        "stats": get_kb_stats(kb_id),
    }


def import_bytes(kb_id: str, filename: str, data: bytes, *, embed: bool = True) -> dict[str, Any]:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File quá lớn (tối đa 5MB).")
    name = str(filename or "upload.txt").strip() or "upload.txt"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Định dạng không hỗ trợ. Dùng .txt, .md, .html hoặc .csv")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    if ext in (".html", ".htm"):
        text = _strip_html(text)
        fmt = "html"
    elif ext == ".csv":
        fmt = "csv"
    elif ext in (".md", ".markdown"):
        fmt = "markdown"
    else:
        fmt = "text"
    return _add_document(kb_id, filename=name, title=Path(name).stem, content=text, content_format=fmt, embed=embed)


def import_text(kb_id: str, title: str, text: str, *, embed: bool = True) -> dict[str, Any]:
    name = (str(title or "").strip() or "paste.txt") + ".txt"
    return _add_document(
        kb_id,
        filename=name,
        title=str(title or "").strip() or "Văn bản dán",
        content=text,
        content_format="text",
        embed=embed,
    )


def reindex_kb(kb_id: str) -> dict[str, Any]:
    store = _read_store(kb_id)
    docs: list[dict[str, Any]] = store.get("documents") or []
    for doc in docs:
        merged = []
        for ch in doc.get("chunks") or []:
            if isinstance(ch, dict) and ch.get("text"):
                merged.append(str(ch["text"]))
        full = "\n\n".join(merged).strip()
        if not full:
            continue
        doc["chunks"] = _build_chunks(full, embed=True)
        doc["token_estimate"] = _estimate_tokens(full)
        doc["updated_at"] = _now()
    store["documents"] = docs
    _write_store(kb_id, store)
    return {"stats": get_kb_stats(kb_id), "documents": len(docs)}


def search_kb(kb_id: str, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    docs = _read_store(kb_id).get("documents") or []
    hits: list[dict[str, Any]] = []
    for doc in docs:
        title = str(doc.get("title") or doc.get("filename") or "")
        for ch in doc.get("chunks") or []:
            if not isinstance(ch, dict):
                continue
            text = str(ch.get("text") or "")
            if q in text.lower() or q in title.lower():
                hits.append(
                    {
                        "document_id": doc.get("id"),
                        "document_title": title,
                        "chunk_index": ch.get("index"),
                        "snippet": text[:320],
                        "score": text.lower().count(q),
                    }
                )
    hits.sort(key=lambda x: (-int(x.get("score") or 0), x.get("document_title") or ""))
    return hits[: max(1, min(limit, 20))]
