"""In-memory KB search cache — invalidated per bot_id on writes."""

from __future__ import annotations

import hashlib
import threading
from typing import Any

_lock = threading.Lock()
_search_cache: dict[int, dict[str, list[dict[str, Any]]]] = {}
_bot_versions: dict[int, int] = {}


def invalidate_bot_kb_cache(bot_id: int) -> None:
    bid = int(bot_id)
    with _lock:
        _search_cache.pop(bid, None)
        _bot_versions[bid] = int(_bot_versions.get(bid, 0)) + 1


def invalidate_all_kb_caches() -> None:
    """Drop every in-memory Chatbot search hit so Settings import/reindex is visible immediately."""
    with _lock:
        _search_cache.clear()
        for bid in list(_bot_versions):
            _bot_versions[bid] = int(_bot_versions.get(bid, 0)) + 1


def invalidate_user_kb_cache(user_id: int) -> None:
    """Search keys embed user_id; bot_id is not known here, so clear the whole cache."""
    _ = int(user_id)
    invalidate_all_kb_caches()


def get_bot_kb_version(bot_id: int) -> int:
    with _lock:
        return int(_bot_versions.get(int(bot_id), 0))


def make_search_key(*, user_id: int, query: str, limit: int) -> str:
    raw = f"{int(user_id)}|{str(query or '').strip().lower()}|{int(limit)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def get_cached_search(bot_id: int, key: str) -> list[dict[str, Any]] | None:
    bid = int(bot_id)
    with _lock:
        bucket = _search_cache.get(bid)
        if not bucket:
            return None
        hit = bucket.get(key)
        return list(hit) if hit is not None else None


def set_cached_search(bot_id: int, key: str, value: list[dict[str, Any]]) -> None:
    bid = int(bot_id)
    with _lock:
        bucket = _search_cache.setdefault(bid, {})
        bucket[key] = list(value)
