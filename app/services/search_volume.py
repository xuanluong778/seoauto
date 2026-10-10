"""
Search volume enrichment: optional API path + deterministic heuristic fallback.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any

from app.services.keyword_research_cost import check_and_record_live_call, volume_batch_size, volume_cache_ttl_seconds

import json
import logging
from datetime import datetime, timezone

_LOG = logging.getLogger(__name__)

_COMMERCIAL = re.compile(
    r"\b(buy|price|cheap|deal|discount|order|coupon|shipping|subscription|"
    r"quote|hire|agency|software|tool|app|download|demo|trial|vs|review)\b",
    re.I,
)


def _manual_volume_override(keyword: str) -> int | None:
    # Never paint a hardcoded volume as real Ads/DFS data (e.g. 14800 for "đào tạo seo").
    return None


def _heuristic_volume(keyword: str) -> tuple[int, float]:
    """Returns (estimated_monthly_volume, confidence 0-1)."""
    k = (keyword or "").strip().lower()
    if not k:
        return 0, 0.1
    mv = _manual_volume_override(k)
    if mv is not None:
        return int(mv), 0.9
    words = k.split()
    wc = max(1, len(words))
    char = len(k)
    # Shorter head-ish terms get higher proxy volume
    base = 1200.0 / math.sqrt(wc) + 400.0 / math.log2(char + 2)
    h = int(hashlib.md5(k.encode(), usedforsecurity=False).hexdigest()[:6], 16)
    jitter = 0.78 + (h % 45) / 100.0
    vol = int(max(10, min(500000, base * jitter)))
    conf = 0.32
    if wc == 1 and char <= 10:
        conf = 0.38
    if _COMMERCIAL.search(k):
        vol = int(vol * 1.15)
        conf = min(0.48, conf + 0.08)
    if wc >= 4:
        conf = max(0.22, conf - 0.06)
    return vol, round(conf, 3)


def fetch_volume_from_api(keyword: str) -> dict[str, Any] | None:
    """
    Hook for Google Ads Keyword Planner or third-party APIs.

    Set ``KEYWORD_VOLUME_API_URL`` + ``KEYWORD_VOLUME_API_KEY`` to POST JSON
    ``{"keyword": "..."}`` and expect ``{"volume": int}`` or ``null`` on miss.
    """
    if os.getenv("VOLUME_API_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return None
    url = (os.getenv("KEYWORD_VOLUME_API_URL") or "").strip()
    if not url:
        return None
    try:
        import requests

        headers = {"Content-Type": "application/json"}
        key = os.getenv("KEYWORD_VOLUME_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        r = requests.post(url, json={"keyword": keyword}, headers=headers, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        v = data.get("volume") or data.get("search_volume")
        if v is None:
            return None
        return {
            "keyword": keyword,
            "search_volume": int(v),
            "volume_source": "api",
            "confidence": float(data.get("confidence") or 0.75),
        }
    except Exception:
        return None


def enrich_keyword_volume(keyword: str) -> dict[str, Any]:
    """Single keyword → volume row."""
    # Try cached batch path first (if enabled)
    batch = enrich_keyword_volumes_cached([keyword])
    if batch and batch[0]:
        return batch[0]
    api = fetch_volume_from_api(keyword)
    if api:
        _cache_set_volume_row(api)
        return api
    v, c = _heuristic_volume(keyword)
    return {
        "keyword": keyword,
        "search_volume": v,
        "volume_source": "estimated",
        "confidence": c,
    }


def enrich_keyword_volumes(keywords: list[str]) -> list[dict[str, Any]]:
    return [enrich_keyword_volume(k) for k in keywords]


def _cache_key(keyword: str, *, country: str | None = None, language: str | None = None) -> str:
    raw = "|".join(
        [
            (keyword or "").strip().lower(),
            (country or os.getenv("SERP_DEFAULT_COUNTRY", "vn")).strip().lower(),
            (language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi")).strip().lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _redis_get(digest: str) -> dict[str, Any] | None:
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        raw = r.get(f"volume:v1:{digest}")
        if raw:
            return json.loads(raw)
    except Exception:
        return None
    return None


def _redis_set(digest: str, payload: dict[str, Any]) -> None:
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        r.setex(
            f"volume:v1:{digest}",
            volume_cache_ttl_seconds(),
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception:
        return None


_VOLUME_EXTRA_KEYS = (
    "monthly_searches",
    "competition",
    "competition_index",
    "provider",
    "cpc_source",
    "monthly_source",
    "competition_source",
)
_VOLUME_CACHE_EXTRA_READY = False


def _ensure_volume_cache_extra_json() -> None:
    """Additive extra_json column so Postgres does not drop monthly/competition."""
    global _VOLUME_CACHE_EXTRA_READY
    if _VOLUME_CACHE_EXTRA_READY:
        return
    try:
        from sqlalchemy import inspect, text

        from app.db import engine

        insp = inspect(engine)
        if "keyword_volume_cache" not in set(insp.get_table_names() or []):
            _VOLUME_CACHE_EXTRA_READY = True
            return
        cols = {c["name"] for c in insp.get_columns("keyword_volume_cache")}
        if "extra_json" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE keyword_volume_cache ADD COLUMN extra_json TEXT"))
        _VOLUME_CACHE_EXTRA_READY = True
    except Exception:
        return


def _volume_extra_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key in _VOLUME_EXTRA_KEYS:
        if payload.get(key) is not None:
            extra[key] = payload.get(key)
    return extra


def _apply_volume_extra(row: dict[str, Any], extra: Any) -> dict[str, Any]:
    if not isinstance(extra, dict):
        return row
    for key in _VOLUME_EXTRA_KEYS:
        if extra.get(key) is not None:
            row[key] = extra.get(key)
    return row


def _parse_extra_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _row_from_db_cache(row: Any, *, loc_country: str, loc_language: str) -> dict[str, Any]:
    out = {
        "keyword": str(getattr(row, "keyword", "") or ""),
        "search_volume": int(getattr(row, "search_volume", 0) or 0),
        "volume_source": str(getattr(row, "volume_source", None) or "api_cache"),
        "confidence": float(getattr(row, "confidence", None) or 0.75),
        "cpc_avg": float(getattr(row, "cpc_avg", None) or 0.0),
        "cpc_min": float(getattr(row, "cpc_min", None) or 0.0),
        "cpc_max": float(getattr(row, "cpc_max", None) or 0.0),
        "country": str(getattr(row, "country", None) or loc_country),
        "language": str(getattr(row, "language", None) or loc_language),
        "provider": str(getattr(row, "volume_source", None) or "api_cache"),
    }
    return _apply_volume_extra(out, _parse_extra_json(getattr(row, "extra_json", None)))


def _db_get(digest: str) -> dict[str, Any] | None:
    try:
        _ensure_volume_cache_extra_json()
        from app.db import SessionLocal
        from app.models.keyword_volume_cache import KeywordVolumeCache

        db = SessionLocal()
        try:
            row = db.query(KeywordVolumeCache).filter(KeywordVolumeCache.digest == digest).first()
            if not row:
                return None
            return _row_from_db_cache(row, loc_country=str(row.country or "vn"), loc_language=str(row.language or "vi"))
        finally:
            db.close()
    except Exception:
        return None


def _db_set(digest: str, payload: dict[str, Any]) -> None:
    try:
        _ensure_volume_cache_extra_json()
        from app.db import SessionLocal
        from app.models.keyword_volume_cache import KeywordVolumeCache

        extra_s = json.dumps(_volume_extra_from_payload(payload), ensure_ascii=False)
        db = SessionLocal()
        try:
            existing = db.query(KeywordVolumeCache).filter(KeywordVolumeCache.digest == digest).first()
            if existing:
                existing.keyword = str(payload.get("keyword") or "")[:200]
                existing.country = str(payload.get("country") or "")[:16]
                existing.language = str(payload.get("language") or "")[:16]
                existing.search_volume = int(payload.get("search_volume") or 0)
                existing.cpc_avg = str(payload.get("cpc_avg") or "0")[:32]
                existing.cpc_min = str(payload.get("cpc_min") or "0")[:32]
                existing.cpc_max = str(payload.get("cpc_max") or "0")[:32]
                existing.volume_source = str(payload.get("volume_source") or "api_cache")[:32]
                existing.confidence = str(payload.get("confidence") or "0.75")[:16]
                existing.extra_json = extra_s
            else:
                db.add(
                    KeywordVolumeCache(
                        digest=digest,
                        keyword=str(payload.get("keyword") or "")[:200],
                        country=str(payload.get("country") or "")[:16],
                        language=str(payload.get("language") or "")[:16],
                        search_volume=int(payload.get("search_volume") or 0),
                        cpc_avg=str(payload.get("cpc_avg") or "0")[:32],
                        cpc_min=str(payload.get("cpc_min") or "0")[:32],
                        cpc_max=str(payload.get("cpc_max") or "0")[:32],
                        volume_source=str(payload.get("volume_source") or "api_cache")[:32],
                        confidence=str(payload.get("confidence") or "0.75")[:16],
                        extra_json=extra_s,
                    )
                )
            db.commit()
        finally:
            db.close()
    except Exception:
        return None


def _cache_set_volume_row(row: dict[str, Any], *, country: str | None = None, language: str | None = None) -> None:
    kw = str(row.get("keyword") or "").strip()
    if not kw:
        return
    dig = _cache_key(kw, country=country, language=language)
    payload = {
        "keyword": kw,
        "search_volume": int(row.get("search_volume") or 0),
        "cpc_avg": float(row.get("cpc_avg") or 0.0) if row.get("cpc_avg") is not None else 0.0,
        "cpc_min": float(row.get("cpc_min") or 0.0) if row.get("cpc_min") is not None else 0.0,
        "cpc_max": float(row.get("cpc_max") or 0.0) if row.get("cpc_max") is not None else 0.0,
        "volume_source": str(row.get("volume_source") or "api"),
        "provider": str(row.get("provider") or row.get("volume_source") or "api"),
        "confidence": float(row.get("confidence") or 0.75),
        "country": (country or os.getenv("SERP_DEFAULT_COUNTRY", "vn")).strip().lower(),
        "language": (language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi")).strip().lower(),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(_volume_extra_from_payload(row))
    payload["provider"] = str(row.get("provider") or row.get("volume_source") or "api")
    _redis_set(dig, payload)
    _db_set(dig, payload)


def peek_volume_cache_status(
    keywords: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Đếm cache hit/miss trước khi gọi API — không gọi DataForSEO."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for k in keywords or []:
        s = str(k or "").strip()
        if not s or len(s) > 200:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(s)
    if not cleaned:
        return {"total": 0, "hits": 0, "misses": 0, "miss_keywords": []}

    loc_country = (country or os.getenv("SERP_DEFAULT_COUNTRY", "vn")).strip().lower()
    loc_language = (language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi")).strip().lower()
    digests = [_cache_key(kw, country=loc_country, language=loc_language) for kw in cleaned]
    db_hits: dict[str, dict[str, Any]] = {}
    try:
        from app.db import SessionLocal
        from app.models.keyword_volume_cache import KeywordVolumeCache

        db = SessionLocal()
        try:
            chunk = int(os.getenv("VOLUME_DB_LOOKUP_CHUNK", "800"))
            chunk = max(50, min(3000, chunk))
            for i in range(0, len(digests), chunk):
                dsub = digests[i : i + chunk]
                rows = db.query(KeywordVolumeCache).filter(KeywordVolumeCache.digest.in_(dsub)).all()
                for r in rows or []:
                    db_hits[str(r.digest)] = {"volume_source": str(r.volume_source or "api_cache")}
        finally:
            db.close()
    except Exception:
        db_hits = {}

    hits = 0
    misses: list[str] = []
    for kw, dig in zip(cleaned, digests):
        hit = _redis_get(dig) or db_hits.get(dig)
        if hit and isinstance(hit, dict):
            vs = str(hit.get("volume_source") or "").lower()
            if (
                vs in ("estimated", "bench")
                and os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes")
            ):
                misses.append(kw)
                continue
            hits += 1
        else:
            misses.append(kw)

    return {
        "total": len(cleaned),
        "hits": hits,
        "misses": len(misses),
        "miss_keywords": misses,
    }


def _ingest_volume_rows(rows: list[dict[str, Any]] | None, dest: dict[str, dict[str, Any]]) -> None:
    for r in rows or []:
        kw = str(r.get("keyword") or "").strip()
        if not kw:
            continue
        dest[kw.lower()] = r


def _fill_missing_volume_fields(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Copy only missing CPC / monthly / competition from extra; keep Ads volume/provider."""
    from app.services.keyword_research_metrics import competition_label_from_index, parse_monthly_search_values

    out = dict(base)
    extra_src = str(extra.get("provider") or extra.get("volume_source") or "dataforseo")

    def _pos(row: dict[str, Any]) -> bool:
        for key in ("cpc_avg", "cpc_min", "cpc_max"):
            try:
                if row.get(key) is not None and float(row.get(key)) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _has_comp(row: dict[str, Any]) -> bool:
        label, _ds = competition_label_from_index(
            row.get("competition") if row.get("competition") not in (None, "") else row.get("competition_index"),
            provider=str(row.get("provider") or row.get("volume_source") or "") or None,
        )
        return label != "Unknown"

    if not _pos(out) and _pos(extra):
        out["cpc_avg"] = extra.get("cpc_avg")
        out["cpc_min"] = extra.get("cpc_min")
        out["cpc_max"] = extra.get("cpc_max")
        out["cpc_source"] = extra_src
    if parse_monthly_search_values(out.get("monthly_searches")) is None and extra.get("monthly_searches"):
        out["monthly_searches"] = extra.get("monthly_searches")
        out["monthly_source"] = extra_src
    if not _has_comp(out) and _has_comp(extra):
        if extra.get("competition") is not None:
            out["competition"] = extra.get("competition")
        if extra.get("competition_index") is not None:
            out["competition_index"] = extra.get("competition_index")
        out["competition_source"] = extra_src
    return out


def _provider_error_code(exc: BaseException) -> str:
    for attr in ("code", "error_code", "status_code", "reason"):
        val = getattr(exc, attr, None)
        if val not in (None, ""):
            return f"{type(exc).__name__}:{val}"
    return type(exc).__name__


def _dfs_fill_missing_volume_fields(
    dfs_keys: list[str],
    fetched: dict[str, dict[str, Any]],
    *,
    country: str | None,
    language: str | None,
    stats: dict[str, Any] | None = None,
) -> None:
    """DataForSEO field-level fill for Ads misses / CPC gaps. Does not replace Ads volume."""
    if not dfs_keys:
        return
    from app.services.volume_providers.dataforseo import fetch_dataforseo_search_volume_batch

    batch_size = volume_batch_size()
    for i in range(0, len(dfs_keys), batch_size):
        chunk = dfs_keys[i : i + batch_size]
        try:
            check_and_record_live_call(stats, label="search_volume_batch")
            rows = fetch_dataforseo_search_volume_batch(
                chunk,
                country=country,
                language=language,
            )
            if stats is not None:
                stats["api_tasks"] = stats.get("api_tasks", 0) + 1
                stats["keywords_api"] = stats.get("keywords_api", 0) + len(chunk)
            dfs_map: dict[str, dict[str, Any]] = {}
            _ingest_volume_rows(rows, dfs_map)
            for kw, extra in dfs_map.items():
                prev = fetched.get(kw)
                fetched[kw] = _fill_missing_volume_fields(prev, extra) if prev else extra
        except Exception as exc:
            _LOG.warning(
                "dataforseo_gap_fill_error provider=dataforseo error=%s keywords=%s",
                _provider_error_code(exc),
                len(chunk),
                exc_info=True,
            )


def _fetch_live_volumes_ads_then_dfs(
    misses: list[str],
    *,
    country: str | None,
    language: str | None,
    stats: dict[str, Any] | None = None,
    allow_dfs: bool = True,
    ads_keys: list[str] | None = None,
    dfs_only_keys: list[str] | None = None,
    base_rows: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Google Ads first; DataForSEO only for keywords Ads missed or field gaps."""
    from app.services.keyword_research_metrics import volume_metrics_gap

    fetched: dict[str, dict[str, Any]] = dict(base_rows or {})
    ads_remaining = list(ads_keys if ads_keys is not None else misses)
    field_only = [k for k in (dfs_only_keys or []) if k]
    if not ads_remaining and not field_only:
        return fetched

    try:
        from app.services.volume_providers.google_ads import (
            fetch_google_ads_historical_metrics,
            google_ads_configured,
            singleflight,
        )
    except Exception as exc:
        _LOG.warning(
            "google_ads_volume_import_error provider=google_ads error=%s",
            _provider_error_code(exc),
            exc_info=True,
        )
        google_ads_configured = lambda: False  # type: ignore[assignment]
        fetch_google_ads_historical_metrics = None  # type: ignore[assignment]
        singleflight = None  # type: ignore[assignment]

    batch_size = volume_batch_size()
    if ads_remaining and google_ads_configured() and fetch_google_ads_historical_metrics is not None:
        for i in range(0, len(ads_remaining), batch_size):
            chunk = ads_remaining[i : i + batch_size]
            flight_key = "ads_vol:" + hashlib.sha256(
                "|".join([country or "", language or ""] + [c.lower() for c in chunk]).encode()
            ).hexdigest()

            def _ads_chunk(c=chunk) -> list[dict[str, Any]]:
                check_and_record_live_call(stats, label="google_ads_volume")
                rows = fetch_google_ads_historical_metrics(c, country=country, language=language)
                if stats is not None:
                    stats["api_tasks"] = stats.get("api_tasks", 0) + 1
                    stats["keywords_api"] = stats.get("keywords_api", 0) + len(c)
                return rows or []

            try:
                rows = singleflight(flight_key, _ads_chunk) if singleflight else _ads_chunk()
                _ingest_volume_rows(rows, fetched)
            except Exception as exc:
                _LOG.warning(
                    "google_ads_volume_error provider=google_ads error=%s keywords=%s",
                    _provider_error_code(exc),
                    len(chunk),
                    exc_info=True,
                )
                continue

    remaining = [k for k in ads_remaining if k.lower() not in fetched]
    incomplete = [
        k
        for k in ads_remaining
        if k.lower() in fetched and volume_metrics_gap(fetched[k.lower()])
    ]
    dfs_keys = remaining + [k for k in incomplete if k not in remaining]
    for k in field_only:
        if k not in dfs_keys:
            dfs_keys.append(k)
    if dfs_keys and allow_dfs:
        _dfs_fill_missing_volume_fields(
            dfs_keys,
            fetched,
            country=country,
            language=language,
            stats=stats,
        )
    return fetched


def enrich_keyword_volumes_cached(
    keywords: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
    allow_api: bool = True,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Batch-friendly cached fetch.

    - If VOLUME_API_ENABLED=0: returns heuristic rows (still cached path is skipped).
    - If Redis is available: reads/writes ``volume:v1:{digest}``.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for k in keywords or []:
        s = str(k or "").strip()
        if not s or len(s) > 200:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(s)
    if not cleaned:
        return []

    loc_country = (country or os.getenv("SERP_DEFAULT_COUNTRY", "vn")).strip().lower()
    loc_language = (language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi")).strip().lower()

    hits: dict[str, dict[str, Any]] = {}
    misses: list[str] = []
    # Fast path: batch DB lookup to avoid opening a DB session per keyword.
    # Redis still uses per-key get; DB is the bigger hotspot on SQLite.
    digests: list[str] = [_cache_key(kw, country=loc_country, language=loc_language) for kw in cleaned]
    db_hits: dict[str, dict[str, Any]] = {}
    try:
        from app.db import SessionLocal
        from app.models.keyword_volume_cache import KeywordVolumeCache

        db = SessionLocal()
        try:
            _ensure_volume_cache_extra_json()
            chunk = int(os.getenv("VOLUME_DB_LOOKUP_CHUNK", "800"))
            chunk = max(50, min(3000, chunk))
            for i in range(0, len(digests), chunk):
                dsub = digests[i : i + chunk]
                if not dsub:
                    continue
                rows = db.query(KeywordVolumeCache).filter(KeywordVolumeCache.digest.in_(dsub)).all()
                for r in rows or []:
                    db_hits[str(r.digest)] = _row_from_db_cache(
                        r, loc_country=loc_country, loc_language=loc_language
                    )
        finally:
            db.close()
    except Exception:
        db_hits = {}

    from app.services.keyword_research_metrics import volume_cpc_only_gap, volume_metrics_gap

    hits: dict[str, dict[str, Any]] = {}
    misses: list[str] = []
    dfs_field_only: list[str] = []
    for kw, dig in zip(cleaned, digests):
        hit = _redis_get(dig) or db_hits.get(dig)
        if hit and isinstance(hit, dict) and hit.get("keyword"):
            vs = str(hit.get("volume_source") or "").lower()
            api_on = os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes")
            row = {
                "keyword": kw,
                "search_volume": int(hit.get("search_volume") or 0),
                "volume_source": str(hit.get("volume_source") or "api_cache"),
                "provider": str(hit.get("provider") or hit.get("volume_source") or "api_cache"),
                "confidence": float(hit.get("confidence") or 0.75),
                "cpc_avg": float(hit.get("cpc_avg") or 0.0),
                "cpc_min": float(hit.get("cpc_min") or 0.0),
                "cpc_max": float(hit.get("cpc_max") or 0.0),
            }
            if hit.get("monthly_searches") is not None:
                row["monthly_searches"] = hit.get("monthly_searches")
            if hit.get("competition_index") is not None:
                row["competition_index"] = hit.get("competition_index")
            if hit.get("competition") is not None:
                row["competition"] = hit.get("competition")
            for _src_key in ("cpc_source", "monthly_source", "competition_source"):
                if hit.get(_src_key):
                    row[_src_key] = hit.get(_src_key)
            stale_src = vs in ("estimated", "bench", "manual_override", "heuristic")
            if api_on and stale_src:
                misses.append(kw)
                continue
            if api_on and volume_cpc_only_gap(row):
                hits[kw.lower()] = row
                dfs_field_only.append(kw)
                continue
            if api_on and volume_metrics_gap(row):
                misses.append(kw)
                hits[kw.lower()] = row
                continue
            hits[kw.lower()] = row
        else:
            misses.append(kw)

    if stats is not None:
        stats["cache_hits"] = stats.get("cache_hits", 0) + len(hits)
        stats["keywords_total"] = len(cleaned)
        stats["keywords_api"] = stats.get("keywords_api", 0)

    fetched: dict[str, dict[str, Any]] = {}
    if (misses or dfs_field_only) and os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes"):
        base_rows = {k.lower(): hits[k.lower()] for k in dfs_field_only if k.lower() in hits}
        fetched = _fetch_live_volumes_ads_then_dfs(
            misses,
            country=loc_country,
            language=loc_language,
            stats=stats,
            allow_dfs=bool(allow_api),
            ads_keys=misses,
            dfs_only_keys=dfs_field_only,
            base_rows=base_rows,
        )

    # Fill results (real -> cache -> heuristic)
    out: list[dict[str, Any]] = []
    for kw in cleaned:
        low = kw.lower()
        if low in fetched:
            live = fetched[low]
            prev = hits.get(low)
            if prev:
                prev_src = str(prev.get("volume_source") or prev.get("provider") or "").lower()
                live_src = str(live.get("volume_source") or live.get("provider") or "").lower()
                if prev_src in ("google_ads", "dataforseo", "api", "api_cache") and live_src == "dataforseo":
                    row = _fill_missing_volume_fields(prev, live)
                elif live_src in ("google_ads", "dataforseo", "api"):
                    row = _fill_missing_volume_fields(live, prev)
                else:
                    row = _fill_missing_volume_fields(prev, live)
            else:
                row = live
            _cache_set_volume_row(row, country=loc_country, language=loc_language)
            out.append(row)
        elif low in hits:
            out.append(hits[low])
        else:
            v, c = _heuristic_volume(kw)
            src = "manual_override" if _manual_volume_override(kw) is not None else "estimated"
            out.append(
                {
                    "keyword": kw,
                    "search_volume": v,
                    "volume_source": src,
                    "provider": "heuristic" if src == "estimated" else src,
                    "confidence": c,
                    "cpc_avg": 0.0,
                    "cpc_min": 0.0,
                    "cpc_max": 0.0,
                }
            )
    return out


_MONTH_KEYS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)


def monthly_search_volume_shape(
    keyword: str,
    *,
    avg_monthly: int | None,
    volume_source: str,
) -> dict[str, Any]:
    """
    Build 12-month buckets around ``avg_monthly``.

    * Real providers (``api``, ``dataforseo``, ``api_cache``): flat monthly at API average.
    * ``estimated``: deterministic seasonal projection — **not** real Google monthly data.
    """
    src = (volume_source or "estimated").lower()
    avg = int(avg_monthly or 0) if avg_monthly is not None else 0
    real_sources = frozenset({"api", "dataforseo", "api_cache", "google_ads"})
    is_real = src in real_sources

    if avg <= 0 and not is_real:
        avg, _conf = _heuristic_volume(keyword)
        src = "estimated"
        is_real = False

    if is_real:
        rounded = [max(0, int(round(avg)))] * 12
        recomputed_avg = float(avg)
        is_estimated = False
        out_src = src
    else:
        h = int(hashlib.md5(keyword.strip().lower().encode(), usedforsecurity=False).hexdigest()[:8], 16)
        weights: list[float] = []
        for i in range(12):
            w = 0.82 + ((h >> (i * 3)) & 0x1F) / 80.0
            if i in (9, 10, 11):
                w *= 1.06
            weights.append(w)
        s = sum(weights) or 1.0
        rounded = [max(0, int(round(avg * 12 * weights[i] / s))) for i in range(12)]
        drift = avg * 12 - sum(rounded)
        if drift != 0 and rounded:
            idx = max(range(12), key=lambda i: rounded[i])
            rounded[idx] = max(0, rounded[idx] + drift)
        recomputed_avg = round(sum(rounded) / 12.0, 1)
        is_estimated = True
        out_src = src

    h_pc = int(hashlib.md5((keyword + "|pc").encode(), usedforsecurity=False).hexdigest()[:8], 16)
    pc_ratio_base = 0.36 + (h_pc % 20) / 100.0
    chart_series: list[dict[str, Any]] = []
    months: dict[str, int] = {}
    for i, name in enumerate(_MONTH_KEYS):
        all_v = rounded[i]
        pr = pc_ratio_base + ((h_pc >> (i * 2)) & 7) / 200.0
        pr = min(0.62, max(0.28, pr))
        pc = int(all_v * pr)
        mobile = max(0, all_v - pc)
        months[name] = all_v
        chart_series.append({"month": name, "all": all_v, "pc": pc, "mobile": mobile})

    return {
        **months,
        "avg_monthly": recomputed_avg,
        "volume_source": out_src,
        "is_estimated": is_estimated,
        "chart_series": chart_series,
    }
