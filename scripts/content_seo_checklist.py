"""Load Content-seo.txt checklist for Content AI prompts (no LLM deps)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_content_seo_file_text() -> str:
    path = Path(__file__).resolve().parents[2] / "Content-seo.txt"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def content_seo_checklist_snippet(*, max_chars: int = 4500) -> str:
    raw = load_content_seo_file_text().strip()
    if not raw:
        return ""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars].rstrip() + "\n… (rút gọn theo giới hạn prompt)"
