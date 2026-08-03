"""
Keyword Research metrics: competition, trend, monthly volume shaping, data provenance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.keyword_research_cost import check_and_record_live_call, volume_batch_size
from app.services.search_volume import _MONTH_KEYS

_LOG = logging.getLogger(__name__)
NA = "N/A"


def competition_label_from_index(competition_index: Any) -> tuple[str, str]:
    """Map DataForSEO competition_index → Low/Medium/High/Unknown + data_source."""
    if competition_index is None or competition_index == "":
        return "Unknown", NA
    if isinstance(competition_index, str):
        s = competition_index.strip().lower()
        if s in ("low", "thấp"):
            return "Low", "dataforseo"
        if s in ("medium", "med", "trung bình", "trung binh"):
            return "Medium", "dataforseo"
        if s in ("high", "cao"):
            return "High", "dataforseo"
        try:
            competition_index = float(s)
        except ValueError:
            return "Unknown", NA
    try:
        x = float(competition_index)
    except (TypeError, ValueError):
        return "Unknown", NA
    if x < 0:
        return "Unknown", NA
    if x <= 0.33:
        return "Low", "dataforseo"
    if x <= 0.67:
        return "Medium", "dataforseo"
    return "High", "dataforseo"


def parse_monthly_search_values(monthly_searches: Any) -> list[int] | None:
    """Parse DataForSEO monthly_searches into chronological volume list (last ≤12 months)."""
    if not monthly_searches or not isinstance(monthly_searches, list):
        return None
    items: list[tuple[int, int, int]] = []
    for m in monthly_searches:
        if not isinstance(m, dict):
            continue
        try:
            y = int(m.get("year"))
            mo = int(m.get("month"))
            sv = int(m.get("search_volume"))
        except (TypeError, ValueError):
            continue
        if mo < 1 or mo > 12:
            continue
        items.append((y, mo, max(0, sv)))
    if len(items) < 2:
        return None
    items.sort(key=lambda t: (t[0], t[1]))
    return [v for _, _, v in items[-12:]]


def normalize_volume_data_source(volume_source: str | None, *, from_cache: bool = False) -> str:
    src = (volume_source or NA).lower()
    if from_cache or src in ("api_cache", "cache"):
        return "cache"
    if src in ("dataforseo", "api", "google_ads"):
        return "dataforseo"
    if src == "estimated":
        return "fallback"
    return NA


def compute_trend(values: list[int] | None) -> dict[str, Any]:
    """
    Trend from real monthly volumes: compare recent 3 months vs prior 3 months.
    Returns direction up/down/stable/unknown + pct_change + data_source.
    """
    if not values or len(values) < 4:
        return {"direction": "unknown", "pct_change": None, "data_source": NA}

    if len(values) >= 6:
        prior = values[-6:-3]
        recent = values[-3:]
    else:
        mid = len(values) // 2
        prior = values[:mid]
        recent = values[mid:]

    avg_prior = sum(prior) / max(1, len(prior))
    avg_recent = sum(recent) / max(1, len(recent))
    if avg_prior <= 0 and avg_recent <= 0:
        return {"direction": "stable", "pct_change": 0.0, "data_source": "dataforseo"}
    denom = avg_prior if avg_prior > 0 else max(avg_recent, 1.0)
    pct = round((avg_recent - avg_prior) / denom * 100.0, 1)
    if pct > 5.0:
        direction = "up"
    elif pct < -5.0:
        direction = "down"
    else:
        direction = "stable"
    return {"direction": direction, "pct_change": pct, "data_source": "dataforseo"}


def _chart_series_from_values(values: list[int]) -> list[dict[str, Any]]:
    h_pc = 0.42
    out: list[dict[str, Any]] = []
    for i, name in enumerate(_MONTH_KEYS):
        all_v = values[i] if i < len(values) else 0
        pc = int(all_v * h_pc)
        mobile = max(0, all_v - pc)
        out.append({"month": name, "all": all_v, "pc": pc, "mobile": mobile})
    return out


def build_search_volume_package(
    keyword: str,
    *,
    raw_volume: int | None,
    volume_source: str | None,
    monthly_searches: Any = None,
    from_cache: bool = False,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """
    Build search_volume dict. ``display_volume`` always equals ``raw_volume`` from provider.
    Monthly series is chart-only and never changes displayed volume.
    """
    vol_ds = normalize_volume_data_source(volume_source, from_cache=from_cache)
    ts = updated_at or datetime.now(timezone.utc).isoformat()

    if raw_volume is None:
        empty = {m: None for m in _MONTH_KEYS}
        return {
            **empty,
            "raw_volume": None,
            "display_volume": None,
            "avg_monthly": None,
            "volume_source": NA,
            "data_source": NA,
            "is_estimated": False,
            "chart_series": [],
            "has_monthly_data": False,
            "updated_at": ts,
        }

    display = int(raw_volume)
    parsed = parse_monthly_search_values(monthly_searches)
    chart_series: list[dict[str, Any]] = []
    months: dict[str, int | None] = {m: None for m in _MONTH_KEYS}

    if parsed and len(parsed) >= 2:
        chart_vals = parsed[-12:]
        while len(chart_vals) < 12:
            chart_vals.insert(0, 0)
        chart_vals = chart_vals[-12:]
        months = {name: chart_vals[i] for i, name in enumerate(_MONTH_KEYS)}
        chart_series = _chart_series_from_values(chart_vals)
        has_monthly = True
    else:
        has_monthly = False

    return {
        **months,
        "raw_volume": display,
        "display_volume": display,
        "avg_monthly": display,
        "volume_source": vol_ds if vol_ds != NA else NA,
        "data_source": vol_ds,
        "is_estimated": False,
        "chart_series": chart_series,
        "has_monthly_data": has_monthly,
        "updated_at": ts,
    }


def refresh_volumes_from_search_volume_api(
    keywords: list[str],
    vol_by_kw: dict[str, dict[str, Any]],
    *,
    country: str | None,
    language: str | None,
    allow_api: bool = True,
    stats: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Overlay authoritative Google Ads search_volume/live on K4K/cache rows."""
    import os

    if os.getenv("VOLUME_API_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return vol_by_kw
    if not allow_api:
        return vol_by_kw
    try:
        from app.services.volume_providers.dataforseo import fetch_dataforseo_search_volume_batch
    except Exception:
        return vol_by_kw

    cleaned: list[str] = []
    seen: set[str] = set()
    for k in keywords or []:
        s = str(k or "").strip()
        if not s:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(s)
    if not cleaned:
        return vol_by_kw

    batch_size = volume_batch_size()
    now = datetime.now(timezone.utc).isoformat()
    refreshed = 0
    for i in range(0, len(cleaned), batch_size):
        chunk = cleaned[i : i + batch_size]
        try:
            if stats is not None:
                check_and_record_live_call(stats, label="search_volume_refresh")
            rows = fetch_dataforseo_search_volume_batch(chunk, country=country, language=language)
            if stats is not None:
                stats["api_tasks"] = stats.get("api_tasks", 0) + 1
                stats["keywords_api"] = stats.get("keywords_api", 0) + len(chunk)
        except Exception as exc:
            _LOG.warning("search_volume batch failed: %s", exc)
            continue
        for r in rows or []:
            kw = str(r.get("keyword") or "").strip()
            if not kw:
                continue
            low = kw.lower()
            prev = dict(vol_by_kw.get(low) or {})
            vol = r.get("search_volume")
            try:
                vol_i = int(vol) if vol is not None else None
            except (TypeError, ValueError):
                vol_i = None
            if vol_i is None:
                continue
            merged = {
                **prev,
                "keyword": kw,
                "search_volume": vol_i,
                "volume_source": "dataforseo",
                "fetched_at": now,
                "updated_at": now,
            }
            if r.get("cpc_avg") is not None and float(r.get("cpc_avg") or 0) > 0:
                merged["cpc_avg"] = float(r["cpc_avg"])
                merged["cpc_min"] = float(r.get("cpc_min") or r["cpc_avg"])
                merged["cpc_max"] = float(r.get("cpc_max") or r["cpc_avg"])
            vol_by_kw[low] = merged
            refreshed += 1
            if prev.get("search_volume") is not None and int(prev["search_volume"]) != vol_i:
                _LOG.info(
                    "volume_refresh keyword=%s canonical=%s raw_old=%s raw_new=%s source=dataforseo",
                    kw,
                    low,
                    prev.get("search_volume"),
                    vol_i,
                )
    _LOG.info("volume_refresh_done count=%s keywords=%s", refreshed, len(cleaned))
    return vol_by_kw


def volume_debug_row(
    keyword: str,
    *,
    canonical_keyword: str,
    raw_volume: int | None,
    display_volume: int | None,
    data_source: str,
    updated_at: str | None,
) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "canonical_keyword": canonical_keyword,
        "raw_volume": raw_volume,
        "display_volume": display_volume,
        "data_source": data_source,
        "updated_at": updated_at or NA,
    }


def cpc_package(
    *,
    cpc_avg: float | None,
    cpc_min: float | None,
    cpc_max: float | None,
    volume_source: str | None,
    from_cache: bool = False,
) -> tuple[float | None, float | None, float | None, str]:
    """Return CPC triplet + data_source; no fake CPC when missing."""
    src = (volume_source or "").lower()
    if cpc_avg is not None and float(cpc_avg) > 0 and src in ("dataforseo", "api", "google_ads", "api_cache", "cache"):
        lo = float(cpc_min) if cpc_min is not None else float(cpc_avg)
        hi = float(cpc_max) if cpc_max is not None else float(cpc_avg)
        ds = "cache" if from_cache or src in ("api_cache", "cache") else "dataforseo"
        return float(cpc_avg), lo, hi, ds
    return None, None, None, NA


def build_data_warnings(
    *,
    volume_ds: str,
    cpc_ds: str,
    competition_ds: str,
    trend_ds: str,
    intent: str,
    kd_label: str | None,
) -> list[str]:
    warnings: list[str] = []
    if volume_ds in (NA, "fallback"):
        warnings.append("volume_missing" if volume_ds == NA else "volume_estimated")
    if cpc_ds == NA:
        warnings.append("cpc_missing")
    if competition_ds == NA:
        warnings.append("competition_missing")
    if trend_ds == NA:
        warnings.append("trend_missing")
    if intent in ("unknown", "", NA):
        warnings.append("intent_unknown")
    if kd_label in (None, NA, ""):
        warnings.append("kd_unavailable")
    return warnings
