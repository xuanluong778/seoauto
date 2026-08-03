"""Per-request / per-job cache — tránh fetch website & research lặp trong cùng luồng viết."""

from __future__ import annotations

import contextvars
from typing import Any, TypeVar

T = TypeVar("T")

_CACHE: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "content_ai_request_cache", default=None
)


def reset_request_cache() -> dict[str, Any]:
    bucket: dict[str, Any] = {}
    _CACHE.set(bucket)
    return bucket


def get_request_cache() -> dict[str, Any]:
    bucket = _CACHE.get()
    if bucket is None:
        bucket = reset_request_cache()
    return bucket


def cache_get(key: str) -> Any:
    return get_request_cache().get(key)


def cache_set(key: str, value: Any) -> None:
    get_request_cache()[key] = value


def cache_get_or_set(key: str, factory: Any) -> Any:
    hit = cache_get(key)
    if hit is not None:
        return hit
    val = factory()
    cache_set(key, val)
    return val
