"""Keyword idea expansion: Google Ads primary, DataForSEO fallback per seed."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from app.services.keyword_dataforseo_expand import (
    expand_keywords_from_dataforseo,
    is_valid_research_keyword,
)
from app.services.keyword_research_cost import check_and_record_live_call, k4k_cache_ttl_seconds
from app.services.volume_providers.google_ads import (
    fetch_google_ads_keyword_ideas,
    google_ads_configured,
    singleflight,
)


def _ideas_cache_get(key: str) -> list[dict[str, Any]] | None:
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        raw = r.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _ideas_cache_set(key: str, rows: list[dict[str, Any]]) -> None:
    try:
        import redis

        ttl = k4k_cache_ttl_seconds()
        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        r.setex(key, max(3600, ttl), json.dumps(rows, ensure_ascii=False))
    except Exception:
        return None


def _ideas_limit_per_seed(limit_per_seed: int | None) -> int:
    per_seed = int(limit_per_seed or os.getenv("KEYWORD_RESEARCH_ADS_IDEAS_LIMIT", "80"))
    return max(10, min(700, per_seed))


def _ideas_cache_key(seed: str, *, country: str | None, language: str | None, limit: int) -> str:
    raw = f"{seed.strip().lower()}|{(country or '').lower()}|{(language or '').lower()}|{limit}|ads"
    return "kideas:v1:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def peek_ads_ideas_cache_status(
    seeds: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
    limit_per_seed: int | None = None,
) -> dict[str, Any]:
    """Đếm seed có Redis kideas:v1 hay cần gọi Google Ads."""
    per_seed = _ideas_limit_per_seed(limit_per_seed)
    hits = 0
    misses = 0
    hit_seeds: list[str] = []
    miss_keywords: list[str] = []
    for seed in seeds or []:
        s = (seed or "").strip()
        if not s:
            continue
        cache_key = _ideas_cache_key(s, country=country, language=language, limit=per_seed)
        if _ideas_cache_get(cache_key) is not None:
            hits += 1
            hit_seeds.append(s)
        else:
            misses += 1
            miss_keywords.append(s)
    return {
        "hits": hits,
        "misses": misses,
        "total": hits + misses,
        "hit_seeds": hit_seeds,
        "miss_keywords": miss_keywords,
    }


def expand_keywords_from_google_ads(
    seeds: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
    limit_per_seed: int | None = None,
    total_cap: int = 200,
    min_volume: int = 0,
    allow_api: bool = True,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Google Ads GenerateKeywordIdeas per seed, Redis-cached. Empty if Ads not configured."""
    if not google_ads_configured():
        return []
    if os.getenv("VOLUME_API_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return []

    cap = max(10, min(int(total_cap or 200), 500))
    per_seed = _ideas_limit_per_seed(limit_per_seed)
    min_vol = max(0, int(min_volume))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    filled_seeds: list[str] = []

    for seed in seeds or []:
        s = (seed or "").strip()
        if not s:
            continue
        cache_key = _ideas_cache_key(s, country=country, language=language, limit=per_seed)
        batch = _ideas_cache_get(cache_key)
        if batch is None:
            ads_live = (
                os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes")
                and google_ads_configured()
            )
            if not ads_live:
                batch = []
            else:
                def _live() -> list[dict[str, Any]]:
                    check_and_record_live_call(stats, label="google_ads_ideas")
                    got = fetch_google_ads_keyword_ideas(
                        [s],
                        country=country,
                        language=language,
                        limit=per_seed,
                    )
                    if stats is not None:
                        stats["api_tasks"] = stats.get("api_tasks", 0) + 1
                    return got or []

                live = singleflight(cache_key, _live)
                batch = live if live is not None else (_ideas_cache_get(cache_key) or [])
                if live:
                    _ideas_cache_set(cache_key, live)
        elif stats is not None:
            stats["cache_hits"] = stats.get("cache_hits", 0) + 1
        seed_hits = 0
        for item in batch or []:
            kw = str(item.get("keyword") or "").strip()
            if not kw or not is_valid_research_keyword(kw):
                continue
            low = kw.lower()
            if low in seen:
                continue
            vol_raw = item.get("search_volume")
            try:
                vol = int(vol_raw) if vol_raw is not None else 0
            except (TypeError, ValueError):
                vol = 0
            if min_vol > 0 and vol < min_vol:
                continue
            seen.add(low)
            seed_hits += 1
            row = dict(item)
            row["keyword"] = kw
            row["source"] = "google_ads"
            row["provider"] = "google_ads"
            row["volume_source"] = "google_ads"
            rows.append(row)
            if len(rows) >= cap:
                if seed_hits:
                    filled_seeds.append(s)
                if stats is not None:
                    stats["ads_seeds_filled"] = list(dict.fromkeys((stats.get("ads_seeds_filled") or []) + filled_seeds))
                return rows
        if seed_hits:
            filled_seeds.append(s)

    if stats is not None:
        stats["ads_seeds_filled"] = list(dict.fromkeys(filled_seeds))
    rows.sort(key=lambda r: int(r.get("search_volume") or 0), reverse=True)
    return rows[:cap]


def expand_keyword_ideas(
    seeds: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
    limit_per_seed: int | None = None,
    total_cap: int = 200,
    min_volume: int = 0,
    allow_api: bool = True,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ads primary; DataForSEO only for seeds Ads missed. Does not re-run filled seeds."""
    local = stats if stats is not None else {}
    ads_rows = expand_keywords_from_google_ads(
        seeds,
        country=country,
        language=language,
        limit_per_seed=limit_per_seed,
        total_cap=total_cap,
        min_volume=min_volume,
        allow_api=allow_api,
        stats=local,
    )
    filled = {str(s).strip().lower() for s in local.get("ads_seeds_filled") or []}

    missing_seeds = [s for s in (seeds or []) if str(s or "").strip().lower() not in filled]
    dfs_rows: list[dict[str, Any]] = []
    if missing_seeds:
        remaining_cap = max(0, int(total_cap or 200) - len(ads_rows))
        if remaining_cap > 0:
            dfs_rows = expand_keywords_from_dataforseo(
                missing_seeds,
                country=country,
                language=language,
                limit_per_seed=limit_per_seed,
                total_cap=remaining_cap,
                min_volume=max(1, min_volume),
                allow_api=allow_api,
                stats=local,
            )
            if dfs_rows:
                local["dataforseo_fallback_seeds"] = missing_seeds

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in list(ads_rows) + list(dfs_rows):
        kw = str(row.get("keyword") or "").strip()
        if not kw:
            continue
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        if "provider" not in row:
            src = str(row.get("source") or row.get("volume_source") or "dataforseo")
            row["provider"] = src
        out.append(row)
        if len(out) >= int(total_cap or 200):
            break
    if stats is not None or local:
        local["idea_provider"] = "google_ads" if ads_rows and not dfs_rows else (
            "google_ads+dataforseo" if ads_rows and dfs_rows else ("dataforseo" if dfs_rows else "none")
        )
    return out
