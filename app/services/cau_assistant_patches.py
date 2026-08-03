"""CAU Sửa SEO — structured AI patches (apply / undo). Auto Update only.

Patches never overwrite the whole article HTML; they target block_id or insert index.
Locked blocks are skipped.
"""

from __future__ import annotations

import re
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.cau_block_model import (
    ContentBlock,
    heading_level,
    parse_blocks,
    section_range,
    serialize_blocks,
)


def new_patch_id() -> str:
    return "pat_" + uuid.uuid4().hex[:12]


def _word_count(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return 0
    return len(text.split())


@dataclass
class ContentPatch:
    patch_id: str
    action: str
    target_block_id: str | None = None
    insert_index: int | None = None
    old_html: str = ""
    new_html: str = ""
    reason: str = ""
    words_added: int = 0
    words_removed: int = 0
    seo_score_before: int | None = None
    seo_score_after_est: int | None = None
    credit_charged: int = 0
    credit_estimate: int = 0
    applied: bool = False
    status: str = "pending"  # pending | applied | skipped | undone
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContentPatch:
        return cls(
            patch_id=str(data.get("patch_id") or new_patch_id()),
            action=str(data.get("action") or ""),
            target_block_id=(str(data["target_block_id"]) if data.get("target_block_id") else None),
            insert_index=int(data["insert_index"]) if data.get("insert_index") is not None else None,
            old_html=str(data.get("old_html") or ""),
            new_html=str(data.get("new_html") or ""),
            reason=str(data.get("reason") or ""),
            words_added=int(data.get("words_added") or 0),
            words_removed=int(data.get("words_removed") or 0),
            seo_score_before=data.get("seo_score_before"),
            seo_score_after_est=data.get("seo_score_after_est"),
            credit_charged=int(data.get("credit_charged") or 0),
            credit_estimate=int(data.get("credit_estimate") or 0),
            applied=bool(data.get("applied")),
            status=str(data.get("status") or "pending"),
            meta=dict(data.get("meta") or {}),
        )


def build_patch(
    *,
    action: str,
    old_html: str,
    new_html: str,
    target_block_id: str | None = None,
    insert_index: int | None = None,
    reason: str = "",
    seo_score_before: int | None = None,
    seo_score_after_est: int | None = None,
    credit_estimate: int = 0,
    meta: dict[str, Any] | None = None,
) -> ContentPatch:
    old_w = _word_count(old_html)
    new_w = _word_count(new_html)
    added = max(0, new_w - old_w)
    removed = max(0, old_w - new_w)
    return ContentPatch(
        patch_id=new_patch_id(),
        action=action,
        target_block_id=target_block_id,
        insert_index=insert_index,
        old_html=old_html,
        new_html=new_html,
        reason=reason,
        words_added=added,
        words_removed=removed,
        seo_score_before=seo_score_before,
        seo_score_after_est=seo_score_after_est,
        credit_estimate=max(0, int(credit_estimate)),
        meta=dict(meta or {}),
    )


def _find_block(blocks: list[ContentBlock], block_id: str | None) -> tuple[int, ContentBlock | None]:
    if not block_id:
        return -1, None
    for i, b in enumerate(blocks):
        if b.block_id == block_id:
            return i, b
    return -1, None


def apply_patch(
    blocks: list[ContentBlock],
    patch: ContentPatch | dict[str, Any],
) -> tuple[list[ContentBlock], ContentPatch, str | None]:
    """
    Apply one structured patch.
    Returns (new_blocks, updated_patch, error_message).
    Never rewrites the whole article blindly.
    """
    p = patch if isinstance(patch, ContentPatch) else ContentPatch.from_dict(patch)
    out = [deepcopy(b) for b in blocks]

    if p.insert_index is not None and not p.target_block_id:
        # Insert new HTML as blocks after index
        idx = max(0, min(int(p.insert_index), len(out)))
        new_parts = parse_blocks(p.new_html)
        for nb in new_parts:
            nb.changed = True
            nb.original_content = nb.current_content
        for offset, nb in enumerate(new_parts):
            out.insert(idx + offset, nb)
        p.applied = True
        p.status = "applied"
        p.meta = dict(p.meta)
        p.meta["inserted_block_ids"] = [b.block_id for b in new_parts]
        return out, p, None

    idx, block = _find_block(out, p.target_block_id)
    if idx < 0 or block is None:
        return blocks, p, "Không tìm thấy block đích."
    if block.locked:
        p.status = "skipped"
        return blocks, p, "Block đã khóa AI — bỏ qua."

    action = str(p.action or "")

    # Selection patch: replace only the selected substring inside the block.
    if (p.meta or {}).get("selection") and p.old_html:
        cur = block.current_content
        if p.old_html not in cur:
            return blocks, p, "Không tìm thấy đoạn đã chọn trong block."
        out[idx].current_content = cur.replace(p.old_html, p.new_html, 1)
        out[idx].changed = out[idx].current_content != out[idx].original_content
        p.applied = True
        p.status = "applied"
        p.meta = dict(p.meta)
        p.meta["selection_applied"] = True
        return out, p, None

    if action in {"rewrite_heading_sync_section", "refresh_section"}:
        start, end = section_range(out, idx)
        # Replace entire section HTML slice
        section_blocks = out[start:end]
        if any(b.locked for b in section_blocks):
            p.status = "skipped"
            return blocks, p, "Section có block khóa — bỏ qua."
        old_ser = serialize_blocks(section_blocks)
        if not p.old_html:
            p.old_html = old_ser
        new_parts = parse_blocks(p.new_html)
        for nb in new_parts:
            nb.changed = True
        out = out[:start] + new_parts + out[end:]
        p.applied = True
        p.status = "applied"
        p.meta = dict(p.meta)
        p.meta["section_start"] = start
        p.meta["section_end"] = end
        p.meta["replaced_count"] = end - start
        p.meta["inserted_block_ids"] = [b.block_id for b in new_parts]
        return out, p, None

    # Default: replace single block content
    if block.current_content != p.old_html and p.old_html:
        # still allow if old matches original or current loosely
        if p.old_html not in (block.current_content, block.original_content):
            # force apply against current if meta says so
            if not p.meta.get("force"):
                return blocks, p, "Nội dung block đã đổi — tạo lại patch."

    # Append-after-heading: insert new blocks; never overwrite the heading itself.
    append_actions = {
        "expand_1_2",
        "expand_3_5",
        "expand_100",
        "expand_200",
        "add_example",
        "add_steps",
        "add_table",
        "add_faq",
        "add_cta",
        "add_internal_link",
    }
    if (p.meta or {}).get("append_after_heading") and (
        action.startswith("append_") or action in append_actions
    ):
        if heading_level(out[idx]) is None:
            return blocks, p, "Chỉ append sau heading."
        new_parts = parse_blocks(p.new_html)
        for nb in new_parts:
            nb.changed = True
        insert_at = idx + 1
        for offset, nb in enumerate(new_parts):
            out.insert(insert_at + offset, nb)
        p.applied = True
        p.status = "applied"
        p.meta = dict(p.meta)
        p.meta["inserted_block_ids"] = [b.block_id for b in new_parts]
        return out, p, None

    out[idx].current_content = p.new_html
    out[idx].changed = out[idx].current_content != out[idx].original_content
    p.applied = True
    p.status = "applied"
    return out, p, None


def undo_patch(
    blocks: list[ContentBlock],
    patch: ContentPatch | dict[str, Any],
) -> tuple[list[ContentBlock], ContentPatch, str | None]:
    p = patch if isinstance(patch, ContentPatch) else ContentPatch.from_dict(patch)
    if p.status != "applied" and not p.applied:
        return blocks, p, "Patch chưa được áp dụng."
    out = [deepcopy(b) for b in blocks]

    inserted_ids = list((p.meta or {}).get("inserted_block_ids") or [])
    if inserted_ids:
        out = [b for b in out if b.block_id not in set(inserted_ids)]
        # If section replace stored replaced_count, re-insert old HTML
        if p.old_html and (p.meta or {}).get("replaced_count"):
            start = int((p.meta or {}).get("section_start") or 0)
            start = max(0, min(start, len(out)))
            old_parts = parse_blocks(p.old_html)
            for offset, nb in enumerate(old_parts):
                out.insert(start + offset, nb)
        p.applied = False
        p.status = "undone"
        return out, p, None

    idx, block = _find_block(out, p.target_block_id)
    if idx < 0 or block is None:
        return blocks, p, "Không tìm thấy block để hoàn tác."

    if (p.meta or {}).get("selection") and p.new_html:
        cur = block.current_content
        if p.new_html in cur:
            out[idx].current_content = cur.replace(p.new_html, p.old_html, 1)
        else:
            return blocks, p, "Không khớp nội dung để hoàn tác selection."
        out[idx].changed = out[idx].current_content != out[idx].original_content
        p.applied = False
        p.status = "undone"
        return out, p, None

    out[idx].current_content = p.old_html
    out[idx].changed = out[idx].current_content != out[idx].original_content
    p.applied = False
    p.status = "undone"
    return out, p, None


def undo_all_patches(
    blocks: list[ContentBlock],
    patches: list[ContentPatch] | list[dict[str, Any]],
) -> tuple[list[ContentBlock], list[ContentPatch]]:
    """Undo applied patches in reverse order."""
    out = [deepcopy(b) for b in blocks]
    updated: list[ContentPatch] = []
    ordered = list(patches or [])
    for raw in reversed(ordered):
        p = raw if isinstance(raw, ContentPatch) else ContentPatch.from_dict(raw)
        if p.status == "applied" or p.applied:
            out, p2, _err = undo_patch(out, p)
            updated.append(p2)
        else:
            updated.append(p)
    updated.reverse()
    return out, updated


REFRESH_LEVELS: dict[str, dict[str, Any]] = {
    "light": {
        "label": "Nhẹ",
        "desc": "Sửa câu, chính tả, thêm vài câu — giữ cấu trúc.",
        "credit_max": 10,
        "sections_est": 2,
        "words_est": 80,
        "risk": "Thấp — ít thay đổi cấu trúc.",
    },
    "standard": {
        "label": "Tiêu chuẩn",
        "desc": "Tối ưu heading, mở rộng section, thêm FAQ/internal link.",
        "credit_max": 25,
        "sections_est": 4,
        "words_est": 250,
        "risk": "Trung bình — có thể thêm block mới.",
    },
    "deep": {
        "label": "Chuyên sâu",
        "desc": "Phân tích intent, đề xuất thêm/gộp/di chuyển heading và viết lại section yếu.",
        "credit_max": 50,
        "sections_est": 6,
        "words_est": 500,
        "risk": "Cao — nhiều section có thể đổi; vẫn không ghi đè cả bài một lần.",
    },
}


def build_refresh_plan(
    *,
    level: str,
    blocks: list[ContentBlock],
    seo_score: int | None = None,
) -> dict[str, Any]:
    cfg = REFRESH_LEVELS.get(level) or REFRESH_LEVELS["standard"]
    headings = [b for b in blocks if heading_level(b) is not None and not b.locked]
    weak = [b for b in blocks if not b.locked and b.block_type in {"paragraph", "html"}]
    impacted = []
    for b in headings[: cfg["sections_est"]]:
        impacted.append(
            {
                "block_id": b.block_id,
                "type": b.block_type,
                "preview": re.sub(r"<[^>]+>", " ", b.current_content)[:120].strip(),
            }
        )
    if not impacted:
        for b in weak[: cfg["sections_est"]]:
            impacted.append(
                {
                    "block_id": b.block_id,
                    "type": b.block_type,
                    "preview": re.sub(r"<[^>]+>", " ", b.current_content)[:120].strip(),
                }
            )
    return {
        "level": level,
        "label": cfg["label"],
        "description": cfg["desc"],
        "impacted": impacted,
        "sections_estimated": min(cfg["sections_est"], max(1, len(impacted) or 1)),
        "words_estimated": cfg["words_est"],
        "credit_max": cfg["credit_max"],
        "risk_warning": cfg["risk"],
        "seo_score": seo_score,
        "locked_skipped": sum(1 for b in blocks if b.locked),
    }
