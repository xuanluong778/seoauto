"""Lead Map Scanner — cấu hình chi phí, giới hạn, cache (env backend)."""

from __future__ import annotations

import json
import os
from typing import Any

from app.core.places_settings import places_api_configured, get_places_api_key
from app.services.seoauto_pricing_catalog import SEOAUTO_PLAN_SLUG_ORDER
from app.services.plan_quota_registry import lead_scanner_limits as _registry_lead_limits

_DEFAULT_PLAN_LIMITS: dict[str, dict[str, int]] = {
    slug: _registry_lead_limits(slug) for slug in (*SEOAUTO_PLAN_SLUG_ORDER, "free", "admin")
}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def lead_scanner_enabled() -> bool:
    return os.getenv("LEAD_SCANNER_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def lead_cache_ttl_sec() -> int:
    return max(60, _int_env("LEAD_SCANNER_CACHE_TTL_SEC", 3600))


def lead_scan_cooldown_sec() -> int:
    return max(10, _int_env("LEAD_SCANNER_SCAN_COOLDOWN_SEC", 60))


def lead_user_rate_limit_per_min() -> int:
    return max(1, _int_env("LEAD_SCANNER_USER_RATE_PER_MIN", 6))


def lead_ip_rate_limit_per_min() -> int:
    return max(1, _int_env("LEAD_SCANNER_IP_RATE_PER_MIN", 20))


def lead_google_cooldown_sec() -> int:
    return max(30, _int_env("LEAD_SCANNER_GOOGLE_COOLDOWN_SEC", 120))


def lead_api_retry_max() -> int:
    return max(0, min(2, _int_env("LEAD_SCANNER_API_RETRY_MAX", 2)))


def lead_allowed_limits() -> list[int]:
    return [20, 50, 100]


def lead_api_cost_estimate_usd() -> dict[str, float]:
    return {
        "search_page": _float_env("LEAD_SCANNER_COST_USD_SEARCH_PAGE", 0.032),
        "place_detail": _float_env("LEAD_SCANNER_COST_USD_PLACE_DETAIL", 0.017),
        "geocode": _float_env("LEAD_SCANNER_COST_USD_GEOCODE", 0.005),
    }


def lead_cost_alert_daily_usd() -> float:
    return _float_env("LEAD_SCANNER_ALERT_DAILY_USD", 25.0)


def lead_cost_alert_monthly_usd() -> float:
    return _float_env("LEAD_SCANNER_ALERT_MONTHLY_USD", 200.0)


def plan_limits() -> dict[str, dict[str, int]]:
    raw = (os.getenv("LEAD_SCANNER_PLAN_LIMITS_JSON") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                out: dict[str, dict[str, int]] = {}
                for slug, row in data.items():
                    if not isinstance(row, dict):
                        continue
                    out[str(slug).lower()] = {
                        "daily_scans": max(0, int(row.get("daily_scans", 0))),
                        "monthly_scans": max(0, int(row.get("monthly_scans", 0))),
                        "max_results": max(20, min(100, int(row.get("max_results", 20)))),
                    }
                if out:
                    return out
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return {k: dict(v) for k, v in _DEFAULT_PLAN_LIMITS.items()}


def limits_for_plan(plan_slug: str | None) -> dict[str, int]:
    slug = str(plan_slug or "free").strip().lower()
    limits = plan_limits()
    if slug in limits:
        return limits[slug]
    if slug in SEOAUTO_PLAN_SLUG_ORDER:
        return limits.get(slug, limits["free"])
    return limits["free"]


def places_key_status() -> dict[str, Any]:
    key = get_places_api_key()
    if not key:
        return {"configured": False, "masked": None}
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "(set)"
    return {"configured": True, "masked": masked}


def admin_snapshot() -> dict[str, Any]:
    return {
        "enabled": lead_scanner_enabled(),
        "places": places_key_status(),
        "places_configured": places_api_configured(),
        "cache_ttl_sec": lead_cache_ttl_sec(),
        "scan_cooldown_sec": lead_scan_cooldown_sec(),
        "google_cooldown_sec": lead_google_cooldown_sec(),
        "user_rate_per_min": lead_user_rate_limit_per_min(),
        "ip_rate_per_min": lead_ip_rate_limit_per_min(),
        "api_retry_max": lead_api_retry_max(),
        "allowed_limits": lead_allowed_limits(),
        "plan_limits": plan_limits(),
        "api_cost_estimate_usd": lead_api_cost_estimate_usd(),
        "alert_daily_usd": lead_cost_alert_daily_usd(),
        "alert_monthly_usd": lead_cost_alert_monthly_usd(),
        "credit_costs": {
            "basic_scan_search": _int_env("CREDIT_COST_LEAD_SCAN_SEARCH", 3),
            "place_detail": _int_env("CREDIT_COST_LEAD_PLACE_DETAIL", 2),
            "geocode": _int_env("CREDIT_COST_LEAD_GEOCODE", 1),
            "export": _int_env("CREDIT_COST_LEAD_EXPORT", 1),
        },
    }
