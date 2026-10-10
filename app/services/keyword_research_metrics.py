"""
Keyword Research metrics: competition, trend, monthly volume shaping, data provenance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.search_volume import _MONTH_KEYS

_LOG = logging.getLogger(__name__)
NA = "N/A"


def competition_label_from_index(competition_index: Any, *, provider: str | None = None) -> tuple[str, str]:
    """Map competition_index or LOW/MEDIUM/HIGH → label + data_source."""
    src = (provider or "").strip().lower()
    if src not in ("google_ads", "dataforseo"):
        src = "dataforseo"
    if competition_index is None or competition_index == "":
        return "Unknown", NA
    if hasattr(competition_index, "name") and not isinstance(competition_index, (int, float, str, bytes)):
        named = getattr(competition_index, "name", None)
        if named:
            competition_index = named
    if isinstance(competition_index, str):
        s = competition_index.strip().lower().split(".")[-1]
        if s in ("unspecified", "unknown", "none", "n/a"):
            return "Unknown", NA
        if s in ("low", "thấp"):
            return "Low", src
        if s in ("medium", "med", "trung bình", "trung binh"):
            return "Medium", src
        if s in ("high", "cao"):
            return "High", src
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
    # Google Ads competition_index is 0–100 (1 = LOW). DataForSEO is often 0–1.
    ads_100 = src == "google_ads" or x > 1
    if ads_100:
        if x == 0:
            return "Unknown", NA
        if x <= 33:
            return "Low", src
        if x <= 67:
            return "Medium", src
        return "High", src
    if x <= 0.33:
        return "Low", src
    if x <= 0.67:
        return "Medium", src
    return "High", src


_MONTH_NAME_TO_NUM = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}


def parse_monthly_search_values(monthly_searches: Any) -> list[int] | None:
    """Parse Ads/DataForSEO monthly_searches into chronological volume list (last ≤12 months)."""
    if not monthly_searches or not isinstance(monthly_searches, list):
        return None
    items: list[tuple[int, int, int]] = []
    for m in monthly_searches:
        if not isinstance(m, dict):
            continue
        try:
            y = int(m.get("year"))
        except (TypeError, ValueError):
            continue
        mo_raw = m.get("month")
        mo: int | None
        try:
            mo = int(mo_raw)
            if mo == 13:
                mo = 12
        except (TypeError, ValueError):
            token = str(mo_raw or "").upper().split(".")[-1]
            mo = _MONTH_NAME_TO_NUM.get(token)
        sv_raw = m.get("search_volume") if m.get("search_volume") is not None else m.get("monthly_searches")
        try:
            sv = int(sv_raw)
        except (TypeError, ValueError):
            continue
        if mo is None or mo < 1 or mo > 12:
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
    if src in ("dataforseo", "api"):
        return "dataforseo"
    if src == "google_ads":
        return "google_ads"
    if src == "estimated":
        return "fallback"
    return NA


def compute_trend(values: list[int] | None, *, data_source: str | None = None) -> dict[str, Any]:
    """
    Trend from real monthly volumes: compare recent 3 months vs prior 3 months.
    Returns direction up/down/stable/unknown + pct_change + data_source.
    """
    src = (data_source or "").strip().lower() if data_source else ""
    if src in ("api", "api_cache"):
        src = "dataforseo"
    elif src == "cache":
        src = "dataforseo"
    elif src not in ("google_ads", "dataforseo"):
        src = "dataforseo"
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
        return {"direction": "stable", "pct_change": 0.0, "data_source": src}
    denom = avg_prior if avg_prior > 0 else max(avg_recent, 1.0)
    pct = round((avg_recent - avg_prior) / denom * 100.0, 1)
    if pct > 5.0:
        direction = "up"
    elif pct < -5.0:
        direction = "down"
    else:
        direction = "stable"
    return {"direction": direction, "pct_change": pct, "data_source": src}


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
    is_estimated = vol_ds in ("fallback",)

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
        "is_estimated": is_estimated,
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
    """Overlay volume for keywords still missing real Ads/DFS data (partial, not full re-run)."""
    import os

    if os.getenv("VOLUME_API_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return vol_by_kw
    if not allow_api:
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
        prev = vol_by_kw.get(low) or {}
        src = str(prev.get("volume_source") or prev.get("provider") or "").lower()
        if src in ("google_ads", "dataforseo", "api", "api_cache") and not volume_metrics_gap(prev):
            continue
        cleaned.append(s)
    if not cleaned:
        return vol_by_kw

    from app.services.search_volume import _fetch_live_volumes_ads_then_dfs

    now = datetime.now(timezone.utc).isoformat()
    fetched = _fetch_live_volumes_ads_then_dfs(
        cleaned, country=country, language=language, stats=stats
    )
    refreshed = 0
    for kw, r in fetched.items():
        prev = dict(vol_by_kw.get(kw) or {})
        vol = r.get("search_volume")
        try:
            vol_i = int(vol) if vol is not None else None
        except (TypeError, ValueError):
            vol_i = None
        if vol_i is None:
            continue
        src = str(r.get("volume_source") or r.get("provider") or "dataforseo")
        merged = {
            **prev,
            **r,
            "keyword": r.get("keyword") or kw,
            "search_volume": vol_i,
            "volume_source": src,
            "provider": str(r.get("provider") or src),
            "fetched_at": now,
            "updated_at": now,
        }
        vol_by_kw[kw] = merged
        refreshed += 1
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
    avg = None
    lo = None
    hi = None
    try:
        if cpc_avg is not None and float(cpc_avg) > 0:
            avg = float(cpc_avg)
    except (TypeError, ValueError):
        avg = None
    try:
        if cpc_min is not None and float(cpc_min) > 0:
            lo = float(cpc_min)
    except (TypeError, ValueError):
        lo = None
    try:
        if cpc_max is not None and float(cpc_max) > 0:
            hi = float(cpc_max)
    except (TypeError, ValueError):
        hi = None
    if avg is None and (lo or hi):
        vals = [x for x in (lo, hi) if x]
        avg = round(sum(vals) / len(vals), 4) if vals else None
    if avg is None:
        return None, None, None, NA
    if lo is None:
        lo = avg
    if hi is None:
        hi = avg
    if src in ("dataforseo", "api", "google_ads", "api_cache", "cache"):
        ds = "cache" if from_cache or src in ("api_cache", "cache") else ("google_ads" if src == "google_ads" else "dataforseo")
        return avg, lo, hi, ds
    return avg, lo, hi, NA


def _volume_metric_flags(row: dict[str, Any]) -> tuple[bool, bool, bool]:
    has_cpc = False
    for key in ("cpc_avg", "cpc_min", "cpc_max"):
        try:
            if row.get(key) is not None and float(row.get(key)) > 0:
                has_cpc = True
                break
        except (TypeError, ValueError):
            continue
    has_monthly = parse_monthly_search_values(row.get("monthly_searches")) is not None
    label, _ds = competition_label_from_index(
        row.get("competition") if row.get("competition") not in (None, "") else row.get("competition_index"),
        provider=str(row.get("provider") or row.get("volume_source") or "") or None,
    )
    has_comp = label != "Unknown"
    return has_cpc, has_monthly, has_comp


def volume_metrics_gap(row: dict[str, Any] | None) -> bool:
    """True when CPC / 12-month series / competition still missing on a volume row."""
    if not row:
        return True
    has_cpc, has_monthly, has_comp = _volume_metric_flags(row)
    return not (has_cpc and has_monthly and has_comp)


def volume_cpc_only_gap(row: dict[str, Any] | None) -> bool:
    """True when a real provider already has volume + monthly + competition, but CPC/bid is missing."""
    if not row:
        return False
    src = str(row.get("provider") or row.get("volume_source") or "").lower()
    if src not in ("google_ads", "dataforseo", "api", "api_cache"):
        return False
    if row.get("search_volume") is None:
        return False
    has_cpc, has_monthly, has_comp = _volume_metric_flags(row)
    return (not has_cpc) and has_monthly and has_comp


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
