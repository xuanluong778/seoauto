"""
SERP fetch for SEO Score tab — cache-first, cost-gated, no duplicate provider bills.

Cache key: keyword + country + language + device + location_code.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from app.services.serp_fetcher import (
    _redis_get_v2,
    _redis_set_v2,
    _resolved_locale,
    _serp_cache_digest,
    _snap_has_urls,
    fetch_serp_for_keyword,
    serp_top10_rows_from_snap,
)

_SEO_SCORE_SERP_NS = "seo_score_serp:v1"


def seo_score_serp_cache_digest(
    keyword: str,
    *,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
    location_code: str | None = None,
) -> str:
    loc = _resolved_locale(country=country, language=language, device=device)
    loc_code = str(location_code or os.getenv("DATAFORSEO_LOCATION_CODE") or "").strip()
    raw = "|".join([loc["country"], loc["language"], loc["device"], loc_code, (keyword or "").strip().lower()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_ttl_seconds() -> int:
    return max(3600, min(86400, int(os.getenv("SEO_SCORE_SERP_CACHE_TTL_SECONDS", "43200"))))


def peek_seo_score_serp_cache(
    keyword: str,
    *,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
    location_code: str | None = None,
) -> dict[str, Any] | None:
    kw = (keyword or "").strip()
    if not kw:
        return None
    digest = seo_score_serp_cache_digest(
        kw, country=country, language=language, device=device, location_code=location_code
    )
    # Prefer SEO-score namespace; fall back to shared serp:v2 digest for reuse
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        raw = r.get(f"{_SEO_SCORE_SERP_NS}:{digest}")
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict) and _snap_has_urls(data):
                data["cache_hit"] = True
                data["cache_digest"] = digest
                return data
    except Exception:
        pass
    loc = _resolved_locale(country=country, language=language, device=device)
    shared = _redis_get_v2(_serp_cache_digest(kw, loc))
    if shared and _snap_has_urls(shared):
        shared = dict(shared)
        shared["cache_hit"] = True
        shared["cache_digest"] = digest
        shared["cache_source"] = "serp_shared"
        return shared
    return None


def _store_seo_score_serp_cache(digest: str, snap: dict[str, Any]) -> None:
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        r.setex(f"{_SEO_SCORE_SERP_NS}:{digest}", _cache_ttl_seconds(), json.dumps(snap)[:120000])
    except Exception:
        pass
    loc = _resolved_locale(
        country=snap.get("country"),
        language=snap.get("language"),
        device=snap.get("device"),
    )
    _redis_set_v2(_serp_cache_digest(str(snap.get("keyword") or ""), loc), snap)


def fetch_seo_score_serp(
    keyword: str,
    *,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
    location_code: str | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Cache → dedup → provider (via serp_fetcher, which respects SERP_FETCH_ENABLED).
    Never bypasses shared serp cache layers.
    """
    kw = (keyword or "").strip()
    if not kw:
        return {"keyword": "", "rows": [], "source": "empty", "cache_hit": False, "provider_called": False}

    digest = seo_score_serp_cache_digest(
        kw, country=country, language=language, device=device, location_code=location_code
    )
    hit = peek_seo_score_serp_cache(
        kw, country=country, language=language, device=device, location_code=location_code
    )
    if hit:
        if stats is not None:
            stats["serp_cache_hit"] = True
            stats["serp_provider_called"] = False
        rows = serp_top10_rows_from_snap(hit)
        return {
            "keyword": kw,
            "rows": rows,
            "snap": hit,
            "source": str(hit.get("source") or "cache"),
            "cache_hit": True,
            "cache_digest": digest,
            "provider_called": False,
        }

    if stats is not None:
        stats["serp_cache_hit"] = False
        stats["serp_provider_called"] = True

    snap = fetch_serp_for_keyword(
        kw,
        top_n=10,
        use_cache=True,
        country=country,
        language=language,
        device=device,
    )
    if _snap_has_urls(snap):
        snap = dict(snap)
        snap["cache_hit"] = False
        snap["cache_digest"] = digest
        _store_seo_score_serp_cache(digest, snap)

    rows = serp_top10_rows_from_snap(snap)
    return {
        "keyword": kw,
        "rows": rows,
        "snap": snap,
        "source": str(snap.get("source") or "none"),
        "cache_hit": bool(snap.get("cache_hit")),
        "cache_digest": digest,
        "provider_called": not bool(snap.get("cache_hit")),
    }
