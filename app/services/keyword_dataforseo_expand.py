"""Expand keyword research candidates via DataForSEO Google Ads Keywords For Keywords."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from app.services.keyword_research_cost import check_and_record_live_call, k4k_cache_ttl_seconds
from app.services.volume_providers.dataforseo import fetch_dataforseo_keywords_for_keywords

_JUNK_DOMAIN = re.compile(r"\b[\w-]+\.(com|vn|net|org|io|co)\b", re.I)
_JUNK_URL = re.compile(r"https?://|www\.", re.I)


def _k4k_cache_get(key: str) -> list[dict[str, Any]] | None:
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


def _k4k_cache_set(key: str, rows: list[dict[str, Any]]) -> None:
    try:
        import redis

        ttl = k4k_cache_ttl_seconds()
        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        r.setex(key, max(3600, ttl), json.dumps(rows, ensure_ascii=False))
    except Exception:
        pass


def _k4k_cache_key(seed: str, *, country: str | None, language: str | None, limit: int) -> str:
    raw = f"{seed.strip().lower()}|{(country or '').lower()}|{(language or '').lower()}|{limit}"
    return "k4k:v1:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_valid_research_keyword(keyword: str) -> bool:
    """Drop SERP titles / URLs — keep real search phrases."""
    s = (keyword or "").strip()
    if len(s) < 2 or len(s) > 80:
        return False
    if len(s.split()) > 8:
        return False
    if "|" in s or "—" in s or "–" in s:
        return False
    if _JUNK_URL.search(s) or _JUNK_DOMAIN.search(s):
        return False
    return True


def peek_k4k_cache_status(
    seeds: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
    limit_per_seed: int | None = None,
) -> dict[str, int]:
    """Đếm seed có cache K4K hay cần gọi API."""
    per_seed = int(
        limit_per_seed or os.getenv("KEYWORD_RESEARCH_DATAFORSEO_K4K_LIMIT", "120")
    )
    per_seed = max(15, min(700, per_seed))
    hits = 0
    misses = 0
    for seed in seeds or []:
        s = (seed or "").strip()
        if not s:
            continue
        cache_key = _k4k_cache_key(s, country=country, language=language, limit=per_seed)
        if _k4k_cache_get(cache_key) is not None:
            hits += 1
        else:
            misses += 1
    return {"hits": hits, "misses": misses, "total": hits + misses}


def expand_keywords_from_dataforseo(
    seeds: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
    limit_per_seed: int | None = None,
    total_cap: int = 200,
    min_volume: int = 1,
    allow_api: bool = True,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Related keywords from DataForSEO with search volume + CPC when available.

    Returns rows: keyword, source, search_volume, cpc_avg, competition_index, monthly_searches.
    """
    if os.getenv("DATAFORSEO_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return []
    if os.getenv("VOLUME_API_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return []

    cap = max(10, min(int(total_cap or 200), 500))
    per_seed = int(
        limit_per_seed
        or os.getenv("KEYWORD_RESEARCH_DATAFORSEO_K4K_LIMIT", "120")
    )
    per_seed = max(15, min(700, per_seed))
    min_vol = max(0, int(min_volume))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    filtered_count = 0

    for seed in seeds or []:
        s = (seed or "").strip()
        if not s:
            continue
        cache_key = _k4k_cache_key(s, country=country, language=language, limit=per_seed)
        batch = _k4k_cache_get(cache_key)
        if batch is None:
            if not allow_api:
                batch = []
            else:
                check_and_record_live_call(stats, label="k4k")
                batch = fetch_dataforseo_keywords_for_keywords(
                    [s],
                    country=country,
                    language=language,
                    limit=per_seed,
                )
                if stats is not None:
                    stats["api_tasks"] = stats.get("api_tasks", 0) + 1
                if batch:
                    _k4k_cache_set(cache_key, batch)
        elif stats is not None:
            stats["cache_hits"] = stats.get("cache_hits", 0) + 1
        for item in batch or []:
            kw = str(item.get("keyword") or "").strip()
            if not kw or not is_valid_research_keyword(kw):
                filtered_count += 1
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
                filtered_count += 1
                continue
            seen.add(low)
            rows.append(
                {
                    "keyword": kw,
                    "source": "dataforseo",
                    "search_volume": vol,
                    "cpc_avg": float(item.get("cpc_avg") or 0.0),
                    "cpc_min": float(item.get("cpc_min") or 0.0),
                    "cpc_max": float(item.get("cpc_max") or 0.0),
                    "competition_index": item.get("competition_index"),
                    "monthly_searches": item.get("monthly_searches"),
                }
            )
            if len(rows) >= cap:
                if stats is not None:
                    stats["k4k_filtered_count"] = stats.get("k4k_filtered_count", 0) + filtered_count
                return rows

    rows.sort(key=lambda r: int(r.get("search_volume") or 0), reverse=True)
    if stats is not None:
        stats["k4k_filtered_count"] = stats.get("k4k_filtered_count", 0) + filtered_count
    return rows[:cap]
