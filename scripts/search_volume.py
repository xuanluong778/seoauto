"""
Search volume enrichment: optional API path + deterministic heuristic fallback.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any

import json
from datetime import datetime, timezone

_COMMERCIAL = re.compile(
    r"\b(buy|price|cheap|deal|discount|order|coupon|shipping|subscription|"
    r"quote|hire|agency|software|tool|app|download|demo|trial|vs|review)\b",
    re.I,
)


def _manual_volume_override(keyword: str) -> int | None:
    k = (keyword or "").strip().lower()
    overrides = {
        "đào tạo seo": 14800,
        "dao tao seo": 14800,
    }
    return overrides.get(k)


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
            int(os.getenv("VOLUME_CACHE_TTL_SECONDS", "2592000")),  # 30 days
            json.dumps(payload, ensure_ascii=False)[:30000],
        )
    except Exception:
        return None


def _db_get(digest: str) -> dict[str, Any] | None:
    try:
        from app.db import SessionLocal
        from app.models.keyword_volume_cache import KeywordVolumeCache

        db = SessionLocal()
        try:
            row = db.query(KeywordVolumeCache).filter(KeywordVolumeCache.digest == digest).first()
            if not row:
                return None
            return {
                "keyword": row.keyword,
                "search_volume": int(row.search_volume or 0),
                "cpc_avg": float(row.cpc_avg or 0),
                "cpc_min": float(row.cpc_min or 0),
                "cpc_max": float(row.cpc_max or 0),
                "volume_source": row.volume_source,
                "confidence": float(row.confidence or 0.75),
                "country": row.country,
                "language": row.language,
            }
        finally:
            db.close()
    except Exception:
        return None


def _db_set(digest: str, payload: dict[str, Any]) -> None:
    try:
        from app.db import SessionLocal
        from app.models.keyword_volume_cache import KeywordVolumeCache

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
        "confidence": float(row.get("confidence") or 0.75),
        "country": (country or os.getenv("SERP_DEFAULT_COUNTRY", "vn")).strip().lower(),
        "language": (language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi")).strip().lower(),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _redis_set(dig, payload)
    _db_set(dig, payload)


def enrich_keyword_volumes_cached(
    keywords: list[str],
    *,
    country: str | None = None,
    language: str | None = None,
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
            chunk = int(os.getenv("VOLUME_DB_LOOKUP_CHUNK", "800"))
            chunk = max(50, min(3000, chunk))
            for i in range(0, len(digests), chunk):
                dsub = digests[i : i + chunk]
                if not dsub:
                    continue
                rows = db.query(KeywordVolumeCache).filter(KeywordVolumeCache.digest.in_(dsub)).all()
                for r in rows or []:
                    db_hits[str(r.digest)] = {
                        "keyword": str(r.keyword or ""),
                        "search_volume": int(r.search_volume or 0),
                        "volume_source": str(r.volume_source or "api_cache"),
                        "confidence": float(r.confidence or 0.75),
                        "cpc_avg": float(r.cpc_avg or 0.0),
                        "cpc_min": float(r.cpc_min or 0.0),
                        "cpc_max": float(r.cpc_max or 0.0),
                        "country": str(r.country or loc_country),
                        "language": str(r.language or loc_language),
                    }
        finally:
            db.close()
    except Exception:
        db_hits = {}

    for kw, dig in zip(cleaned, digests):
        hit = _redis_get(dig) or db_hits.get(dig)
        if hit and isinstance(hit, dict) and hit.get("keyword"):
            vs = str(hit.get("volume_source") or "").lower()
            if (
                vs in ("estimated", "bench")
                and os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes")
            ):
                misses.append(kw)
                continue
            row = {
                "keyword": kw,
                "search_volume": int(hit.get("search_volume") or 0),
                "volume_source": str(hit.get("volume_source") or "api_cache"),
                "confidence": float(hit.get("confidence") or 0.75),
                "cpc_avg": float(hit.get("cpc_avg") or 0.0),
                "cpc_min": float(hit.get("cpc_min") or 0.0),
                "cpc_max": float(hit.get("cpc_max") or 0.0),
            }
            mv = _manual_volume_override(kw)
            if mv is not None and int(row.get("search_volume") or 0) != int(mv):
                row["search_volume"] = int(mv)
                row["volume_source"] = "manual_override"
                row["confidence"] = max(float(row.get("confidence") or 0.0), 0.9)
                _cache_set_volume_row(row, country=loc_country, language=loc_language)
            hits[kw.lower()] = row
        else:
            misses.append(kw)

    # Fetch real volumes in batches (DataForSEO first) if enabled
    fetched: dict[str, dict[str, Any]] = {}
    if misses and os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes"):
        # DataForSEO batch provider (optional)
        try:
            from app.services.volume_providers.dataforseo import fetch_dataforseo_search_volume_batch

            batch_size = int(os.getenv("VOLUME_BATCH_SIZE", "100"))
            batch_size = max(10, min(700, batch_size))
            for i in range(0, len(misses), batch_size):
                chunk = misses[i : i + batch_size]
                rows = fetch_dataforseo_search_volume_batch(
                    chunk,
                    country=loc_country,
                    language=loc_language,
                )
                for r in rows or []:
                    kw = str(r.get("keyword") or "").strip()
                    if not kw:
                        continue
                    fetched[kw.lower()] = r
        except Exception:
            fetched = {}

    # Fill results (real -> cache -> heuristic)
    out: list[dict[str, Any]] = []
    for kw in cleaned:
        low = kw.lower()
        if low in fetched:
            row = fetched[low]
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
