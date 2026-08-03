"""
DataForSEO Google Ads search volume provider (batch).

Env:
- VOLUME_API_ENABLED=1
- DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD

Optional locale config (prefer explicit to avoid hardcoding):
- DATAFORSEO_LOCATION_CODE (int) e.g. 2704 for Vietnam
- DATAFORSEO_LANGUAGE_CODE (str) e.g. "vi"

If location/language codes are not configured, provider returns [] (no-op) so the
caller can fallback to cache/heuristics.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from app.services.cost_control.executor import (
    CostControlBypassError,
    execute_guarded_external,
    guarded_requests_post,
)
from app.services.cost_control.settings import cost_control_enforced
from app.services.cost_control.types import ExternalApiProvider


def _enabled() -> bool:
    return os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes")


def _auth() -> tuple[str, str] | None:
    login = (os.getenv("DATAFORSEO_LOGIN") or "").strip()
    password = (os.getenv("DATAFORSEO_PASSWORD") or "").strip()
    if not login or not password:
        return None
    return (login, password)


def _location_code(country: str | None) -> int | None:
    # Prefer explicit configuration. Avoid baking a huge mapping table into the app.
    raw = (os.getenv("DATAFORSEO_LOCATION_CODE") or "").strip()
    if raw:
        try:
            return int(raw)
        except Exception:
            return None
    return None


def _language_code(language: str | None) -> str | None:
    raw = (os.getenv("DATAFORSEO_LANGUAGE_CODE") or "").strip()
    if raw:
        return raw
    # small safe fallback for common case
    lang = (language or "").strip().lower()
    if lang in ("vi", "vi-vn"):
        return "vi"
    if lang in ("en", "en-us", "en-gb"):
        return "en"
    return None


def _dataforseo_post(
    endpoint: str,
    payload: list[dict[str, Any]],
    auth: tuple[str, str],
    *,
    action: str,
    timeout: int = 45,
) -> requests.Response | None:
    try:
        if cost_control_enforced():
            return guarded_requests_post(
                ExternalApiProvider.DATAFORSEO,
                action,
                endpoint,
                json=payload,
                auth=auth,
                timeout=timeout,
            )
        return requests.post(endpoint, json=payload, auth=auth, timeout=timeout)
    except CostControlBypassError:
        return None
    except Exception:
        return None


def fetch_dataforseo_search_volume_batch(
    keywords: list[str],
    *,
    country: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    """
    Returns list rows:
    - keyword
    - search_volume (int)
    - cpc_avg / cpc_min / cpc_max (float, optional)
    - volume_source="dataforseo"
    - confidence (float)
    """
    if not _enabled():
        return []
    auth = _auth()
    if auth is None:
        return []

    loc_code = _location_code(country)
    lang_code = _language_code(language)
    if loc_code is None or not lang_code:
        return []

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

    base = (os.getenv("DATAFORSEO_BASE_URL") or "https://api.dataforseo.com").strip().rstrip("/")
    endpoint = f"{base}/v3/keywords_data/google_ads/search_volume/live"

    # DataForSEO expects an array of tasks.
    payload = [
        {
            "keywords": cleaned,
            "location_code": loc_code,
            "language_code": lang_code,
        }
    ]

    try:
        r = _dataforseo_post(endpoint, payload, auth, action="search_volume", timeout=45)
        if r is None or r.status_code >= 400:
            return []
        data = r.json() if r.content else {}
    except Exception:
        return []

    # Parse very defensively; DataForSEO response structure can vary across plans.
    out: list[dict[str, Any]] = []
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        return []
    for t in tasks:
        res = t.get("result") or []
        if not isinstance(res, list):
            continue
        for row in res:
            kw = str(row.get("keyword") or "").strip()
            if not kw:
                continue
            vol = row.get("search_volume")
            try:
                vol_i = int(vol) if vol is not None else None
            except Exception:
                vol_i = None
            if vol_i is None:
                continue
            cpc = row.get("cpc")
            # Some responses provide a single CPC; keep min/max same.
            try:
                cpc_f = float(cpc) if cpc is not None else 0.0
            except Exception:
                cpc_f = 0.0
            out.append(
                {
                    "keyword": kw,
                    "search_volume": vol_i,
                    "cpc_avg": cpc_f,
                    "cpc_min": cpc_f,
                    "cpc_max": cpc_f,
                    "volume_source": "dataforseo",
                    "confidence": 0.9,
                }
            )
    return out


def fetch_dataforseo_keywords_for_keywords(
    seeds: list[str],
    *,
    country: str | None,
    language: str | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Google Ads Keywords For Keywords — related terms with volume/CPC.
    """
    if not _enabled():
        return []
    auth = _auth()
    if auth is None:
        return []

    loc_code = _location_code(country)
    lang_code = _language_code(language)
    if loc_code is None or not lang_code:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for k in seeds or []:
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

    limit = max(5, min(int(limit or 100), 700))
    base = (os.getenv("DATAFORSEO_BASE_URL") or "https://api.dataforseo.com").strip().rstrip("/")
    endpoint = f"{base}/v3/keywords_data/google_ads/keywords_for_keywords/live"
    payload = [
        {
            "keywords": cleaned,
            "location_code": loc_code,
            "language_code": lang_code,
            "limit": limit,
        }
    ]

    try:
        r = _dataforseo_post(endpoint, payload, auth, action="keywords_for_keywords", timeout=90)
        if r is None or r.status_code >= 400:
            return []
        data = r.json() if r.content else {}
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        return []
    for t in tasks:
        res = t.get("result") or []
        if not isinstance(res, list):
            continue
        for row in res:
            kw = str(row.get("keyword") or "").strip()
            if not kw:
                continue
            vol = row.get("search_volume")
            vol_i: int | None
            try:
                vol_i = int(vol) if vol is not None else None
            except (TypeError, ValueError):
                vol_i = None
            cpc = row.get("cpc")
            try:
                cpc_f = float(cpc) if cpc is not None else 0.0
            except (TypeError, ValueError):
                cpc_f = 0.0
            low_bid = row.get("low_top_of_page_bid")
            high_bid = row.get("high_top_of_page_bid")
            try:
                cpc_lo = float(low_bid) if low_bid is not None else cpc_f
            except (TypeError, ValueError):
                cpc_lo = cpc_f
            try:
                cpc_hi = float(high_bid) if high_bid is not None else cpc_f
            except (TypeError, ValueError):
                cpc_hi = cpc_f
            out.append(
                {
                    "keyword": kw,
                    "search_volume": vol_i,
                    "cpc_avg": cpc_f,
                    "cpc_min": cpc_lo,
                    "cpc_max": cpc_hi,
                    "competition_index": row.get("competition_index"),
                    "monthly_searches": row.get("monthly_searches"),
                    "volume_source": "dataforseo",
                    "confidence": 0.92,
                }
            )
    return out

