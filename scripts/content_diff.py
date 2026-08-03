"""Diff helpers for Content Auto Update preview."""

from __future__ import annotations

import difflib
import re
from html import unescape
from typing import Any


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", unescape(html or ""))


def _line_diff(old: str, new: str, max_lines: int = 120) -> list[str]:
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    return diff[:max_lines]


def build_content_diff(
    *,
    old_title: str,
    new_title: str,
    old_content: str,
    new_content: str,
    old_excerpt: str,
    new_excerpt: str,
) -> dict[str, Any]:
    fields = []
    for key, o, n in (
        ("title", old_title, new_title),
        ("excerpt", old_excerpt, new_excerpt),
        ("content", old_content, new_content),
    ):
        changed = (o or "").strip() != (n or "").strip()
        entry: dict[str, Any] = {
            "field": key,
            "changed": changed,
            "old_preview": (o or "")[:2000],
            "new_preview": (n or "")[:2000],
        }
        if changed:
            if key == "content":
                entry["diff_lines"] = _line_diff(_strip_tags(o)[:8000], _strip_tags(n)[:8000])
                entry["old_word_count"] = len(_strip_tags(o).split())
                entry["new_word_count"] = len(_strip_tags(n).split())
            else:
                entry["diff_lines"] = _line_diff(o or "", n or "")
        fields.append(entry)

    changed_count = sum(1 for f in fields if f.get("changed"))
    content_f = next((f for f in fields if f.get("field") == "content"), {})
    title_f = next((f for f in fields if f.get("field") == "title"), {})
    return {
        "changed_fields": changed_count,
        "fields": fields,
        "summary": f"{changed_count} trường thay đổi" if changed_count else "Không có thay đổi",
        "title_changed": bool(title_f.get("changed")),
        "old_title": (old_title or "")[:500],
        "new_title": (new_title or "")[:500],
        "old_word_count": int(content_f.get("old_word_count") or 0),
        "new_word_count": int(content_f.get("new_word_count") or 0),
    }


def build_preview_summary(
    *,
    diff: dict[str, Any],
    comparison: dict[str, Any] | None,
    backup_id: str,
) -> dict[str, Any]:
    comp = comparison or {}
    return {
        "backup_id": backup_id,
        "title": {
            "old": diff.get("old_title") or "",
            "new": diff.get("new_title") or "",
            "changed": diff.get("title_changed"),
        },
        "word_count": {
            "old": diff.get("old_word_count") or 0,
            "new": diff.get("new_word_count") or 0,
        },
        "seo_score": {
            "before": comp.get("before_score"),
            "after": comp.get("after_score"),
            "delta": comp.get("delta"),
        },
        "improved_factors": comp.get("improved_factors") or [],
        "failed_after": comp.get("failed_after") or [],
        "diff_summary": diff.get("summary") or "",
        "changed_fields": diff.get("changed_fields") or 0,
    }
