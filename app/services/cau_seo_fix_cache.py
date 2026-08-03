"""Cache kết quả Sửa bằng AI — popup Auto Update (theo bài + lỗi + content hash)."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cau_seo_fix_cache.json"
_LOCK = threading.Lock()
_MAX_ENTRIES = 500


def _content_hash(*, title: str, meta: str, slug: str, content: str) -> str:
    raw = f"{title}\n{meta}\n{slug}\n{content[:80_000]}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def make_fix_cache_key(
    *,
    user_id: int,
    post_url: str,
    factor_id: str,
    title: str = "",
    meta: str = "",
    slug: str = "",
    content: str = "",
) -> str:
    ch = _content_hash(title=title, meta=meta, slug=slug, content=content)
    url = str(post_url or "").strip().lower()
    return f"{user_id}:{url}:{factor_id}:{ch}:v6"


def invalidate_cached_fixes(*, factor_id: str | None = None, post_url: str | None = None) -> int:
    """Xóa cache fix (theo factor hoặc URL) — dùng khi đổi logic sửa."""
    removed = 0
    with _LOCK:
        data = _load()
        if not data:
            return 0
        fid = str(factor_id or "").strip().lower()
        url = str(post_url or "").strip().lower()
        keys = list(data.keys())
        for key in keys:
            if fid and f":{fid}:" not in key.lower():
                continue
            if url and url not in key.lower():
                continue
            data.pop(key, None)
            removed += 1
        if removed:
            _save(data)
    return removed


def _load() -> dict[str, Any]:
    try:
        if _CACHE_PATH.is_file():
            data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save(data: dict[str, Any]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    items = list(data.items())
    if len(items) > _MAX_ENTRIES:
        items = items[-_MAX_ENTRIES:]
    _CACHE_PATH.write_text(json.dumps(dict(items), ensure_ascii=False), encoding="utf-8")


def get_cached_fix(key: str) -> dict[str, Any] | None:
    with _LOCK:
        row = _load().get(key)
    return row if isinstance(row, dict) else None


def put_cached_fix(key: str, payload: dict[str, Any]) -> None:
    with _LOCK:
        data = _load()
        data[key] = payload
        _save(data)
