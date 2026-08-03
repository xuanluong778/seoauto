"""Content Auto Update — block model for Sửa SEO modal (parse / serialize / structure).

Preserves exact original HTML slices for unchanged blocks so round-trip is stable.
"""

from __future__ import annotations

import re
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

_GUTENBERG_OPEN = re.compile(
    r"<!--\s*wp:([a-z0-9\-/]+)(\s+(\{[\s\S]*?\}))?\s*(/)?-->",
    re.I,
)
_SHORTCODE = re.compile(r"\[[a-zA-Z][\w\-]*(?:\s[^\]]*)?\]")
_TOP_TAG = re.compile(
    r"(?is)(<!--[\s\S]*?-->)|"
    r"(<(?P<tag>h[1-6]|p|ul|ol|table|figure|blockquote|pre|hr|div|section|aside|nav|"
    r"header|footer|article|form|iframe|video|audio|img|address)"
    r"(?:\s[^>]*)?(?:/>|>[\s\S]*?</(?P=tag)\s*>))",
)


@dataclass
class ContentBlock:
    block_id: str
    block_type: str
    original_content: str
    current_content: str
    locked: bool = False
    changed: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContentBlock:
        return cls(
            block_id=str(data.get("block_id") or new_block_id()),
            block_type=str(data.get("block_type") or "html"),
            original_content=str(data.get("original_content") or ""),
            current_content=str(data.get("current_content") or data.get("original_content") or ""),
            locked=bool(data.get("locked")),
            changed=bool(data.get("changed")),
            meta=dict(data.get("meta") or {}),
        )


def new_block_id() -> str:
    return "blk_" + uuid.uuid4().hex[:12]


def _detect_type_from_html(html: str) -> tuple[str, dict[str, Any]]:
    raw = str(html or "").strip()
    if not raw:
        return "html", {}
    low = raw.lower()
    if low.startswith("<!-- wp:"):
        m = _GUTENBERG_OPEN.match(raw)
        name = (m.group(1) if m else "block").lower()
        meta: dict[str, Any] = {"gutenberg": name}
        if name.startswith("heading") or name == "core/heading":
            hm = re.search(r"<h([1-6])\b", raw, re.I)
            level = int(hm.group(1)) if hm else 2
            meta["level"] = level
            return "heading", meta
        if "paragraph" in name:
            return "paragraph", meta
        if "list" in name:
            return "list", meta
        if "table" in name:
            return "table", meta
        if "image" in name:
            return "image", meta
        if "embed" in name or "video" in name or "audio" in name:
            return "embed", meta
        if "shortcode" in name or "html" in name:
            return "shortcode" if "shortcode" in name else "html", meta
        return "gutenberg", meta

    if re.match(r"^\[/?[a-zA-Z]", raw):
        return "shortcode", {}

    hm = re.match(r"^<h([1-6])\b", raw, re.I)
    if hm:
        return "heading", {"level": int(hm.group(1))}
    if re.match(r"^<(ul|ol)\b", raw, re.I):
        return "list", {}
    if re.match(r"^<table\b", raw, re.I):
        return "table", {}
    if re.match(r"^<(figure|img)\b", raw, re.I) or ("<img" in low and re.match(r"^<(p|div|figure)\b", raw, re.I)):
        if re.match(r"^<(figure|img)\b", raw, re.I):
            return "image", {}
    if re.match(r"^<(iframe|embed|video|audio)\b", raw, re.I):
        return "embed", {}
    if re.match(r"^<p\b", raw, re.I):
        return "paragraph", {}
    return "html", {}


def _make_block(html: str, *, block_type: str | None = None, meta: dict[str, Any] | None = None) -> ContentBlock:
    content = str(html or "")
    detected, dmeta = _detect_type_from_html(content)
    btype = block_type or detected
    merged = dict(dmeta)
    if meta:
        merged.update(meta)
    return ContentBlock(
        block_id=new_block_id(),
        block_type=btype,
        original_content=content,
        current_content=content,
        locked=False,
        changed=False,
        meta=merged,
    )


def _parse_gutenberg(html: str) -> list[ContentBlock] | None:
    text = str(html or "")
    if "<!-- wp:" not in text.lower() and "<!--wp:" not in text.lower():
        return None
    blocks: list[ContentBlock] = []
    i = 0
    n = len(text)
    while i < n:
        m = _GUTENBERG_OPEN.search(text, i)
        if not m:
            tail = text[i:]
            if tail:
                blocks.append(_make_block(tail))
            break
        if m.start() > i:
            gap = text[i : m.start()]
            if gap:
                blocks.append(_make_block(gap))
        self_close = bool(m.group(4))
        name = m.group(1)
        if self_close:
            chunk = text[m.start() : m.end()]
            blocks.append(_make_block(chunk))
            i = m.end()
            continue
        close = re.search(
            rf"<!--\s*/wp:{re.escape(name)}\s*-->",
            text[m.end() :],
            re.I,
        )
        if not close:
            # Unclosed — take rest as one block
            chunk = text[m.start() :]
            blocks.append(_make_block(chunk))
            break
        end = m.end() + close.end()
        chunk = text[m.start() : end]
        blocks.append(_make_block(chunk))
        i = end
    return blocks


def _parse_classic(html: str) -> list[ContentBlock]:
    text = str(html or "")
    if not text:
        return []
    blocks: list[ContentBlock] = []
    pos = 0
    n = len(text)
    while pos < n:
        # Leading whitespace / shortcodes / text until next tag
        m = _TOP_TAG.search(text, pos)
        if not m:
            tail = text[pos:]
            if tail.strip():
                # Maybe shortcode-only chunk
                blocks.append(_make_block(tail))
            break
        if m.start() > pos:
            gap = text[pos : m.start()]
            if gap:
                blocks.append(_make_block(gap))
        chunk = m.group(0)
        # HTML comments that are not gutenberg stay as html
        if chunk.lstrip().startswith("<!--") and "wp:" not in chunk.lower():
            blocks.append(_make_block(chunk, block_type="html"))
        else:
            blocks.append(_make_block(chunk))
        pos = m.end()
    return blocks


def parse_blocks(html: str) -> list[ContentBlock]:
    """Parse HTML / Gutenberg into ContentBlock list (exact slice preservation)."""
    text = str(html or "")
    if not text.strip():
        return []
    guten = _parse_gutenberg(text)
    if guten is not None:
        return guten
    return _parse_classic(text)


def serialize_blocks(blocks: list[ContentBlock] | list[dict[str, Any]]) -> str:
    """Join blocks: unchanged → original_content; changed → current_content."""
    parts: list[str] = []
    for raw in blocks or []:
        b = raw if isinstance(raw, ContentBlock) else ContentBlock.from_dict(raw)
        if b.changed:
            parts.append(b.current_content)
        else:
            parts.append(b.original_content)
    return "".join(parts)


def roundtrip_unchanged(html: str) -> bool:
    return serialize_blocks(parse_blocks(html)) == str(html or "")


def heading_level(block: ContentBlock | dict[str, Any]) -> int | None:
    b = block if isinstance(block, ContentBlock) else ContentBlock.from_dict(block)
    if b.block_type != "heading" and "heading" not in str(b.meta.get("gutenberg") or ""):
        # still check HTML
        hm = re.search(r"<h([1-6])\b", b.current_content, re.I)
        if not hm:
            return None
        return int(hm.group(1))
    lvl = b.meta.get("level")
    if lvl:
        return int(lvl)
    hm = re.search(r"<h([1-6])\b", b.current_content, re.I)
    return int(hm.group(1)) if hm else None


def section_range(blocks: list[ContentBlock], index: int) -> tuple[int, int]:
    """Inclusive start, exclusive end of heading section (heading + descendants)."""
    if index < 0 or index >= len(blocks):
        raise IndexError("block index out of range")
    level = heading_level(blocks[index])
    if level is None:
        return index, index + 1
    end = index + 1
    while end < len(blocks):
        hl = heading_level(blocks[end])
        if hl is not None and hl <= level:
            break
        end += 1
    return index, end


def move_section(blocks: list[ContentBlock], index: int, *, direction: str) -> list[ContentBlock]:
    """Move heading section up/down among sibling-level sections."""
    out = list(blocks)
    start, end = section_range(out, index)
    level = heading_level(out[index])
    if level is None:
        return out
    chunk = out[start:end]
    if direction == "up":
        # find previous sibling section start
        prev = start - 1
        while prev >= 0:
            hl = heading_level(out[prev])
            if hl is not None and hl <= level:
                # if same or higher, find its section start
                if hl == level:
                    p_start, _ = section_range(out, prev)
                    del out[start:end]
                    out[p_start:p_start] = chunk
                    return out
                break
            prev -= 1
        return out
    if direction == "down":
        # next sibling after this section
        nxt = end
        while nxt < len(out):
            hl = heading_level(out[nxt])
            if hl is not None and hl == level:
                _ns, n_end = section_range(out, nxt)
                # remove chunk first
                del out[start:end]
                # after deletion, n_end shifts
                insert_at = n_end - (end - start)
                out[insert_at:insert_at] = chunk
                return out
            if hl is not None and hl < level:
                break
            nxt += 1
        return out
    return out


def change_heading_level(block: ContentBlock, new_level: int) -> ContentBlock:
    lvl = max(1, min(6, int(new_level)))
    html = block.current_content
    html2 = re.sub(r"<h([1-6])(\b)", rf"<h{lvl}\2", html, count=1, flags=re.I)
    html2 = re.sub(r"</h([1-6])\s*>", f"</h{lvl}>", html2, count=1, flags=re.I)
    # gutenberg attrs level
    html2 = re.sub(r'("level"\s*:\s*)\d+', rf"\g<1>{lvl}", html2, count=1)
    b = deepcopy(block)
    b.current_content = html2
    b.changed = b.current_content != b.original_content
    b.meta = dict(b.meta)
    b.meta["level"] = lvl
    return b


def insert_heading_html(
    *,
    title: str,
    level: int = 2,
    body_html: str = "",
) -> str:
    lvl = max(2, min(4, int(level)))
    title_esc = (
        str(title or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    parts = [f"<h{lvl}>{title_esc}</h{lvl}>"]
    body = str(body_html or "").strip()
    if body:
        parts.append(body if body.startswith("<") else f"<p>{body}</p>")
    return "".join(parts)


def insert_blocks_at(
    blocks: list[ContentBlock],
    index: int,
    new_blocks: list[ContentBlock],
) -> list[ContentBlock]:
    """Insert after the block at index-1; index is insert position (0 = before first)."""
    out = list(blocks)
    i = max(0, min(int(index), len(out)))
    for offset, nb in enumerate(new_blocks):
        out.insert(i + offset, nb)
    return out


def blocks_to_outline(blocks: list[ContentBlock]) -> list[dict[str, Any]]:
    tree: list[dict[str, Any]] = []
    for i, b in enumerate(blocks):
        lvl = heading_level(b)
        if lvl is None:
            continue
        text = re.sub(r"<[^>]+>", "", b.current_content)
        text = re.sub(r"\s+", " ", text).strip()
        tree.append(
            {
                "index": i,
                "block_id": b.block_id,
                "level": lvl,
                "text": text[:200],
                "locked": b.locked,
            }
        )
    return tree


class BlockHistory:
    """Undo/redo stack of block list snapshots."""

    def __init__(self, limit: int = 50) -> None:
        self.limit = limit
        self._undo: list[list[dict[str, Any]]] = []
        self._redo: list[list[dict[str, Any]]] = []

    @staticmethod
    def _snap(blocks: list[ContentBlock]) -> list[dict[str, Any]]:
        return [b.to_dict() for b in blocks]

    @staticmethod
    def _restore(snap: list[dict[str, Any]]) -> list[ContentBlock]:
        return [ContentBlock.from_dict(x) for x in snap]

    def push(self, blocks: list[ContentBlock]) -> None:
        self._undo.append(self._snap(blocks))
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current: list[ContentBlock]) -> list[ContentBlock] | None:
        if not self._undo:
            return None
        self._redo.append(self._snap(current))
        return self._restore(self._undo.pop())

    def redo(self, current: list[ContentBlock]) -> list[ContentBlock] | None:
        if not self._redo:
            return None
        self._undo.append(self._snap(current))
        return self._restore(self._redo.pop())
