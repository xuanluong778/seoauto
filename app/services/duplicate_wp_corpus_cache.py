"""Tenant-scoped WordPress corpus cache for duplicate checks (WAVE 5)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

from app.services.embedding_worker_rollout import (
    duplicate_wp_async_fetch_enabled,
    duplicate_wp_corpus_cache_enabled,
)

_LOG = logging.getLogger(__name__)

_CORPUS_TTL = int(os.getenv("DUPLICATE_WP_CORPUS_TTL", "300"))
_STALE_TTL = int(os.getenv("DUPLICATE_WP_STALE_TTL", "3600"))
_CACHE_VERSION = int(os.getenv("DUPLICATE_WP_CACHE_VERSION", "1"))

_METRICS: dict[str, int] = {
    "wp_fetch_count": 0,
    "wp_cache_hit": 0,
    "wp_cache_miss": 0,
    "wp_async_refresh": 0,
}


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    except Exception:
        return None


def _site_norm(site: str) -> str:
    return str(site or "").strip().lower().rstrip("/")


def _keywords_sig(keywords: list[str]) -> str:
    cleaned = sorted(" ".join(str(k or "").strip().lower().split()) for k in keywords if str(k or "").strip())
    raw = "|".join(cleaned[:32])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _corpus_key(*, user_id: int, site: str, keywords: list[str]) -> str:
    return (
        f"dup:wp:v{_CACHE_VERSION}:{int(user_id)}:"
        f"{hashlib.sha256(_site_norm(site).encode()).hexdigest()[:12]}:"
        f"{_keywords_sig(keywords)}"
    )


def _site_index_key(*, user_id: int, site: str) -> str:
    return (
        f"dup:wp:idx:v{_CACHE_VERSION}:{int(user_id)}:"
        f"{hashlib.sha256(_site_norm(site).encode()).hexdigest()[:12]}"
    )


def _site_meta_key(*, user_id: int, site: str) -> str:
    return (
        f"dup:wp:meta:v{_CACHE_VERSION}:{int(user_id)}:"
        f"{hashlib.sha256(_site_norm(site).encode()).hexdigest()[:12]}"
    )


def ref_to_dict(ref: Any) -> dict[str, Any]:
    return {
        "keyword": str(getattr(ref, "keyword", "") or ""),
        "title": str(getattr(ref, "title", "") or ""),
        "url": str(getattr(ref, "url", "") or ""),
        "slug": str(getattr(ref, "slug", "") or ""),
        "source": str(getattr(ref, "source", "") or "published"),
        "project_id": str(getattr(ref, "project_id", "") or ""),
        "target_website": str(getattr(ref, "target_website", "") or ""),
        "wp_post_id": int(getattr(ref, "wp_post_id", 0) or 0),
    }


def ref_from_dict(data: dict[str, Any]) -> Any:
    from app.services.content_ai_duplicate_detection import ExistingArticleRef

    return ExistingArticleRef(
        keyword=str(data.get("keyword") or ""),
        title=str(data.get("title") or ""),
        url=str(data.get("url") or ""),
        slug=str(data.get("slug") or ""),
        source=str(data.get("source") or "published"),
        project_id=str(data.get("project_id") or ""),
        target_website=str(data.get("target_website") or ""),
        wp_post_id=int(data.get("wp_post_id") or 0),
    )


def _serialize_refs(refs: list[Any]) -> bytes:
    return json.dumps([ref_to_dict(r) for r in refs], ensure_ascii=False).encode("utf-8")


def _deserialize_refs(raw: bytes) -> list[Any]:
    try:
        rows = json.loads(raw.decode("utf-8"))
        if not isinstance(rows, list):
            return []
        return [ref_from_dict(r) for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def record_wp_fetch() -> None:
    _METRICS["wp_fetch_count"] = int(_METRICS.get("wp_fetch_count", 0)) + 1


def metrics_snapshot() -> dict[str, Any]:
    hit = int(_METRICS.get("wp_cache_hit", 0))
    miss = int(_METRICS.get("wp_cache_miss", 0))
    total = hit + miss
    return {
        "wp_fetch_count": int(_METRICS.get("wp_fetch_count", 0)),
        "wp_cache_hit": hit,
        "wp_cache_miss": miss,
        "wp_cache_hit_rate": round(hit / total, 4) if total else 0.0,
        "wp_async_refresh": int(_METRICS.get("wp_async_refresh", 0)),
    }


def reset_metrics() -> None:
    for k in _METRICS:
        _METRICS[k] = 0


def invalidate_wp_corpus_for_site(*, user_id: int, site: str) -> None:
    """Bump site version and drop hot corpus keys (publish add/edit/delete)."""
    from app.services.content_ai_duplicate_detection import invalidate_duplicate_corpus_cache

    invalidate_duplicate_corpus_cache(int(user_id))
    r = _redis()
    site_n = _site_norm(site)
    if not r or not site_n:
        return
    try:
        meta_key = _site_meta_key(user_id=user_id, site=site_n)
        r.incr(f"{meta_key}:ver")
        r.set(f"{meta_key}:invalidated_at", str(int(time.time())), ex=_STALE_TTL)
        pattern = f"dup:wp:v{_CACHE_VERSION}:{int(user_id)}:*"
        for key in r.scan_iter(match=pattern, count=200):
            r.delete(key)
    except Exception as exc:
        _LOG.debug("invalidate_wp_corpus failed: %s", exc)


def patch_wp_corpus_post(
    *,
    user_id: int,
    site: str,
    post_id: int,
    ref: Any | None,
    deleted: bool = False,
) -> None:
    """Incremental index update for a single WP post."""
    r = _redis()
    site_n = _site_norm(site)
    if not r or not site_n or post_id <= 0:
        return
    idx_key = _site_index_key(user_id=user_id, site=site_n)
    try:
        if deleted:
            r.hdel(idx_key, str(post_id))
        elif ref is not None:
            r.hset(idx_key, str(post_id), json.dumps(ref_to_dict(ref), ensure_ascii=False))
            r.expire(idx_key, _STALE_TTL)
    except Exception as exc:
        _LOG.debug("patch_wp_corpus_post failed: %s", exc)


def _load_index_refs(*, user_id: int, site: str) -> list[Any]:
    r = _redis()
    site_n = _site_norm(site)
    if not r or not site_n:
        return []
    try:
        idx_key = _site_index_key(user_id=user_id, site=site_n)
        rows = r.hgetall(idx_key)
        if not rows:
            return []
        out: list[Any] = []
        for raw in rows.values():
            if isinstance(raw, bytes):
                data = json.loads(raw.decode("utf-8"))
            else:
                data = json.loads(str(raw))
            if isinstance(data, dict):
                out.append(ref_from_dict(data))
        return out
    except Exception:
        return []


def _cache_get(key: str) -> list[Any] | None:
    r = _redis()
    if not r:
        return None
    try:
        raw = r.get(key)
        if raw:
            return _deserialize_refs(raw)
    except Exception:
        pass
    return None


def _cache_set(key: str, refs: list[Any], *, ttl: int) -> None:
    r = _redis()
    if not r:
        return
    try:
        r.setex(key, ttl, _serialize_refs(refs))
        r.setex(f"{key}:stale", _STALE_TTL, _serialize_refs(refs))
    except Exception:
        pass


def _cache_delete(key: str) -> None:
    r = _redis()
    if not r:
        return
    try:
        r.delete(key)
        r.delete(f"{key}:stale")
    except Exception:
        pass


def _fetch_live_corpus_resilient(
    *,
    user_id: int,
    target_website: str,
    search_keywords: list[str],
    role: str,
    cache_key: str,
) -> tuple[list[Any], str | None]:
    """Fetch live WP corpus; on timeout/429/500 return stale cache when available."""
    from app.services.content_ai_duplicate_detection import _collect_live_site_articles

    stale_key = f"{cache_key}:stale"
    try:
        refs = _collect_live_site_articles(
            user_id=user_id,
            target_website=target_website,
            search_keywords=search_keywords,
            role=role,
        )
        return refs, None
    except Exception as exc:
        err = str(exc)[:200]
        _LOG.warning("WP corpus fetch failed user=%s site=%s: %s", user_id, target_website, err)
        stale = _cache_get(stale_key) or _cache_get(cache_key)
        if stale is not None:
            return stale, err
        index_refs = _load_index_refs(user_id=user_id, site=target_website)
        if index_refs:
            return index_refs, err
        return [], err


def clear_corpus_cache_entry(*, user_id: int, site: str, keywords: list[str]) -> None:
    """Drop hot+stale Redis keys for a corpus entry (cold-cache drills)."""
    key = _corpus_key(user_id=user_id, site=site, keywords=keywords)
    _cache_delete(key)


def _enqueue_refresh(*, user_id: int, site: str, keywords: list[str], role: str) -> None:
    if not duplicate_wp_async_fetch_enabled():
        return
    try:
        from app.workers.embedding_tasks import enqueue_wp_corpus_sync

        enqueue_wp_corpus_sync(
            user_id=int(user_id),
            target_website=str(site),
            keywords=list(keywords),
            role=str(role or "user"),
        )
        _METRICS["wp_async_refresh"] = int(_METRICS.get("wp_async_refresh", 0)) + 1
    except Exception as exc:
        _LOG.debug("enqueue wp corpus sync failed: %s", exc)


def get_live_site_articles_cached(
    *,
    user_id: int,
    target_website: str = "",
    search_keywords: list[str] | None = None,
    role: str = "user",
) -> list[Any]:
    """Cached wrapper around live WP corpus collection."""
    tw = str(target_website or "").strip()
    kws = [str(k or "").strip() for k in (search_keywords or []) if str(k or "").strip()]
    if not tw:
        return []

    if not duplicate_wp_corpus_cache_enabled():
        record_wp_fetch()
        refs, _ = _fetch_live_corpus_resilient(
            user_id=user_id,
            target_website=tw,
            search_keywords=kws,
            role=role,
            cache_key=_corpus_key(user_id=user_id, site=tw, keywords=kws),
        )
        return refs

    cache_key = _corpus_key(user_id=user_id, site=tw, keywords=kws)
    hit = _cache_get(cache_key)
    if hit is not None:
        _METRICS["wp_cache_hit"] = int(_METRICS.get("wp_cache_hit", 0)) + 1
        return hit

    _METRICS["wp_cache_miss"] = int(_METRICS.get("wp_cache_miss", 0)) + 1

    stale_key = f"{cache_key}:stale"
    stale = _cache_get(stale_key)
    if stale is not None and duplicate_wp_async_fetch_enabled():
        _METRICS["wp_cache_hit"] = int(_METRICS.get("wp_cache_hit", 0)) + 1
        _enqueue_refresh(user_id=user_id, site=tw, keywords=kws, role=role)
        return stale

    record_wp_fetch()
    refs, _err = _fetch_live_corpus_resilient(
        user_id=user_id,
        target_website=tw,
        search_keywords=kws,
        role=role,
        cache_key=cache_key,
    )
    if refs:
        _cache_set(cache_key, refs, ttl=_CORPUS_TTL)
    _enqueue_refresh(user_id=user_id, site=tw, keywords=kws, role=role)
    return refs


def sync_wp_corpus_incremental(
    *,
    user_id: int,
    target_website: str,
    search_keywords: list[str] | None = None,
    role: str = "user",
) -> dict[str, Any]:
    """Background refresh: keyword-scoped fetch + update Redis cache/index."""
    tw = str(target_website or "").strip()
    kws = [str(k or "").strip() for k in (search_keywords or []) if str(k or "").strip()]
    if not tw:
        return {"ok": False, "error": "no_site"}

    record_wp_fetch()
    refs, _err = _fetch_live_corpus_resilient(
        user_id=user_id,
        target_website=tw,
        search_keywords=kws,
        role=role,
        cache_key=_corpus_key(user_id=user_id, site=tw, keywords=kws),
    )
    cache_key = _corpus_key(user_id=user_id, site=tw, keywords=kws)
    _cache_set(cache_key, refs, ttl=_CORPUS_TTL)
    for ref in refs:
        pid = int(getattr(ref, "wp_post_id", 0) or 0)
        if pid > 0:
            patch_wp_corpus_post(user_id=user_id, site=tw, post_id=pid, ref=ref)
    return {"ok": True, "count": len(refs), "site": tw}
